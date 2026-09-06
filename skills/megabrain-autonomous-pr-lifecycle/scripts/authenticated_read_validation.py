#!/usr/bin/env python3
"""Closed B4.2 P1 adapter for one authenticated, read-only dev-ref check."""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import stat
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping

REPOSITORY = "mide-lim/megabrain"
ORIGIN = "https://github.com/mide-lim/megabrain.git"
REF = "refs/heads/dev"
REF_API_PATH = "/repos/mide-lim/megabrain/git/ref/heads/dev"
API_ROOT = "https://api.github.com"
OPERATION = "validate-read-dev-ref"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")

# The expected installation baseline is validated before the requested token.
# This adapter requests only the smaller read profile below.
EXPECTED_INSTALLATION_PERMISSIONS = {
    "actions": "read",
    "contents": "write",
    "metadata": "read",
    "pull_requests": "write",
    "statuses": "read",
    "workflows": "write",
}
READ_TOKEN_REQUEST_PERMISSIONS = {"contents": "read"}


class SafeFailure(Exception):
    """An expected, non-sensitive failure represented by a symbolic code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _required_environment(environ: Mapping[str, str]) -> tuple[str, str, str]:
    names = (
        "MEGABRAIN_GITHUB_APP_ID",
        "MEGABRAIN_GITHUB_APP_INSTALLATION_ID",
        "MEGABRAIN_GITHUB_APP_KEY_PATH",
    )
    values = tuple(environ.get(name, "") for name in names)
    if not values[0].isdecimal() or not values[1].isdecimal() or not values[2]:
        raise SafeFailure("environment_missing")
    return values  # type: ignore[return-value]


def configured_origin() -> str:
    completed = subprocess.run(
        ["git", "config", "--get", "remote.origin.url"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        timeout=10,
    )
    if completed.returncode != 0:
        raise SafeFailure("origin_rejected")
    return completed.stdout.strip()


def validate_key_path(key_path: str) -> None:
    try:
        key_stat = os.lstat(key_path)
    except OSError as exc:
        raise SafeFailure("key_invalid") from exc
    if not stat.S_ISREG(key_stat.st_mode) or stat.S_IMODE(key_stat.st_mode) & 0o077:
        raise SafeFailure("key_invalid")


def make_jwt(app_id: str, key_path: str, now: int | None = None) -> str:
    issued_at = int(time.time() if now is None else now)
    header = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64url(
        json.dumps({"iat": issued_at - 30, "exp": issued_at + 540, "iss": app_id}, separators=(",", ":")).encode()
    )
    signing_input = f"{header}.{payload}".encode("ascii")
    try:
        signed = subprocess.run(
            ["openssl", "dgst", "-sha256", "-sign", key_path],
            input=signing_input,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SafeFailure("jwt_sign_failed") from exc
    if signed.returncode != 0 or not signed.stdout:
        raise SafeFailure("jwt_sign_failed")
    return f"{header}.{payload}.{_b64url(signed.stdout)}"


def request_json(
    method: str,
    path: str,
    authorization: str,
    payload: Mapping[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        f"{API_ROOT}{path}",
        data=body,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": authorization,
            "User-Agent": "megabrain-b4-2-p1-read-validation",
            **({"Content-Type": "application/json"} if body is not None else {}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body_value = response.read()
            decoded = json.loads(body_value.decode("utf-8")) if body_value else {}
            return response.status, decoded if isinstance(decoded, dict) else {}
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as exc:
        raise SafeFailure("api_request_failed") from exc


def _valid_installation_permissions(value: Any) -> bool:
    return isinstance(value, dict) and "administration" not in value and value == EXPECTED_INSTALLATION_PERMISSIONS


def _valid_read_token_permissions(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and "administration" not in value
        and value.get("contents") == "read"
        and set(value).issubset({"contents", "metadata"})
        and all(permission == "read" for permission in value.values())
    )


def _valid_scope(value: Any) -> bool:
    if not isinstance(value, dict) or value.get("total_count") != 1:
        return False
    repositories = value.get("repositories")
    return (
        isinstance(repositories, list)
        and len(repositories) == 1
        and isinstance(repositories[0], dict)
        and repositories[0].get("full_name") == REPOSITORY
    )


def _read_sha(value: Any) -> str | None:
    if not isinstance(value, dict) or value.get("ref") != REF:
        return None
    object_value = value.get("object")
    if not isinstance(object_value, dict) or object_value.get("type") != "commit":
        return None
    sha = object_value.get("sha")
    return sha if isinstance(sha, str) and SHA_RE.fullmatch(sha) else None


def _base_result() -> dict[str, Any]:
    return {
        "operation": OPERATION,
        "status": "failed",
        "failure_code": None,
        "origin_valid": False,
        "installation_permissions_valid": None,
        "token_permissions_valid": None,
        "scope_valid": None,
        "ref_valid": None,
        "sha": None,
        "revocation": "not_attempted",
        "temporary_cleanup": None,
    }


def run_operation(
    operation: str,
    operational_gate_approved: bool,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Run only the P1 fixed ref read after an explicit human authorization."""
    result = _base_result()
    if operation != OPERATION:
        result["failure_code"] = "operation_rejected"
        return result
    if not operational_gate_approved:
        result["failure_code"] = "operational_gate_required"
        return result

    environment = os.environ if environ is None else environ
    token: str | None = None
    temporary_directory: tempfile.TemporaryDirectory[str] | None = None
    try:
        app_id, installation_id, key_path = _required_environment(environment)
        if configured_origin() != ORIGIN:
            raise SafeFailure("origin_rejected")
        result["origin_valid"] = True
        validate_key_path(key_path)
        jwt = make_jwt(app_id, key_path)
        baseline_status, baseline = request_json("GET", f"/app/installations/{installation_id}", f"Bearer {jwt}")
        if baseline_status != 200 or not _valid_installation_permissions(baseline.get("permissions")):
            result["installation_permissions_valid"] = False
            raise SafeFailure("installation_permissions_rejected")
        result["installation_permissions_valid"] = True
        mint_status, minted = request_json(
            "POST",
            f"/app/installations/{installation_id}/access_tokens",
            f"Bearer {jwt}",
            {"repositories": ["megabrain"], "permissions": READ_TOKEN_REQUEST_PERMISSIONS},
        )
        jwt = ""
        candidate = minted.get("token") if mint_status == 201 else None
        if not isinstance(candidate, str) or not candidate:
            raise SafeFailure("token_mint_failed")
        token = candidate
        if not _valid_read_token_permissions(minted.get("permissions")):
            result["token_permissions_valid"] = False
            raise SafeFailure("token_permissions_rejected")
        result["token_permissions_valid"] = True
        scope_status, scope = request_json("GET", "/installation/repositories", f"token {token}")
        if scope_status != 200 or not _valid_scope(scope):
            result["scope_valid"] = False
            raise SafeFailure("scope_rejected")
        result["scope_valid"] = True
        temporary_directory = tempfile.TemporaryDirectory(prefix="megabrain-b4-2-p1-")
        result["temporary_cleanup"] = False
        ref_status, ref = request_json("GET", REF_API_PATH, f"token {token}")
        sha = _read_sha(ref) if ref_status == 200 else None
        if sha is None:
            result["ref_valid"] = False
            raise SafeFailure("ref_rejected")
        result["ref_valid"] = True
        result["sha"] = sha
    except SafeFailure as exc:
        result["failure_code"] = exc.code
    except Exception:
        result["failure_code"] = "unexpected_failure"
    finally:
        if token is not None:
            try:
                revoke_status, _ = request_json("DELETE", "/installation/token", f"token {token}")
                result["revocation"] = "ok" if revoke_status == 204 else "failed"
                if revoke_status != 204:
                    result["failure_code"] = "revocation_failed"
            except SafeFailure:
                result["revocation"] = "failed"
                result["failure_code"] = "revocation_failed"
        if temporary_directory is not None:
            try:
                temporary_directory.cleanup()
                result["temporary_cleanup"] = True
            except Exception:
                result["temporary_cleanup"] = False
                result["failure_code"] = "cleanup_failed"
        token = None

    if result["failure_code"] is None:
        result["status"] = "ok"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the fixed B4.2 P1 read-only dev-ref validator.")
    parser.add_argument("--operation", required=True, choices=[OPERATION])
    parser.add_argument("--operational-gate-approved", action="store_true")
    arguments = parser.parse_args()
    result = run_operation(arguments.operation, arguments.operational_gate_approved)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
