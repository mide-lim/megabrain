#!/usr/bin/env python3
"""Closed B4.2 P4 adapter for one authenticated, contract-bound CI observation."""
from __future__ import annotations

import argparse
import base64
import copy
import importlib.util
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
API_ROOT = "https://api.github.com"
OPERATION = "observe-ci"
GIT_BINARY = "/usr/bin/git"
OPENSSL_BINARY = "/usr/bin/openssl"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
EXPECTED_INSTALLATION_PERMISSIONS = {
    "actions": "read",
    "contents": "write",
    "metadata": "read",
    "pull_requests": "write",
    "statuses": "read",
    "workflows": "write",
}
OBSERVE_TOKEN_REQUEST_PERMISSIONS = {
    "pull_requests": "read",
    "actions": "read",
    "statuses": "read",
    "metadata": "read",
}


def _load_lifecycle() -> Any:
    path = Path(__file__).with_name("autonomous_pr_lifecycle.py")
    specification = importlib.util.spec_from_file_location("megabrain_b42_lifecycle", path)
    if specification is None or specification.loader is None:
        raise RuntimeError("lifecycle_unavailable")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


LIFECYCLE = _load_lifecycle()


class SafeFailure(Exception):
    """An expected non-sensitive failure represented by a symbolic code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def validate_privileged_executable(path: str) -> None:
    if path not in {GIT_BINARY, OPENSSL_BINARY}:
        raise SafeFailure("privileged_executable_invalid")
    try:
        executable_stat = os.lstat(path)
    except OSError as exc:
        raise SafeFailure("privileged_executable_invalid") from exc
    executable_mode = executable_stat.st_mode
    if (stat.S_ISLNK(executable_mode) or not stat.S_ISREG(executable_mode)
            or executable_stat.st_uid != 0 or executable_mode & (stat.S_IWGRP | stat.S_IWOTH)
            or not executable_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)):
        raise SafeFailure("privileged_executable_invalid")


def _required_environment(environ: Mapping[str, str]) -> tuple[str, str, str]:
    names = ("MEGABRAIN_GITHUB_APP_ID", "MEGABRAIN_GITHUB_APP_INSTALLATION_ID", "MEGABRAIN_GITHUB_APP_KEY_PATH")
    values = tuple(environ.get(name, "") for name in names)
    if not values[0].isdecimal() or not values[1].isdecimal() or not values[2]:
        raise SafeFailure("environment_missing")
    return values  # type: ignore[return-value]


def validate_key_path(key_path: str) -> None:
    try:
        key_stat = os.lstat(key_path)
    except OSError as exc:
        raise SafeFailure("key_invalid") from exc
    if stat.S_ISLNK(key_stat.st_mode) or not stat.S_ISREG(key_stat.st_mode) or stat.S_IMODE(key_stat.st_mode) & 0o077:
        raise SafeFailure("key_invalid")


def _git_environment(home: str) -> dict[str, str]:
    return {"HOME": home, "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}


def _run_source_git(command: list[str], cwd: Path, home: str) -> str:
    validate_privileged_executable(GIT_BINARY)
    invocation = [GIT_BINARY, "-c", "credential.helper=", "-c", "credential.interactive=false", "-c", "core.hooksPath=/dev/null", *command[1:]]
    try:
        completed = subprocess.run(invocation, cwd=cwd, env=_git_environment(home), stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, check=False, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LIFECYCLE.StopNeedsHuman("git_command_rejected") from exc
    if completed.returncode != 0:
        raise LIFECYCLE.StopNeedsHuman("git_command_rejected")
    return completed.stdout.strip()


def _allowed_source_git(command: list[str], branch: str) -> bool:
    ref = f"refs/heads/{branch}"
    return tuple(command) in {
        ("git", "symbolic-ref", "--short", "HEAD"),
        ("git", "remote", "get-url", "origin"),
        ("git", "rev-parse", "HEAD"),
        ("git", "status", "--porcelain=v1", "--untracked-files=all"),
        ("git", "ls-remote", "origin", ref),
    }


def source_runner(temporary_home: str, branch: str):
    """Permit only token-free source and remote-ref reads for P4 validation."""
    def run(command: list[str], cwd: Path) -> str:
        if not _allowed_source_git(command, branch):
            raise LIFECYCLE.StopNeedsHuman("git_command_rejected")
        return _run_source_git(command, cwd, temporary_home)
    return run


def configured_origin(repository_root: Path, temporary_home: str) -> str:
    return _run_source_git(["git", "remote", "get-url", "origin"], repository_root, temporary_home)


def make_jwt(app_id: str, key_path: str, now: int | None = None) -> str:
    validate_privileged_executable(OPENSSL_BINARY)
    issued_at = int(time.time() if now is None else now)
    header = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64url(json.dumps({"iat": issued_at - 30, "exp": issued_at + 540, "iss": app_id}, separators=(",", ":")).encode())
    try:
        signed = subprocess.run([OPENSSL_BINARY, "dgst", "-sha256", "-sign", key_path], input=f"{header}.{payload}".encode("ascii"),
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SafeFailure("jwt_sign_failed") from exc
    if signed.returncode != 0 or not signed.stdout:
        raise SafeFailure("jwt_sign_failed")
    return f"{header}.{payload}.{_b64url(signed.stdout)}"


def request_json(method: str, path: str, authorization: str, payload: Mapping[str, Any] | None = None) -> tuple[int, Any]:
    body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(f"{API_ROOT}{path}", data=body, method=method, headers={
        "Accept": "application/vnd.github+json", "Authorization": authorization,
        "User-Agent": "megabrain-b4-2-p4-controlled-ci-observation",
        **({"Content-Type": "application/json"} if body is not None else {}),
    })
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            response_body = response.read()
            return response.status, json.loads(response_body.decode("utf-8")) if response_body else {}
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as exc:
        raise SafeFailure("api_request_failed") from exc


def _valid_installation_permissions(value: Any) -> bool:
    return isinstance(value, dict) and "administration" not in value and value == EXPECTED_INSTALLATION_PERMISSIONS


def _valid_observe_token_permissions(value: Any) -> bool:
    return isinstance(value, dict) and value == OBSERVE_TOKEN_REQUEST_PERMISSIONS and "contents" not in value and "administration" not in value


def _valid_scope(value: Any) -> bool:
    return (isinstance(value, dict) and value.get("total_count") == 1 and isinstance(value.get("repositories"), list)
            and len(value["repositories"]) == 1 and isinstance(value["repositories"][0], dict)
            and value["repositories"][0].get("full_name") == REPOSITORY)


def _matching_run_ids(body: Any, sha: str, number: int) -> list[int]:
    if not isinstance(body, Mapping) or not isinstance(body.get("workflow_runs"), list):
        return []
    return [run["id"] for run in body["workflow_runs"] if isinstance(run, Mapping) and type(run.get("id")) is int
            and run.get("event") == "pull_request" and run.get("head_sha") == sha and isinstance(run.get("pull_requests"), list)
            and any(isinstance(entry, Mapping) and entry.get("number") == number for entry in run["pull_requests"])]


def authenticated_observe_request(token: str, state: Mapping[str, Any]):
    """Expose exactly three fixed GET observation endpoints and no log endpoint."""
    number, sha = state.get("pr_number"), state.get("head_sha")
    if type(number) is not int or number <= 0 or not isinstance(sha, str) or not SHA_RE.fullmatch(sha):
        raise LIFECYCLE.StopNeedsHuman("pr_or_head_missing")
    pr_path = f"/repos/{REPOSITORY}/pulls/{number}"
    runs_path = f"/repos/{REPOSITORY}/actions/runs?event=pull_request&head_sha={sha}"
    selected_run_id: int | None = None

    def request(method: str, path: str, payload: Mapping[str, Any] | None = None) -> Any:
        nonlocal selected_run_id
        allowed = (method == "GET" and payload is None and path in {pr_path, runs_path})
        if selected_run_id is not None and method == "GET" and payload is None and path == f"/repos/{REPOSITORY}/actions/runs/{selected_run_id}/jobs":
            allowed = True
        if not allowed:
            raise LIFECYCLE.StopNeedsHuman("api_request_rejected")
        status, body = request_json(method, path, f"token {token}")
        if status != 200:
            raise LIFECYCLE.StopNeedsHuman("api_response_rejected")
        if path == runs_path:
            matching = _matching_run_ids(body, sha, number)
            selected_run_id = matching[0] if len(matching) == 1 else None
        return body
    return request


def validate_source_for_observe_ci(lifecycle: Any, contract: Mapping[str, Any], state: Mapping[str, Any]) -> str:
    """Complete all contract/state/local/ref validation before JWT creation."""
    head = lifecycle._validate_checkout(contract)
    number = state.get("pr_number")
    if (state.get("published_once") is not True or type(number) is not int or number <= 0 or state.get("head_sha") != head
            or state.get("pending_correction_sha") is not None):
        raise LIFECYCLE.StopNeedsHuman("pr_or_head_missing")
    lifecycle._validate_remote_head(contract, head)
    return head


def validated_jobs_evidence(observed: Mapping[str, Any], contract: Mapping[str, Any]) -> dict[str, str]:
    """Accept only exact completed success/failure conclusions; no provider text."""
    expected = contract.get("expected_ci_jobs")
    jobs = observed.get("jobs")
    if (not isinstance(expected, list) or not isinstance(jobs, Mapping) or set(jobs) != set(expected)
            or any(jobs.get(name) not in {"success", "failure"} for name in expected)):
        raise SafeFailure("ci_result_rejected")
    return {name: jobs[name] for name in expected}


def _base_result() -> dict[str, Any]:
    return {"operation": OPERATION, "status": "failed", "failure_code": None, "origin_valid": False,
            "contract_valid": False, "preconditions_valid": False, "installation_permissions_valid": None,
            "observe_token_permissions_valid": None, "scope_valid": None, "pr_number": None,
            "head_sha": None, "workflow_run_id": None, "revocation": "not_attempted", "temporary_cleanup": None}


def run_operation(operation: str, lifecycle_id: str, environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Run only fixed observe-ci when state binds a Run Authorization."""
    result = _base_result()
    if operation != OPERATION:
        result["failure_code"] = "operation_rejected"
        return result
    environment = os.environ if environ is None else environ
    token: str | None = None
    lifecycle: Any = None
    temporary_directory: tempfile.TemporaryDirectory[str] | None = None
    reservation: Any = None
    reservation_acquired = False
    expected_state: dict[str, Any] | None = None
    expected_fingerprint: str | None = None
    head: str | None = None
    deferred_state: dict[str, Any] | None = None
    try:
        app_id, installation_id, key_path = _required_environment(environment)
        validate_privileged_executable(GIT_BINARY)
        validate_privileged_executable(OPENSSL_BINARY)
        validate_key_path(key_path)
        source_root = Path.cwd().resolve()
        lifecycle = LIFECYCLE.Lifecycle(source_root, lifecycle_id)
        reservation = lifecycle._publish_reservation()
        reservation.__enter__()
        reservation_acquired = True
        contract, state = lifecycle._guard(OPERATION)
        expected_state = copy.deepcopy(state)
        expected_fingerprint = state.get("fingerprint")
        if not isinstance(expected_fingerprint, str):
            raise LIFECYCLE.StopNeedsHuman("contract_fingerprint_divergent")
        result["contract_valid"] = True
        temporary_directory = tempfile.TemporaryDirectory(prefix="megabrain-b4-2-p4-")
        result["temporary_cleanup"] = False
        lifecycle.runner = source_runner(temporary_directory.name, contract["branch"])
        if configured_origin(source_root, temporary_directory.name) != ORIGIN:
            raise SafeFailure("origin_rejected")
        result["origin_valid"] = True
        contract, state = lifecycle._guard(OPERATION)
        if state != expected_state or state.get("fingerprint") != expected_fingerprint:
            raise LIFECYCLE.StopNeedsHuman("state_changed_before_authentication")
        head = validate_source_for_observe_ci(lifecycle, contract, state)
        result["preconditions_valid"] = True
        jwt = make_jwt(app_id, key_path)
        baseline_status, baseline = request_json("GET", f"/app/installations/{installation_id}", f"Bearer {jwt}")
        if baseline_status != 200 or not _valid_installation_permissions(baseline.get("permissions") if isinstance(baseline, Mapping) else None):
            result["installation_permissions_valid"] = False
            raise SafeFailure("installation_permissions_rejected")
        result["installation_permissions_valid"] = True
        mint_status, minted = request_json("POST", f"/app/installations/{installation_id}/access_tokens", f"Bearer {jwt}",
                                           {"repositories": ["megabrain"], "permissions": OBSERVE_TOKEN_REQUEST_PERMISSIONS})
        jwt = ""
        candidate = minted.get("token") if mint_status == 201 and isinstance(minted, Mapping) else None
        if not isinstance(candidate, str) or not candidate:
            raise SafeFailure("token_mint_failed")
        token = candidate
        if not _valid_observe_token_permissions(minted.get("permissions")):
            result["observe_token_permissions_valid"] = False
            raise SafeFailure("token_permissions_rejected")
        result["observe_token_permissions_valid"] = True
        scope_status, scope = request_json("GET", "/installation/repositories", f"token {token}")
        if scope_status != 200 or not _valid_scope(scope):
            result["scope_valid"] = False
            raise SafeFailure("scope_rejected")
        result["scope_valid"] = True
        lifecycle.request = authenticated_observe_request(token, state)

        def defer_state_write(value: dict[str, Any]) -> None:
            nonlocal deferred_state
            deferred_state = copy.deepcopy(value)

        observed = lifecycle._observe_ci_locked(state_writer=defer_state_write)
        if observed.get("head_sha") != head or type(observed.get("workflow_run_id")) is not int:
            raise SafeFailure("ci_result_rejected")
        jobs = validated_jobs_evidence(observed, contract)
        result.update({"pr_number": state["pr_number"], "head_sha": head, "workflow_run_id": observed["workflow_run_id"], "jobs": jobs})
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
            if (lifecycle is None or expected_state is None or expected_fingerprint is None or head is None
                    or deferred_state is None):
                result["failure_code"] = "state_commit_rejected"
            else:
                try:
                    lifecycle._commit_deferred_ci_state(expected_state, expected_fingerprint, head, deferred_state)
                except LIFECYCLE.StopNeedsHuman as exc:
                    result["failure_code"] = str(exc)
                except Exception:
                    result["failure_code"] = "state_commit_rejected"
        if reservation_acquired:
            try:
                reservation.__exit__(None, None, None)
            except LIFECYCLE.StopNeedsHuman as exc:
                result["failure_code"] = str(exc)
            except Exception:
                result["failure_code"] = "publish_reservation_cleanup_failed"
    if result["failure_code"] is None:
        result["status"] = "ok"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the fixed B4.2 P4 controlled CI observation adapter.")
    parser.add_argument("--operation", required=True, choices=[OPERATION])
    parser.add_argument("--lifecycle-id", required=True)
    arguments = parser.parse_args()
    result = run_operation(arguments.operation, arguments.lifecycle_id)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
