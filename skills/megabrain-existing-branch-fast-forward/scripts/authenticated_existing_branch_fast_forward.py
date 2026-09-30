#!/usr/bin/env python3
"""One-transition adapter for a fixed existing-branch fast-forward only."""
from __future__ import annotations

import base64
import datetime as dt
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping

OWNER = "mide-lim"
REPOSITORY = "mide-lim/megabrain"
ORIGIN = "https://github.com/mide-lim/megabrain.git"
EXPECTED_DEV_SHA = "68282465b0393c7e140c363ff4b68d85e917afd8"
TARGET_BRANCH = "agent/f6-i1-b-a1-installer-rollback-hardening"
TARGET_REF = "refs/heads/agent/f6-i1-b-a1-installer-rollback-hardening"
EXPECTED_OLD_SHA = "9fa26a31dd6e384fee6bfdfe3b31119cf2f18af8"
AUTHORIZED_NEW_SHA = "e4c7de42b416766e65bccc4fdf1ff49ba170474f"
AUTHORIZED_NEW_TREE = "21a88423d9ffa344dd97a75e23d423b28e14a5e5"
AUTHORIZED_NEW_PARENT = "9fa26a31dd6e384fee6bfdfe3b31119cf2f18af8"

GIT_BINARY = "/usr/bin/git"
OPENSSL_BINARY = "/usr/bin/openssl"
API_ROOT = "https://api.github.com"
AUTHORIZATION_ID = "f6-i1-b-b4-existing-branch-fast-forward-v1"
AUTHORIZATION_ROOT = Path("/etc/megabrain/hermes-authorizations/f6-i1-b-b4-existing-branch-fast-forward")
AUTHORIZATION_PATH = AUTHORIZATION_ROOT / f"{AUTHORIZATION_ID}.json"
RUNTIME_CONFIG_PATH = Path(
    "/home/megabrain-hermes/.hermes/skills/megabrain/"
    "megabrain-github-app-auth/scripts/github_app_runtime_config.py"
)
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
MAX_AUTHORIZATION_TTL = dt.timedelta(hours=24)
AUTHORIZATION_FIELDS = frozenset({
    "version", "authorization_id", "repository", "target_ref", "expected_old_sha",
    "authorized_new_sha", "authorized_new_tree", "authorized_new_parent", "expected_dev_sha",
    "issued_at", "expires_at",
})


class StopSourceDrift(RuntimeError):
    pass


class StopRemoteDrift(RuntimeError):
    pass


class StopPostWriteVerification(RuntimeError):
    pass


class SafeFailure(RuntimeError):
    pass


class PushAttemptGate:
    """One irreversible write claim per process invocation."""

    def __init__(self) -> None:
        self.attempts = 0

    def claim(self) -> None:
        if self.attempts != 0:
            raise StopPostWriteVerification("push_attempt_exhausted")
        self.attempts = 1


def sanitized_result(status: str, failure_code: str | None = None) -> dict[str, Any]:
    return {
        "operation": "existing-branch-fast-forward",
        "status": status,
        "failure_code": failure_code,
        "force_with_lease": True,
        "unconditional_force": False,
        "authorized_result_fast_forward": True,
        "push_attempts": 0,
        "credential_minted": False,
        "revocation": "not_attempted",
    }


def parse_strict_json(text: str) -> dict[str, Any]:
    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_key")
            result[key] = value
        return result
    try:
        value = json.loads(text, object_pairs_hook=no_duplicates)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise StopSourceDrift("authorization_schema_rejected") from exc
    if not isinstance(value, dict):
        raise StopSourceDrift("authorization_schema_rejected")
    return value


def _parse_timestamp(value: Any) -> dt.datetime:
    if not isinstance(value, str) or not UTC_RE.fullmatch(value):
        raise StopSourceDrift("authorization_schema_rejected")
    try:
        return dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except ValueError as exc:
        raise StopSourceDrift("authorization_schema_rejected") from exc


