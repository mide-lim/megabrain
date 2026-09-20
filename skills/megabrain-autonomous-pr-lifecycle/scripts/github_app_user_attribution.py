#!/usr/bin/env python3
"""Protected GitHub App user-to-server attribution for B4.2 P3."""
from __future__ import annotations

import base64
import grp
import json
import os
import pwd
import re
import stat
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

API_ROOT = "https://api.github.com"
OAUTH_TOKEN_URL = "https://github.com/login/oauth/access_token"
DEVICE_CODE_URL = "https://github.com/login/device/code"
API_VERSION = "2026-03-10"
REPOSITORY = "mide-lim/megabrain"
REPOSITORY_NAME = "megabrain"
EXPECTED_LOGIN = "mide-lim"
EXPECTED_USER = "megabrain-hermes"
EXPECTED_GROUP = "megabrain-hermes"
CONFIG_DIRECTORY = Path("/home/megabrain-hermes/.config/megabrain-hermes/github-app")
CONFIG_PATH = CONFIG_DIRECTORY / "user-attribution.conf"
CLIENT_SECRET_PATH = CONFIG_DIRECTORY / "client-secret.txt"
REFRESH_TOKEN_PATH = CONFIG_DIRECTORY / "user-refresh-token.txt"
MAX_FILE_BYTES = 4096
CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9._-]{8,128}$")
EXPECTED_SCOPED_PERMISSIONS = {"pull_requests": "write"}
ALLOWED_SCOPED_PERMISSION_KEYS = frozenset({"pull_requests", "metadata"})


