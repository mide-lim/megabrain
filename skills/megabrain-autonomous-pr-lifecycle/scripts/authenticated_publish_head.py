#!/usr/bin/env python3
"""Closed B4.2 P2 adapter for one authenticated, contract-bound head push."""
from __future__ import annotations

import argparse
import base64
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
OPERATION = "publish-head"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
EXPECTED_INSTALLATION_PERMISSIONS = {
    "actions": "read",
    "contents": "write",
    "metadata": "read",
    "pull_requests": "write",
    "statuses": "read",
    "workflows": "write",
}
PUBLISH_TOKEN_REQUEST_PERMISSIONS = {"contents": "write"}
GIT_BINARY = "/usr/bin/git"
OPENSSL_BINARY = "/usr/bin/openssl"


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
    """An expected, non-sensitive failure represented by a symbolic code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def validate_privileged_executable(path: str) -> None:
    """Accept only a fixed root-owned, non-writable executable path."""
    try:
        executable_stat = os.lstat(path)
    except OSError as exc:
        raise SafeFailure("privileged_executable_invalid") from exc
    executable_mode = executable_stat.st_mode
    if (
        stat.S_ISLNK(executable_mode)
        or not stat.S_ISREG(executable_mode)
        or executable_stat.st_uid != 0
        or executable_mode & (stat.S_IWGRP | stat.S_IWOTH)
        or not executable_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    ):
        raise SafeFailure("privileged_executable_invalid")


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
    validate_privileged_executable(GIT_BINARY)
    completed = subprocess.run(
        [GIT_BINARY, "remote", "get-url", "origin"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        timeout=10,
    )
    if completed.returncode != 0:
        raise SafeFailure("origin_rejected")
    return completed.stdout.strip()


def validate_push_destination() -> None:
    """Require one exact effective HTTPS push target before any mutation."""
    try:
        validate_privileged_executable(GIT_BINARY)
        configured = subprocess.run(
            [GIT_BINARY, "config", "--local", "--get-all", "remote.origin.pushurl"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=10,
        )
        effective = subprocess.run(
            [GIT_BINARY, "remote", "get-url", "--all", "--push", "origin"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SafeFailure("push_destination_rejected") from exc
    if configured.returncode not in {0, 1} or effective.returncode != 0:
        raise SafeFailure("push_destination_rejected")
    configured_values = configured.stdout.splitlines() if configured.returncode == 0 else []
    effective_values = effective.stdout.splitlines()
    if (configured_values and configured_values != [ORIGIN]) or effective_values != [ORIGIN]:
        raise SafeFailure("push_destination_rejected")


def validate_key_path(key_path: str) -> None:
    try:
        key_stat = os.lstat(key_path)
    except OSError as exc:
        raise SafeFailure("key_invalid") from exc
    if not stat.S_ISREG(key_stat.st_mode) or stat.S_IMODE(key_stat.st_mode) & 0o077:
        raise SafeFailure("key_invalid")


def make_jwt(app_id: str, key_path: str, now: int | None = None) -> str:
    validate_privileged_executable(OPENSSL_BINARY)
    issued_at = int(time.time() if now is None else now)
    header = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64url(json.dumps({"iat": issued_at - 30, "exp": issued_at + 540, "iss": app_id}, separators=(",", ":")).encode())
    try:
        signed = subprocess.run(
            [OPENSSL_BINARY, "dgst", "-sha256", "-sign", key_path],
            input=f"{header}.{payload}".encode("ascii"),
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


def request_json(method: str, path: str, authorization: str, payload: Mapping[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        f"{API_ROOT}{path}", data=body, method=method,
        headers={
            "Accept": "application/vnd.github+json", "Authorization": authorization,
            "User-Agent": "megabrain-b4-2-p2-controlled-push",
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


def _valid_publish_token_permissions(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("contents") == "write"
        and set(value).issubset({"contents", "metadata"})
        and value.get("metadata", "read") == "read"
    )


def _valid_scope(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("total_count") == 1
        and isinstance(value.get("repositories"), list)
        and len(value["repositories"]) == 1
        and isinstance(value["repositories"][0], dict)
        and value["repositories"][0].get("full_name") == REPOSITORY
    )


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


def _allowed_git_command(command: list[str], branch: str) -> bool:
    ref = f"refs/heads/{branch}"
    fixed = {
        ("git", "symbolic-ref", "--short", "HEAD"),
        ("git", "remote", "get-url", "origin"),
        ("git", "rev-parse", "HEAD"),
        ("git", "status", "--porcelain=v1", "--untracked-files=all"),
        ("git", "ls-remote", "origin", ref),
        ("git", "push", "origin", f"HEAD:{ref}"),
    }
    if tuple(command) in fixed:
        return True
    if len(command) == 5 and command[:3] == ["git", "merge-base", "--is-ancestor"]:
        return all(SHA_RE.fullmatch(value) for value in command[3:])
    if len(command) == 9 and command[:6] == ["git", "diff", "--name-status", "-z", "--find-renames=100%", "--find-copies=100%"] and command[6] == "--find-copies-harder":
        return all(SHA_RE.fullmatch(value) for value in command[7:9])
    if len(command) == 6 and command[:3] == ["git", "ls-tree", "-z"] and SHA_RE.fullmatch(command[3]) and command[4] == "--":
        return bool(command[5]) and "\x00" not in command[5]
    return False


def _isolated_git_environment(home: str, token: str | None = None, askpass_path: str | None = None) -> dict[str, str]:
    environment = {
        "HOME": home,
        "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
    }
    if token is not None and askpass_path is not None:
        environment["GIT_ASKPASS"] = askpass_path
        environment["MEGABRAIN_GITHUB_APP_TOKEN"] = token
    return environment


def _run_isolated_git(command: list[str], cwd: Path, home: str, *, token: str | None = None,
                      askpass_path: str | None = None) -> str:
    validate_privileged_executable(GIT_BINARY)
    isolated_command = [
        GIT_BINARY, "-c", "credential.helper=", "-c", "credential.useHttpPath=true",
        "-c", "credential.interactive=false", "-c", "core.hooksPath=/dev/null",
        *command[1:],
    ]
    try:
        completed = subprocess.run(
            isolated_command, cwd=cwd,
            env=_isolated_git_environment(home, token, askpass_path),
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, check=False, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LIFECYCLE.StopNeedsHuman("git_command_rejected") from exc
    if completed.returncode != 0:
        raise LIFECYCLE.StopNeedsHuman("git_command_rejected")
    return completed.stdout.strip()


def source_runner(temp_directory: str, branch: str):
    """Run only local validation Git commands without an installation token."""
    def run(command: list[str], cwd: Path) -> str:
        if not _allowed_git_command(command, branch) or command[1] in {"ls-remote", "push"}:
            raise LIFECYCLE.StopNeedsHuman("git_command_rejected")
        return _run_isolated_git(command, cwd, temp_directory)
    return run


def create_isolated_staging_repository(source_root: Path, staging_root: Path, branch: str,
                                       approved_head: str, temporary_home: str) -> None:
    """Import only the approved source commit graph before credentials exist."""
    if not SHA_RE.fullmatch(approved_head):
        raise LIFECYCLE.StopNeedsHuman("local_head_rejected")
    staging_root.mkdir(mode=0o700)
    _run_isolated_git(["git", "init", "--quiet"], staging_root, temporary_home)
    _run_isolated_git(
        ["git", "fetch", "--no-tags", "--no-recurse-submodules", str(source_root), approved_head],
        staging_root, temporary_home,
    )
    _run_isolated_git(["git", "cat-file", "-e", f"{approved_head}^{{commit}}"], staging_root, temporary_home)
    _run_isolated_git(["git", "update-ref", f"refs/heads/{branch}", approved_head], staging_root, temporary_home)
    _run_isolated_git(["git", "symbolic-ref", "HEAD", f"refs/heads/{branch}"], staging_root, temporary_home)
    _run_isolated_git(["git", "reset", "--hard", "--quiet", approved_head], staging_root, temporary_home)
    if _run_isolated_git(["git", "rev-parse", "HEAD"], staging_root, temporary_home) != approved_head:
        raise LIFECYCLE.StopNeedsHuman("staged_head_mismatch")
    if _run_isolated_git(["git", "remote"], staging_root, temporary_home):
        raise LIFECYCLE.StopNeedsHuman("staging_origin_rejected")
    _run_isolated_git(["git", "remote", "add", "origin", ORIGIN], staging_root, temporary_home)
    if (_run_isolated_git(["git", "remote"], staging_root, temporary_home) != "origin"
            or _run_isolated_git(["git", "remote", "get-url", "origin"], staging_root, temporary_home) != ORIGIN):
        raise LIFECYCLE.StopNeedsHuman("staging_origin_rejected")


def validate_source_for_staging(lifecycle: Any, contract: Mapping[str, Any], state: Mapping[str, Any]) -> str:
    """Complete every local contract, checkout, and committed-range check pre-token."""
    head = lifecycle._validate_checkout(contract)
    lifecycle._validate_committed_paths(contract, state.get("head_sha"), head)
    lifecycle._correction_count(contract, state)
    if type(state.get("published_once")) is not bool:
        raise LIFECYCLE.StopNeedsHuman("publication_state_rejected")
    return head


def controlled_runner(temp_directory: str, askpass_path: str, token: str, branch: str,
                      staging_root: Path):
    def run(command: list[str], cwd: Path) -> str:
        if not _allowed_git_command(command, branch) or cwd.resolve() != staging_root.resolve():
            raise LIFECYCLE.StopNeedsHuman("git_command_rejected")
        return _run_isolated_git(command, cwd, temp_directory, token=token, askpass_path=askpass_path)
    return run


def _base_result() -> dict[str, Any]:
    return {
        "operation": OPERATION, "status": "failed", "failure_code": None,
        "origin_valid": False, "installation_permissions_valid": None,
        "publish_token_permissions_valid": None, "scope_valid": None,
        "publish": None, "remote_sha_verified": None,
        "revocation": "not_attempted", "temporary_cleanup": None,
    }


def run_operation(operation: str, lifecycle_id: str, operational_gate_approved: bool, environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Run only the exact contract-bound `publish-head` after a human gate."""
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
        validate_privileged_executable(GIT_BINARY)
        validate_privileged_executable(OPENSSL_BINARY)
        if configured_origin() != ORIGIN:
            raise SafeFailure("origin_rejected")
        validate_push_destination()
        result["origin_valid"] = True
        source_root = Path.cwd().resolve()
        lifecycle = LIFECYCLE.Lifecycle(source_root, lifecycle_id)
        contract, state = lifecycle._guard()
        branch = contract["branch"]
        validate_key_path(key_path)
        temporary_directory = tempfile.TemporaryDirectory(prefix="megabrain-b4-2-p2-")
        result["temporary_cleanup"] = False
        lifecycle.runner = source_runner(temporary_directory.name, branch)
        approved_head = validate_source_for_staging(lifecycle, contract, state)
        staging_root = Path(temporary_directory.name) / "staging"
        create_isolated_staging_repository(source_root, staging_root, branch, approved_head, temporary_directory.name)
        jwt = make_jwt(app_id, key_path)
        baseline_status, baseline = request_json("GET", f"/app/installations/{installation_id}", f"Bearer {jwt}")
        if baseline_status != 200 or not _valid_installation_permissions(baseline.get("permissions")):
            result["installation_permissions_valid"] = False
            raise SafeFailure("installation_permissions_rejected")
        result["installation_permissions_valid"] = True
        mint_status, minted = request_json("POST", f"/app/installations/{installation_id}/access_tokens", f"Bearer {jwt}", {"repositories": ["megabrain"], "permissions": PUBLISH_TOKEN_REQUEST_PERMISSIONS})
        jwt = ""
        candidate = minted.get("token") if mint_status == 201 else None
        if not isinstance(candidate, str) or not candidate:
            raise SafeFailure("token_mint_failed")
        token = candidate
        if not _valid_publish_token_permissions(minted.get("permissions")):
            result["publish_token_permissions_valid"] = False
            raise SafeFailure("token_permissions_rejected")
        result["publish_token_permissions_valid"] = True
        scope_status, scope = request_json("GET", "/installation/repositories", f"token {token}")
        if scope_status != 200 or not _valid_scope(scope):
            result["scope_valid"] = False
            raise SafeFailure("scope_rejected")
        result["scope_valid"] = True
        runner = controlled_runner(
            temporary_directory.name, create_askpass(temporary_directory.name), token, branch, staging_root,
        )
        staged_lifecycle = LIFECYCLE.Lifecycle(staging_root, lifecycle_id)
        staged_lifecycle.runner = runner
        with staged_lifecycle._publish_reservation():
            published = staged_lifecycle._publish_head_locked()
        result["publish"] = True
        result["remote_sha_verified"] = published.get("head_sha") if isinstance(published.get("head_sha"), str) else None
        if result["remote_sha_verified"] is None:
            raise SafeFailure("remote_head_mismatch")
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
        result["status"] = "ok"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the fixed B4.2 P2 controlled publish-head adapter.")
    parser.add_argument("--operation", required=True, choices=[OPERATION])
    parser.add_argument("--lifecycle-id", required=True)
    parser.add_argument("--operational-gate-approved", action="store_true")
    arguments = parser.parse_args()
    result = run_operation(arguments.operation, arguments.lifecycle_id, arguments.operational_gate_approved)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