def validate_authorization_value(value: Mapping[str, Any], now: dt.datetime | None = None) -> None:
    if set(value) != AUTHORIZATION_FIELDS or type(value.get("version")) is not int or value["version"] != 1:
        raise StopSourceDrift("authorization_schema_rejected")
    expected = {
        "authorization_id": AUTHORIZATION_ID,
        "repository": REPOSITORY,
        "target_ref": TARGET_REF,
        "expected_old_sha": EXPECTED_OLD_SHA,
        "authorized_new_sha": AUTHORIZED_NEW_SHA,
        "authorized_new_tree": AUTHORIZED_NEW_TREE,
        "authorized_new_parent": AUTHORIZED_NEW_PARENT,
        "expected_dev_sha": EXPECTED_DEV_SHA,
    }
    if any(value.get(key) != expected_value for key, expected_value in expected.items()):
        raise StopSourceDrift("authorization_tuple_rejected")
    issued_at = _parse_timestamp(value["issued_at"])
    expires_at = _parse_timestamp(value["expires_at"])
    current = dt.datetime.now(dt.timezone.utc) if now is None else now
    if issued_at > current or expires_at <= current:
        raise StopSourceDrift("authorization_expired")
    if expires_at <= issued_at or expires_at - issued_at > MAX_AUTHORIZATION_TTL:
        raise StopSourceDrift("authorization_schema_rejected")


def validate_trusted_path(path: Path, *, file_expected: bool) -> None:
    parts = path.parts
    if not path.is_absolute() or not parts or parts[0] != "/":
        raise StopSourceDrift("authorization_trust_rejected")
    current = Path("/")
    chain = [current]
    for component in parts[1:]:
        current = current / component
        chain.append(current)
    for position, candidate in enumerate(chain):
        is_final = position == len(chain) - 1
        try:
            info = os.lstat(candidate)
        except OSError as exc:
            raise StopSourceDrift("authorization_missing") from exc
        mode = info.st_mode
        expected_type = stat.S_ISREG(mode) if is_final and file_expected else stat.S_ISDIR(mode)
        if (stat.S_ISLNK(mode) or not expected_type or info.st_uid != 0 or stat.S_IMODE(mode) & 0o022):
            raise StopSourceDrift("authorization_trust_rejected")
        if is_final and file_expected and stat.S_IMODE(mode) != 0o600:
            raise StopSourceDrift("authorization_trust_rejected")


def load_authorization(now: dt.datetime | None = None) -> dict[str, Any]:
    validate_trusted_path(AUTHORIZATION_PATH, file_expected=True)
    try:
        text = AUTHORIZATION_PATH.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise StopSourceDrift("authorization_missing") from exc
    value = parse_strict_json(text)
    validate_authorization_value(value, now)
    return value


def validate_privileged_executable(path: str) -> None:
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise StopSourceDrift("privileged_executable_rejected") from exc
    if (stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_uid != 0
            or stat.S_IMODE(info.st_mode) & 0o022 or not info.st_mode & stat.S_IXUSR):
        raise StopSourceDrift("privileged_executable_rejected")


def _local_env(home: str) -> dict[str, str]:
    return {
        "HOME": home,
        "PATH": "/usr/bin:/bin",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_NO_REPLACE_OBJECTS": "1",
    }