class UserAttributionError(Exception):
    """Sanitized, fail-closed user attribution failure."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class UserAttributionSettings:
    client_id: str
    expected_login: str
    client_secret_path: str
    refresh_token_path: str


@dataclass(frozen=True)
class ScopedPrCredential:
    token: str
    actor_login: str
    permissions: dict[str, str]
    scope: dict[str, Any]
    settings: UserAttributionSettings


def _identity() -> tuple[int, int]:
    try:
        user = pwd.getpwnam(EXPECTED_USER)
        group = grp.getgrnam(EXPECTED_GROUP)
    except KeyError as exc:
        raise UserAttributionError("user_attribution_identity_rejected") from exc
    if user.pw_gid != group.gr_gid:
        raise UserAttributionError("user_attribution_identity_rejected")
    return user.pw_uid, group.gr_gid


def _same_identity(first: os.stat_result, second: os.stat_result) -> bool:
    return first.st_dev == second.st_dev and first.st_ino == second.st_ino


def _validate_parent_chain(uid: int, gid: int) -> None:
    components = (
        (Path("/"), 0, 0),
        (Path("/home"), 0, 0),
        (Path("/home/megabrain-hermes"), uid, gid),
        (Path("/home/megabrain-hermes/.config"), uid, gid),
        (Path("/home/megabrain-hermes/.config/megabrain-hermes"), uid, gid),
        (CONFIG_DIRECTORY, uid, gid),
    )
    for path, expected_uid, expected_gid in components:
        try:
            info = os.lstat(path)
        except OSError as exc:
            raise UserAttributionError("user_attribution_parent_rejected") from exc
        if (
            stat.S_ISLNK(info.st_mode)
            or not stat.S_ISDIR(info.st_mode)
            or info.st_uid != expected_uid
            or info.st_gid != expected_gid
            or stat.S_IMODE(info.st_mode) & 0o022
        ):
            raise UserAttributionError("user_attribution_parent_rejected")


def _read_fixed_file(path: Path, *, code: str) -> bytes:
    uid, gid = _identity()
    _validate_parent_chain(uid, gid)
    if path.parent != CONFIG_DIRECTORY:
        raise UserAttributionError(code)
    try:
        before = os.lstat(path)
    except OSError as exc:
        raise UserAttributionError(code) from exc
    if (
        stat.S_ISLNK(before.st_mode)
        or not stat.S_ISREG(before.st_mode)
        or before.st_uid != uid
        or before.st_gid != gid
        or stat.S_IMODE(before.st_mode) not in {0o400, 0o600}
        or before.st_size > MAX_FILE_BYTES
    ):
        raise UserAttributionError(code)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise UserAttributionError(code) from exc
    try:
        opened = os.fstat(descriptor)
        if (
            not _same_identity(before, opened)
            or not stat.S_ISREG(opened.st_mode)
            or opened.st_uid != uid
            or opened.st_gid != gid
            or stat.S_IMODE(opened.st_mode) not in {0o400, 0o600}
        ):
            raise UserAttributionError(code)
        payload = os.read(descriptor, MAX_FILE_BYTES + 1)
        if len(payload) > MAX_FILE_BYTES:
            raise UserAttributionError(code)
    except UserAttributionError:
        raise
    except OSError as exc:
        raise UserAttributionError(code) from exc
    finally:
        os.close(descriptor)
    try:
        after = os.lstat(path)
    except OSError as exc:
        raise UserAttributionError(code) from exc
    if not _same_identity(opened, after):
        raise UserAttributionError(code)
    return payload


def _parse_single_line_secret(payload: bytes, *, prefix: str | None, code: str) -> str:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UserAttributionError(code) from exc
    if not text.endswith("\n") or text.count("\n") != 1:
        raise UserAttributionError(code)
    value = text[:-1]
    if not value or len(value) > 2048 or any(character.isspace() for character in value):
        raise UserAttributionError(code)
    if prefix is not None and not value.startswith(prefix):
        raise UserAttributionError(code)
    return value


def _parse_config(payload: bytes) -> UserAttributionSettings:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UserAttributionError("user_attribution_config_rejected") from exc
    if not text.endswith("\n") or "\r" in text:
        raise UserAttributionError("user_attribution_config_rejected")
    lines = text[:-1].split("\n")
    if len(lines) != 4:
        raise UserAttributionError("user_attribution_config_rejected")
    values: dict[str, str] = {}
    for line in lines:
        if line.count("=") != 1:
            raise UserAttributionError("user_attribution_config_rejected")
        key, value = line.split("=", 1)
        if not key or not value or key in values or any(character.isspace() for character in key + value):
            raise UserAttributionError("user_attribution_config_rejected")
        values[key] = value
    expected = {"github_app_client_id", "expected_login", "client_secret_path", "refresh_token_path"}
    if set(values) != expected:
        raise UserAttributionError("user_attribution_config_rejected")
    if not CLIENT_ID_RE.fullmatch(values["github_app_client_id"]):
        raise UserAttributionError("user_attribution_client_id_rejected")
    if values["expected_login"] != EXPECTED_LOGIN:
        raise UserAttributionError("user_attribution_actor_rejected")
    if values["client_secret_path"] != str(CLIENT_SECRET_PATH):
        raise UserAttributionError("user_attribution_secret_path_rejected")
    if values["refresh_token_path"] != str(REFRESH_TOKEN_PATH):
        raise UserAttributionError("user_attribution_refresh_path_rejected")
    return UserAttributionSettings(
        client_id=values["github_app_client_id"],
        expected_login=values["expected_login"],
        client_secret_path=values["client_secret_path"],
        refresh_token_path=values["refresh_token_path"],
    )


def load_user_attribution_settings() -> UserAttributionSettings:
    return _parse_config(_read_fixed_file(CONFIG_PATH, code="user_attribution_config_rejected"))


def _read_client_secret(settings: UserAttributionSettings) -> str:
    if settings.client_secret_path != str(CLIENT_SECRET_PATH):
        raise UserAttributionError("user_attribution_secret_path_rejected")
    return _parse_single_line_secret(
        _read_fixed_file(CLIENT_SECRET_PATH, code="user_attribution_secret_rejected"),
        prefix=None,
        code="user_attribution_secret_rejected",
    )


def _read_refresh_token(settings: UserAttributionSettings) -> str:
    if settings.refresh_token_path != str(REFRESH_TOKEN_PATH):
        raise UserAttributionError("user_attribution_refresh_path_rejected")
    return _parse_single_line_secret(
        _read_fixed_file(REFRESH_TOKEN_PATH, code="user_attribution_refresh_rejected"),
        prefix="ghr_",
        code="user_attribution_refresh_rejected",
    )


def _write_fixed_file(path: Path, value: str) -> None:
    uid, gid = _identity()
    _validate_parent_chain(uid, gid)
    if os.geteuid() != uid or os.getegid() != gid or path.parent != CONFIG_DIRECTORY:
        raise UserAttributionError("user_attribution_write_rejected")
    if not value or "\r" in value or len(value.encode("utf-8")) > MAX_FILE_BYTES - 1:
        raise UserAttributionError("user_attribution_write_rejected")
    if path != CONFIG_PATH and "\n" in value:
        raise UserAttributionError("user_attribution_write_rejected")
    if path == CONFIG_PATH and (value.startswith("\n") or value.endswith("\n") or "\n\n" in value):
        raise UserAttributionError("user_attribution_write_rejected")
    descriptor, temporary_name = tempfile.mkstemp(prefix=".user-attribution-", dir=CONFIG_DIRECTORY)
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        payload = (value + "\n").encode("utf-8")
        written = os.write(descriptor, payload)
        if written != len(payload):
            raise OSError
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary_path, path)
    except Exception as exc:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary_path.unlink()
        except OSError:
            pass
        raise UserAttributionError("user_attribution_write_rejected") from exc


def _write_refresh_token(settings: UserAttributionSettings, token: str) -> None:
    if settings.refresh_token_path != str(REFRESH_TOKEN_PATH) or not token.startswith("ghr_"):
        raise UserAttributionError("user_attribution_refresh_rejected")
    _write_fixed_file(REFRESH_TOKEN_PATH, token)


def persist_bootstrap(client_id: str, client_secret: str, refresh_token: str) -> UserAttributionSettings:
    if not CLIENT_ID_RE.fullmatch(client_id):
        raise UserAttributionError("user_attribution_client_id_rejected")
    if not client_secret or any(character.isspace() for character in client_secret):
        raise UserAttributionError("user_attribution_secret_rejected")
    if not refresh_token.startswith("ghr_") or any(character.isspace() for character in refresh_token):
        raise UserAttributionError("user_attribution_refresh_rejected")
    settings = UserAttributionSettings(
        client_id=client_id,
        expected_login=EXPECTED_LOGIN,
        client_secret_path=str(CLIENT_SECRET_PATH),
        refresh_token_path=str(REFRESH_TOKEN_PATH),
    )
    _write_fixed_file(CLIENT_SECRET_PATH, client_secret)
    _write_fixed_file(REFRESH_TOKEN_PATH, refresh_token)
    config = "\n".join((
        f"github_app_client_id={client_id}",
        f"expected_login={EXPECTED_LOGIN}",
        f"client_secret_path={CLIENT_SECRET_PATH}",
        f"refresh_token_path={REFRESH_TOKEN_PATH}",
    ))
    _write_fixed_file(CONFIG_PATH, config)
    return settings


def _decode_json(payload: bytes) -> Any:
    try:
        return json.loads(payload.decode("utf-8")) if payload else {}
    except (UnicodeDecodeError, ValueError) as exc:
        raise UserAttributionError("user_attribution_response_rejected") from exc


def _http_json(request: urllib.request.Request) -> tuple[int, Any]:
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, _decode_json(response.read())
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, _decode_json(exc.read())
        except UserAttributionError:
            raise
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UserAttributionError("user_attribution_request_failed") from exc


def _oauth_form(url: str, payload: Mapping[str, str]) -> tuple[int, Any]:
    body = urllib.parse.urlencode(payload).encode("ascii")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "megabrain-b4-2-user-attribution",
        },
    )
    return _http_json(request)


def _api_json(
    method: str,
    path: str,
    authorization: str,
    payload: Mapping[str, Any] | None = None,
) -> tuple[int, Any]:
    body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        f"{API_ROOT}{path}",
        data=body,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": authorization,
            "User-Agent": "megabrain-b4-2-user-attribution",
            "X-GitHub-Api-Version": API_VERSION,
            **({"Content-Type": "application/json"} if body is not None else {}),
        },
    )
    return _http_json(request)


def _basic_authorization(client_id: str, client_secret: str) -> str:
    encoded = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
    return f"Basic {encoded}"


def request_device_authorization(client_id: str) -> dict[str, Any]:
    if not CLIENT_ID_RE.fullmatch(client_id):
        raise UserAttributionError("user_attribution_client_id_rejected")
    status, body = _oauth_form(DEVICE_CODE_URL, {"client_id": client_id})
    if status != 200 or not isinstance(body, dict):
        raise UserAttributionError("device_flow_start_failed")
    required = ("device_code", "user_code", "verification_uri", "expires_in", "interval")
    if any(key not in body for key in required):
        raise UserAttributionError("device_flow_response_rejected")
    if (
        not all(isinstance(body[key], str) and body[key] for key in ("device_code", "user_code", "verification_uri"))
        or type(body["expires_in"]) is not int
        or type(body["interval"]) is not int
        or body["expires_in"] <= 0
        or body["interval"] <= 0
    ):
        raise UserAttributionError("device_flow_response_rejected")
    return body


def exchange_device_code(client_id: str, device_code: str) -> tuple[int, Any]:
    if not CLIENT_ID_RE.fullmatch(client_id) or not device_code:
        raise UserAttributionError("device_flow_request_rejected")
    return _oauth_form(
        OAUTH_TOKEN_URL,
        {
            "client_id": client_id,
            "device_code": device_code,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        },
    )


def _extract_user_token_pair(body: Any) -> tuple[str, str]:
    if not isinstance(body, dict):
        raise UserAttributionError("user_token_response_rejected")
    access_token = body.get("access_token")
    refresh_token = body.get("refresh_token")
    if (
        not isinstance(access_token, str)
        or not access_token.startswith("ghu_")
        or not isinstance(refresh_token, str)
        or not refresh_token.startswith("ghr_")
        or body.get("token_type") != "bearer"
        or body.get("expires_in") != 28800
        or type(body.get("refresh_token_expires_in")) is not int
        or body["refresh_token_expires_in"] <= 0
    ):
        raise UserAttributionError("user_token_response_rejected")
    return access_token, refresh_token


def _repository_scope(installation_id: str, token: str) -> dict[str, Any]:
    if not installation_id.isdecimal():
        raise UserAttributionError("user_attribution_installation_rejected")
    status, body = _api_json(
        "GET",
        f"/user/installations/{installation_id}/repositories?per_page=100",
        f"Bearer {token}",
    )
    if status != 200 or not isinstance(body, dict):
        raise UserAttributionError("user_repository_scope_rejected")
    return body


def validate_broad_user_access_token(access_token: str, installation_id: str) -> None:
    if not access_token.startswith("ghu_"):
        raise UserAttributionError("user_token_response_rejected")
    status, actor = _api_json("GET", "/user", f"Bearer {access_token}")
    if (
        status != 200
        or not isinstance(actor, dict)
        or actor.get("login") != EXPECTED_LOGIN
        or actor.get("type") != "User"
    ):
        raise UserAttributionError("user_attribution_actor_rejected")
    scope = _repository_scope(installation_id, access_token)
    repositories = scope.get("repositories")
    if not isinstance(repositories, list) or not any(
        isinstance(repository, dict) and repository.get("full_name") == REPOSITORY
        for repository in repositories
    ):
        raise UserAttributionError("user_repository_scope_rejected")


def _valid_scoped_permissions(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("pull_requests") == "write"
        and set(value).issubset(ALLOWED_SCOPED_PERMISSION_KEYS)
        and value.get("metadata", "read") == "read"
        and "administration" not in value
    )


def _valid_exact_repository_scope(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("total_count") == 1
        and isinstance(value.get("repositories"), list)
        and len(value["repositories"]) == 1
        and isinstance(value["repositories"][0], dict)
        and value["repositories"][0].get("full_name") == REPOSITORY
    )


def create_scoped_pr_credential_from_access(
    settings: UserAttributionSettings,
    access_token: str,
    client_secret: str,
    installation_id: str,
) -> ScopedPrCredential:
    if settings.expected_login != EXPECTED_LOGIN or not access_token.startswith("ghu_"):
        raise UserAttributionError("user_attribution_actor_rejected")
    authorization = _basic_authorization(settings.client_id, client_secret)
    payload = {
        "access_token": access_token,
        "target": EXPECTED_LOGIN,
        "repositories": [REPOSITORY_NAME],
        "permissions": {"pull_requests": "write"},
    }
    status, scoped = _api_json(
        "POST",
        f"/applications/{settings.client_id}/token/scoped",
        authorization,
        payload,
    )
    candidate = scoped.get("token") if status == 200 and isinstance(scoped, dict) else None
    if not isinstance(candidate, str) or not candidate.startswith("ghu_"):
        raise UserAttributionError("scoped_token_mint_failed")
    success = False
    try:
        actor = scoped.get("user")
        installation = scoped.get("installation")
        permissions = installation.get("permissions") if isinstance(installation, dict) else None
        if not isinstance(actor, dict) or actor.get("login") != EXPECTED_LOGIN:
            raise UserAttributionError("user_attribution_actor_rejected")
        if not _valid_scoped_permissions(permissions):
            raise UserAttributionError("scoped_token_permissions_rejected")
        actor_status, actor_check = _api_json("GET", "/user", f"Bearer {candidate}")
        if actor_status != 200 or not isinstance(actor_check, dict) or actor_check.get("login") != EXPECTED_LOGIN:
            raise UserAttributionError("user_attribution_actor_rejected")
        scope = _repository_scope(installation_id, candidate)
        if not _valid_exact_repository_scope(scope):
            raise UserAttributionError("scoped_token_scope_rejected")
        success = True
        return ScopedPrCredential(
            token=candidate,
            actor_login=EXPECTED_LOGIN,
            permissions=dict(permissions),
            scope=dict(scope),
            settings=settings,
        )
    finally:
        if not success:
            revoke_token_with_secret(settings.client_id, client_secret, candidate)


def revoke_token_with_secret(client_id: str, client_secret: str, token: str) -> bool:
    if not token:
        return True
    status, _ = _api_json(
        "DELETE",
        f"/applications/{client_id}/token",
        _basic_authorization(client_id, client_secret),
        {"access_token": token},
    )
    return status == 204


def mint_scoped_pr_credential(installation_id: str) -> ScopedPrCredential:
    settings = load_user_attribution_settings()
    refresh_token = _read_refresh_token(settings)
    status, refreshed = _oauth_form(
        OAUTH_TOKEN_URL,
        {
            "client_id": settings.client_id,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
    )
    if status != 200:
        raise UserAttributionError("user_token_refresh_failed")
    access_token, new_refresh_token = _extract_user_token_pair(refreshed)
    _write_refresh_token(settings, new_refresh_token)
    validate_broad_user_access_token(access_token, installation_id)
    if load_user_attribution_settings() != settings:
        raise UserAttributionError("user_attribution_config_changed")
    client_secret = _read_client_secret(settings)
    credential = create_scoped_pr_credential_from_access(
        settings, access_token, client_secret, installation_id,
    )
    access_token = ""
    return credential


def revoke_scoped_pr_credential(credential: ScopedPrCredential) -> bool:
    try:
        if load_user_attribution_settings() != credential.settings:
            return False
        client_secret = _read_client_secret(credential.settings)
        return revoke_token_with_secret(
            credential.settings.client_id, client_secret, credential.token,
        )
    except UserAttributionError:
        return False
