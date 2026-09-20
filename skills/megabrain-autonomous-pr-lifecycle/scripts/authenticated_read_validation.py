#!/usr/bin/env python3
"""Closed B4.2 P1 adapter for one authenticated, read-only dev-ref check."""
from __future__ import annotations

import argparse
import base64
import importlib.util
import json
import re
import sys
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
EXPECTED_INSTALLATION_PERMISSIONS = {"actions": "read", "contents": "write", "metadata": "read", "pull_requests": "write", "statuses": "read", "workflows": "write"}
READ_TOKEN_REQUEST_PERMISSIONS = {"contents": "read"}

def _load_sidecar(name: str, filename: str) -> Any:
    path = Path(__file__).with_name(filename)
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError("sidecar_unavailable")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module

LIFECYCLE = _load_sidecar("megabrain_b42_lifecycle_p1", "autonomous_pr_lifecycle.py")
RUNTIME_CONFIG = _load_sidecar("megabrain_b42_runtime_config_bridge_p1", "github_app_runtime_config_bridge.py")

class SafeFailure(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code

def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

def configured_origin() -> str:
    import subprocess
    completed = subprocess.run(["git", "config", "--get", "remote.origin.url"], check=False, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=10)
    if completed.returncode != 0:
        raise SafeFailure("origin_rejected")
    return completed.stdout.strip()

def make_jwt(app_id: str, key_path: str, now: int | None = None) -> str:
    import subprocess
    issued_at = int(time.time() if now is None else now)
    header = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64url(json.dumps({"iat": issued_at - 30, "exp": issued_at + 540, "iss": app_id}, separators=(",", ":")).encode())
    try:
        signed = subprocess.run(["openssl", "dgst", "-sha256", "-sign", key_path], input=f"{header}.{payload}".encode("ascii"), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SafeFailure("jwt_sign_failed") from exc
    if signed.returncode != 0 or not signed.stdout:
        raise SafeFailure("jwt_sign_failed")
    return f"{header}.{payload}.{_b64url(signed.stdout)}"

def request_json(method: str, path: str, authorization: str, payload: Mapping[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(f"{API_ROOT}{path}", data=body, method=method, headers={"Accept": "application/vnd.github+json", "Authorization": authorization, "User-Agent": "megabrain-b4-2-p1-read-validation", **({"Content-Type": "application/json"} if body is not None else {})})
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
    return isinstance(value, dict) and "administration" not in value and value.get("contents") == "read" and set(value).issubset({"contents", "metadata"}) and all(permission == "read" for permission in value.values())

def _valid_scope(value: Any) -> bool:
    return isinstance(value, dict) and value.get("total_count") == 1 and isinstance(value.get("repositories"), list) and len(value["repositories"]) == 1 and isinstance(value["repositories"][0], dict) and value["repositories"][0].get("full_name") == REPOSITORY

def _read_sha(value: Any) -> str | None:
    if not isinstance(value, dict) or value.get("ref") != REF:
        return None
    object_value = value.get("object")
    if not isinstance(object_value, dict) or object_value.get("type") != "commit":
        return None
    sha = object_value.get("sha")
    return sha if isinstance(sha, str) and SHA_RE.fullmatch(sha) else None

def _base_result() -> dict[str, Any]:
    return {"operation": OPERATION, "status": "failed", "failure_code": None, "origin_valid": False, "installation_permissions_valid": None, "token_permissions_valid": None, "scope_valid": None, "ref_valid": None, "sha": None, "revocation": "not_attempted", "temporary_cleanup": None}

def run_operation(operation: str, lifecycle_id: str) -> dict[str, Any]:
    """Run only P1 after its bound Run Authorization permits this exact operation."""
    result = _base_result()
    if operation != OPERATION:
        result["failure_code"] = "operation_rejected"
        return result
    token: str | None = None
    temporary_directory: tempfile.TemporaryDirectory[str] | None = None
    try:
        lifecycle = LIFECYCLE.Lifecycle(Path.cwd().resolve(), lifecycle_id)
        contract, state = lifecycle._guard(OPERATION)
        settings = RUNTIME_CONFIG.load_runtime_settings()
        if configured_origin() != ORIGIN:
            raise SafeFailure("origin_rejected")
        result["origin_valid"] = True
        jwt = make_jwt(settings.app_id, settings.key_path)
        baseline_status, baseline = request_json("GET", f"/app/installations/{settings.installation_id}", f"Bearer {jwt}")
        if baseline_status != 200 or not _valid_installation_permissions(baseline.get("permissions")):
            result["installation_permissions_valid"] = False
            raise SafeFailure("installation_permissions_rejected")
        result["installation_permissions_valid"] = True
        refreshed_contract, refreshed_state = lifecycle._guard(OPERATION)
        if refreshed_contract != contract or refreshed_state != state:
            raise LIFECYCLE.StopNeedsHuman("state_changed_before_authentication")
        if RUNTIME_CONFIG.load_runtime_settings() != settings:
            raise SafeFailure("runtime_config_changed_before_mint")
        mint_status, minted = request_json("POST", f"/app/installations/{settings.installation_id}/access_tokens", f"Bearer {jwt}", {"repositories": ["megabrain"], "permissions": READ_TOKEN_REQUEST_PERMISSIONS})
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
    except LIFECYCLE.StopNeedsHuman as exc:
        result["failure_code"] = str(exc)
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
                result["revocation"] = "failed"; result["failure_code"] = "revocation_failed"
        if temporary_directory is not None:
            try:
                temporary_directory.cleanup(); result["temporary_cleanup"] = True
            except Exception:
                result["temporary_cleanup"] = False; result["failure_code"] = "cleanup_failed"
        token = None
    if result["failure_code"] is None:
        result["status"] = "ok"
    return result

def main() -> int:
    parser = argparse.ArgumentParser(description="Run the fixed B4.2 P1 read-only dev-ref validator.")
    parser.add_argument("--operation", required=True, choices=[OPERATION])
    parser.add_argument("--lifecycle-id", required=True)
    arguments = parser.parse_args()
    result = run_operation(arguments.operation, arguments.lifecycle_id)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["status"] == "ok" else 1

if __name__ == "__main__":
    raise SystemExit(main())