def _run_git(root: Path, arguments: list[str], *, home: str, token: str | None = None,
             askpass: str | None = None, permitted: bool = True) -> tuple[int, str]:
    if not permitted:
        raise StopSourceDrift("git_command_rejected")
    validate_privileged_executable(GIT_BINARY)
    command = [
        GIT_BINARY, "-c", "credential.helper=", "-c", "credential.useHttpPath=true",
        "-c", "credential.interactive=false", "-c", "core.hooksPath=/dev/null", *arguments,
    ]
    environment = _local_env(home)
    if token is not None and askpass is not None:
        environment["GIT_ASKPASS"] = askpass
        environment["MEGABRAIN_GITHUB_APP_TOKEN"] = token
    try:
        completed = subprocess.run(
            command, cwd=root, env=environment, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            check=False, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise StopSourceDrift("git_command_rejected") from exc
    return completed.returncode, completed.stdout.strip()


def _must_git(root: Path, arguments: list[str], *, home: str) -> str:
    code, output = _run_git(root, arguments, home=home)
    if code != 0:
        raise StopSourceDrift("git_command_rejected")
    return output


def validate_clean_state(worktree_status: str, index_status: str) -> None:
    if worktree_status:
        raise StopSourceDrift("worktree_dirty")
    if index_status:
        raise StopSourceDrift("index_dirty")


def validate_commit_metadata(commit: str, tree: str, parents: list[str]) -> None:
    if commit != AUTHORIZED_NEW_SHA or tree != AUTHORIZED_NEW_TREE:
        raise StopSourceDrift("commit_metadata_rejected")
    if len(parents) != 1 or parents[0] != AUTHORIZED_NEW_PARENT:
        raise StopSourceDrift("commit_parent_rejected")


def _parse_remote_ref(output: str, ref: str) -> str | None:
    lines = [line for line in output.splitlines() if line]
    if not lines:
        return None
    if len(lines) != 1:
        raise StopRemoteDrift("STOP_REMOTE_DRIFT")
    fields = lines[0].split("\t")
    if len(fields) != 2 or fields[1] != ref or not SHA_RE.fullmatch(fields[0]):
        raise StopRemoteDrift("STOP_REMOTE_DRIFT")
    return fields[0]


def classify_remote(remote_sha: str | None) -> str:
    if remote_sha is None:
        raise StopRemoteDrift("STOP_REMOTE_BRANCH_MISSING")
    if remote_sha == AUTHORIZED_NEW_SHA:
        return "ALREADY_AT_AUTHORIZED_HEAD"
    if remote_sha == EXPECTED_OLD_SHA:
        return "PREPARE"
    raise StopRemoteDrift("STOP_REMOTE_DRIFT")


def _local_remote_read(root: Path, ref: str, home: str) -> str | None:
    code, output = _run_git(root, ["ls-remote", "origin", ref], home=home)
    if code != 0:
        raise StopSourceDrift("git_command_rejected")
    return _parse_remote_ref(output, ref)


def validate_workspace(root: Path, home: str) -> None:
    if _must_git(root, ["remote", "get-url", "origin"], home=home) != ORIGIN:
        raise StopSourceDrift("origin_rejected")
    if _must_git(root, ["symbolic-ref", "--short", "HEAD"], home=home) != TARGET_BRANCH:
        raise StopSourceDrift("target_branch_rejected")
    if _must_git(root, ["rev-parse", "HEAD"], home=home) != AUTHORIZED_NEW_SHA:
        raise StopSourceDrift("local_head_rejected")
    if _must_git(root, ["cat-file", "-t", AUTHORIZED_NEW_SHA], home=home) != "commit":
        raise StopSourceDrift("local_commit_rejected")
    metadata = _must_git(root, ["show", "-s", "--format=%T%x00%P", AUTHORIZED_NEW_SHA], home=home).split("\x00")
    if len(metadata) != 2:
        raise StopSourceDrift("commit_metadata_rejected")
    validate_commit_metadata(AUTHORIZED_NEW_SHA, metadata[0], metadata[1].split() if metadata[1] else [])
    worktree_code, _ = _run_git(root, ["diff", "--quiet"], home=home)
    index_code, _ = _run_git(root, ["diff", "--cached", "--quiet"], home=home)
    if worktree_code not in {0, 1} or index_code not in {0, 1}:
        raise StopSourceDrift("git_command_rejected")
    validate_clean_state("dirty" if worktree_code else "", "dirty" if index_code else "")
    if _local_remote_read(root, "refs/heads/dev", home) != EXPECTED_DEV_SHA:
        raise StopSourceDrift("dev_drift")


def create_staging_repository(source_root: Path, staging_root: Path, home: str) -> None:
    staging_root.mkdir(mode=0o700)
    commands = (
        ["init", "--quiet"],
        ["fetch", "--no-tags", "--no-recurse-submodules", str(source_root), AUTHORIZED_NEW_SHA],
        ["cat-file", "-e", f"{AUTHORIZED_NEW_SHA}^{{commit}}"],
        ["update-ref", TARGET_REF, AUTHORIZED_NEW_SHA],
        ["symbolic-ref", "HEAD", TARGET_REF],
        ["reset", "--hard", "--quiet", AUTHORIZED_NEW_SHA],
        ["remote", "add", "origin", ORIGIN],
    )
    for command in commands:
        if _run_git(staging_root, command, home=home)[0] != 0:
            raise StopSourceDrift("staging_rejected")
    if _must_git(staging_root, ["rev-parse", "HEAD"], home=home) != AUTHORIZED_NEW_SHA:
        raise StopSourceDrift("staged_head_rejected")
    tree_and_parents = _must_git(
        staging_root, ["show", "-s", "--format=%T%x00%P", AUTHORIZED_NEW_SHA], home=home,
    ).split("\x00")
    if len(tree_and_parents) != 2:
        raise StopSourceDrift("staging_rejected")
    validate_commit_metadata(
        AUTHORIZED_NEW_SHA, tree_and_parents[0], tree_and_parents[1].split() if tree_and_parents[1] else [],
    )
    if _must_git(staging_root, ["remote", "get-url", "origin"], home=home) != ORIGIN:
        raise StopSourceDrift("staging_rejected")


def build_push_command() -> list[str]:
    return [
        "git", "push", "--porcelain",
        f"--force-with-lease={TARGET_REF}:{EXPECTED_OLD_SHA}",
        "origin", f"{AUTHORIZED_NEW_SHA}:{TARGET_REF}",
    ]


def is_allowed_controlled_command(command: list[str]) -> bool:
    return tuple(command) in {
        ("git", "ls-remote", "origin", TARGET_REF),
        ("git", "ls-remote", "origin", "refs/heads/dev"),
        tuple(build_push_command()),
    }


def _controlled_git(root: Path, home: str, token: str, askpass: str, command: list[str]) -> tuple[int, str]:
    if not is_allowed_controlled_command(command):
        raise StopSourceDrift("git_command_rejected")
    return _run_git(root, command[1:], home=home, token=token, askpass=askpass)


def create_askpass(directory: str) -> str:
    path = Path(directory) / "askpass"
    try:
        path.write_text(
            "#!/bin/sh\ncase \"$1\" in\n  *Username*|*username*) printf '%s\\n' x-access-token ;;\n  *) printf '%s\\n' \"$MEGABRAIN_GITHUB_APP_TOKEN\" ;;\nesac\n",
            encoding="utf-8",
        )
        os.chmod(path, 0o700)
    except OSError as exc:
        raise SafeFailure("askpass_failed") from exc
    return str(path)


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _load_runtime_settings() -> Any:
    try:
        info = os.lstat(RUNTIME_CONFIG_PATH)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700:
            raise OSError
        specification = importlib.util.spec_from_file_location("fixed_b41_runtime_config", RUNTIME_CONFIG_PATH)
        if specification is None or specification.loader is None:
            raise RuntimeError
        module = importlib.util.module_from_spec(specification)
        sys.modules[specification.name] = module
        specification.loader.exec_module(module)
        settings = module.load_runtime_config()
        if not all(isinstance(value, str) and value for value in (settings.app_id, settings.installation_id, settings.key_path)):
            raise RuntimeError
        return settings
    except Exception as exc:
        raise SafeFailure("runtime_config_rejected") from exc


def _make_jwt(app_id: str, key_path: str) -> str:
    validate_privileged_executable(OPENSSL_BINARY)
    issued_at = int(time.time())
    header = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")).encode("ascii"))
    payload = _b64url(json.dumps({"iat": issued_at - 30, "exp": issued_at + 540, "iss": app_id}, separators=(",", ":")).encode("ascii"))
    try:
        completed = subprocess.run(
            [OPENSSL_BINARY, "dgst", "-sha256", "-sign", key_path], input=f"{header}.{payload}".encode("ascii"),
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False, timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SafeFailure("jwt_sign_failed") from exc
    if completed.returncode != 0 or not completed.stdout:
        raise SafeFailure("jwt_sign_failed")
    return f"{header}.{payload}.{_b64url(completed.stdout)}"


def _request_json(method: str, path: str, authorization: str, payload: Mapping[str, Any] | None = None) -> tuple[int, Any]:
    body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        f"{API_ROOT}{path}", data=body, method=method,
        headers={"Accept": "application/vnd.github+json", "Authorization": authorization,
                 "User-Agent": "megabrain-existing-branch-fast-forward",
                 **({"Content-Type": "application/json"} if body is not None else {})},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            content = response.read()
            decoded = json.loads(content.decode("utf-8")) if content else {}
            if not isinstance(decoded, dict):
                raise ValueError
            return response.status, decoded
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as exc:
        raise SafeFailure("api_request_failed") from exc


def _valid_token_permissions(value: Any) -> bool:
    return isinstance(value, dict) and value.get("contents") == "write" and set(value).issubset({"contents", "metadata"}) and value.get("metadata", "read") == "read"


def _valid_scope(value: Any) -> bool:
    return (isinstance(value, dict) and value.get("total_count") == 1 and isinstance(value.get("repositories"), list)
            and len(value["repositories"]) == 1 and isinstance(value["repositories"][0], dict)
            and value["repositories"][0].get("full_name") == REPOSITORY)


def _mint_token() -> str:
    settings = _load_runtime_settings()
    jwt = _make_jwt(settings.app_id, settings.key_path)
    try:
        status, minted = _request_json(
            "POST", f"/app/installations/{settings.installation_id}/access_tokens", f"Bearer {jwt}",
            {"repositories": ["megabrain"], "permissions": {"contents": "write"}},
        )
    finally:
        jwt = ""
    candidate = minted.get("token") if status == 201 and isinstance(minted, dict) else None
    if not isinstance(candidate, str) or not candidate or not _valid_token_permissions(minted.get("permissions")):
        raise SafeFailure("token_mint_rejected")
    scope_status, scope = _request_json("GET", "/installation/repositories", f"token {candidate}")
    if scope_status != 200 or not _valid_scope(scope):
        raise SafeFailure("token_scope_rejected")
    return candidate


def _revoke_token(token: str) -> bool:
    try:
        status, _ = _request_json("DELETE", "/installation/token", f"token {token}")
    except SafeFailure:
        return False
    return status == 204


def verify_post_write(target_sha: str | None, dev_sha: str | None) -> None:
    if target_sha != AUTHORIZED_NEW_SHA:
        raise StopPostWriteVerification("STOP_POST_WRITE_VERIFICATION")
    if dev_sha != EXPECTED_DEV_SHA:
        raise StopPostWriteVerification("dev_drift_after_write")


def decide_before_mint(remote_sha: str | None, mint: Any) -> str:
    decision = classify_remote(remote_sha)
    if decision == "ALREADY_AT_AUTHORIZED_HEAD":
        return decision
    mint()
    return decision


def preflight_and_maybe_mint(worktree_status: str, index_status: str, remote_sha: str | None, mint: Any) -> str:
    validate_clean_state(worktree_status, index_status)
    return decide_before_mint(remote_sha, mint)


def run() -> dict[str, Any]:
    result = sanitized_result("failed")
    token: str | None = None
    temporary: tempfile.TemporaryDirectory[str] | None = None
    try:
        root = Path.cwd().resolve()
        temporary = tempfile.TemporaryDirectory(prefix="megabrain-existing-branch-ff-")
        load_authorization()
        validate_workspace(root, temporary.name)
        remote_before = _local_remote_read(root, TARGET_REF, temporary.name)
        if classify_remote(remote_before) == "ALREADY_AT_AUTHORIZED_HEAD":
            result.update({"status": "ok", "failure_code": "ALREADY_AT_AUTHORIZED_HEAD"})
            return result
        staging = Path(temporary.name) / "staging"
        create_staging_repository(root, staging, temporary.name)
        load_authorization()
        validate_workspace(root, temporary.name)
        token = _mint_token()
        result["credential_minted"] = True
        askpass = create_askpass(temporary.name)
        gate = PushAttemptGate()
        gate.claim()
        result["push_attempts"] = gate.attempts
        code, _ = _controlled_git(staging, temporary.name, token, askpass, build_push_command())
        if code != 0:
            raise StopPostWriteVerification("push_rejected")
        target_code, target_output = _controlled_git(staging, temporary.name, token, askpass, ["git", "ls-remote", "origin", TARGET_REF])
        dev_code, dev_output = _controlled_git(staging, temporary.name, token, askpass, ["git", "ls-remote", "origin", "refs/heads/dev"])
        if target_code != 0 or dev_code != 0:
            raise StopPostWriteVerification("STOP_POST_WRITE_VERIFICATION")
        verify_post_write(_parse_remote_ref(target_output, TARGET_REF), _parse_remote_ref(dev_output, "refs/heads/dev"))
        result["status"] = "ok"
    except (StopSourceDrift, StopRemoteDrift, StopPostWriteVerification, SafeFailure) as exc:
        result["failure_code"] = str(exc)
    except Exception:
        result["failure_code"] = "unexpected_failure"
    finally:
        if token is not None:
            result["revocation"] = "ok" if _revoke_token(token) else "failed"
            if result["revocation"] != "ok":
                result["status"] = "failed"
                result["failure_code"] = "revocation_failed"
        if temporary is not None:
            temporary.cleanup()
    return result


def main() -> int:
    if len(sys.argv) != 1:
        print(json.dumps(sanitized_result("failed", "arguments_rejected"), sort_keys=True, separators=(",", ":")))
        return 1
    result = run()
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
