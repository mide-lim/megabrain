#!/usr/bin/env python3
"""Closed, contract-bound B4.2 autonomous PR lifecycle (no credentials included)."""

from __future__ import annotations

import datetime as dt
import fnmatch
import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping

REPOSITORY = "mide-lim/megabrain"
ORIGIN_URL = "https://github.com/mide-lim/megabrain.git"
API_ROOT = "https://api.github.com"
CONTRACT_ROOT = Path("/etc/megabrain/hermes-contracts/b4.2")
RUN_AUTHORIZATION_ROOT = Path("/etc/megabrain/hermes-authorizations/b4.3")
MAX_RUN_AUTHORIZATION_TTL = dt.timedelta(hours=24)
RUN_AUTHORIZATION_OPERATIONS = frozenset({
    "preflight", "publish-head", "ensure-pr", "observe-ci",
    "authorize-correction", "finalize-correction", "report-ready",
})
RUN_AUTHORIZATION_FIELDS = frozenset({
    "version", "authorization_id", "lifecycle_id", "task_contract_fingerprint",
    "allowed_operations", "issued_at", "expires_at",
})
RUN_AUTHORIZATION_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
UTC_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

PUBLIC_OPERATIONS = frozenset({"preflight", "publish-head", "ensure-pr", "observe-ci", "refresh-from-dev", "report-ready", "authorize-correction", "finalize-correction"})
DENIED_PATHS = (
    "skills/**",
    "skills/megabrain-autonomous-pr-lifecycle/**",
    "skills/megabrain-github-app-auth/**",
    ".github/workflows/**",
    "AGENTS.md",
    "docs/RISK_POLICY.md",
    "docs/DEFINITION_OF_DONE.md",
    "docs/TASK_CONTRACT*.md",
    "docs/AUTONOMOUS_PR_LIFECYCLE_B4_2*.md",
    "docs/GITHUB_APP_AUTH_BOOTSTRAP*.md",
    "docs/DEVELOPMENT_WORKFLOW.md",
    "docs/DECISIONS.md",
    "contracts/**",
    "infra/**",
)
EXPECTED_FIELDS = frozenset({
    "version", "lifecycle_id", "status", "repository", "origin_url", "branch", "base",
    "head_sha_initial", "allowed_paths", "expected_ci_jobs", "allow_safe_refresh",
    "max_corrections", "poll_deadline_utc", "owner_human", "approval_reference",
    "pr_title", "pr_body",
})
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")
LIFECYCLE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
BRANCH_RE = re.compile(r"^agent/[a-z0-9][a-z0-9._-]{0,62}$")
MAX_WORKFLOW_JSON_FILES = 32
MAX_JSON_FILE_BYTES = 262144
MAX_DIAGNOSTIC_ENTRIES = 8
MAX_SAFE_RELATIVE_PATH_LENGTH = 128
CORRECTION_COMMIT_MESSAGE = "fix(b4.2): correct repository validation"
LOCAL_GIT_BINARY = "/usr/bin/git"

Runner = Callable[[list[str], Path], str]
Request = Callable[[str, str, Mapping[str, Any] | None], Any]


class StopNeedsHuman(RuntimeError):
    """Fail-closed terminal state; no caller should retry without a human gate."""


def canonical_json(value: Mapping[str, Any]) -> bytes:
    filtered = {key: value[key] for key in value if key != "fingerprint"}
    return json.dumps(filtered, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def fingerprint(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _trusted_utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _strict_json(text: str) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_key")
            result[key] = value
        return result
    value = json.loads(text, object_pairs_hook=reject_duplicates)
    if not isinstance(value, dict):
        raise ValueError("object_required")
    return value


def _parse_utc_timestamp(value: Any) -> dt.datetime:
    if not isinstance(value, str) or not UTC_TIMESTAMP_RE.fullmatch(value):
        raise StopNeedsHuman("run_authorization_time_rejected")
    try:
        return dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except ValueError as exc:
        raise StopNeedsHuman("run_authorization_time_rejected") from exc


def _safe_relative(value: str) -> bool:
    path = PurePosixPath(value)
    return bool(value) and not path.is_absolute() and ".." not in path.parts and "\\" not in value and "\x00" not in value


def normalize_p5_state(state: Mapping[str, Any]) -> dict[str, Any]:
    """Read legacy state without persisting defaults during a read."""
    normalized = dict(state)
    normalized.setdefault("ci_failure", None)
    normalized.setdefault("pending_correction_sha", None)
    normalized.setdefault("pending_publish_attempted", False)
    return normalized


def repository_validation_json_v1(root: Path, allowed_paths: list[str]) -> dict[str, Any]:
    """Parse fixed local workflow JSON files without subprocesses or network."""
    del allowed_paths  # Authorization separately decides whether diagnostics are in scope.
    directory = root / "workflows"
    invalid: list[dict[str, Any]] = []
    try:
        entries = [] if not directory.exists() else sorted(directory.iterdir(), key=lambda item: item.name)
    except OSError as exc:
        raise StopNeedsHuman("json_profile_directory_rejected") from exc
    files = [item for item in entries if item.name.endswith(".json")]
    if not files:
        return {"profile_id": "repository-validation-json-v1", "result": "fail",
                "failure_code": "zero_workflow_json_files", "invalid_files": []}
    if len(files) > MAX_WORKFLOW_JSON_FILES:
        raise StopNeedsHuman("json_profile_file_limit_rejected")
    for item in files:
        relative = item.relative_to(root).as_posix()
        try:
            item_stat = item.lstat()
        except OSError as exc:
            raise StopNeedsHuman("json_profile_file_rejected") from exc
        if (not _safe_relative(relative) or len(relative) > MAX_SAFE_RELATIVE_PATH_LENGTH
                or stat.S_ISLNK(item_stat.st_mode) or not stat.S_ISREG(item_stat.st_mode)
                or item_stat.st_size > MAX_JSON_FILE_BYTES):
            raise StopNeedsHuman("json_profile_file_rejected")
        try:
            content = item.read_text(encoding="utf-8")
            json.loads(content)
        except json.JSONDecodeError as exc:
            if len(invalid) >= MAX_DIAGNOSTIC_ENTRIES:
                raise StopNeedsHuman("json_profile_diagnostic_limit_rejected") from exc
            invalid.append({"path": relative, "reason_code": "json_decode_error", "line": min(max(exc.lineno, 1), MAX_JSON_FILE_BYTES), "column": min(max(exc.colno, 1), MAX_JSON_FILE_BYTES)})
        except (OSError, UnicodeDecodeError) as exc:
            raise StopNeedsHuman("json_profile_file_rejected") from exc
    return {"profile_id": "repository-validation-json-v1", "result": "fail" if invalid else "pass", "invalid_files": invalid}


def _local_git_read(root: Path, arguments: list[str]) -> bytes:
    """Read a local Git object with the fixed system Git binary only."""
    try:
        binary_stat = os.lstat(LOCAL_GIT_BINARY)
        if (stat.S_ISLNK(binary_stat.st_mode) or not stat.S_ISREG(binary_stat.st_mode)
                or binary_stat.st_uid != 0 or stat.S_IMODE(binary_stat.st_mode) & 0o022):
            raise OSError
        completed = subprocess.run(
            [LOCAL_GIT_BINARY, *arguments], cwd=root, check=False,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=False, timeout=10,
            env={"PATH": "/usr/bin:/bin", "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1",
                 "GIT_NO_REPLACE_OBJECTS": "1"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise StopNeedsHuman("json_profile_git_read_rejected") from exc
    if completed.returncode != 0:
        raise StopNeedsHuman("json_profile_git_read_rejected")
    return completed.stdout


def repository_validation_json_v1_for_commit(root: Path, sha: str, allowed_paths: list[str]) -> dict[str, Any]:
    """Run the fixed profile against direct JSON blobs in one committed tree.

    This intentionally reads Git objects rather than the checkout, so a local
    worktree cannot stand in for either S1 or S2 during correction finalization.
    """
    del allowed_paths
    if not SHA_RE.fullmatch(sha):
        raise StopNeedsHuman("json_profile_commit_rejected")
    _local_git_read(root, ["cat-file", "-e", f"{sha}^{{commit}}"])
    workflow_entry = _local_git_read(root, ["ls-tree", "-z", sha, "--", "workflows"])
    if not workflow_entry:
        return {"profile_id": "repository-validation-json-v1", "result": "fail",
                "failure_code": "zero_workflow_json_files", "invalid_files": []}
    try:
        metadata, path = workflow_entry.rstrip(b"\0").split(b"\t", 1)
        mode, object_type, object_id = metadata.split(b" ")
    except ValueError as exc:
        raise StopNeedsHuman("json_profile_commit_rejected") from exc
    if path != b"workflows" or mode != b"040000" or object_type != b"tree" or not SHA_RE.fullmatch(object_id.decode("ascii")):
        raise StopNeedsHuman("json_profile_commit_rejected")
    listing = _local_git_read(root, ["ls-tree", "-z", f"{sha}:workflows"])
    records = listing.split(b"\0")
    if records[-1] != b"":
        raise StopNeedsHuman("json_profile_commit_rejected")
    files: list[tuple[str, str]] = []
    for record in records[:-1]:
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode, object_type, object_id = metadata.split(b" ")
            name = raw_path.decode("utf-8")
            object_sha = object_id.decode("ascii")
        except (UnicodeDecodeError, ValueError) as exc:
            raise StopNeedsHuman("json_profile_commit_rejected") from exc
        relative = f"workflows/{name}"
        if not name.endswith(".json"):
            continue
        if (not _safe_relative(relative) or "/" in name or len(relative) > MAX_SAFE_RELATIVE_PATH_LENGTH
                or mode not in {b"100644", b"100755"} or object_type != b"blob" or not SHA_RE.fullmatch(object_sha)):
            raise StopNeedsHuman("json_profile_commit_rejected")
        files.append((relative, object_sha))
    if not files:
        return {"profile_id": "repository-validation-json-v1", "result": "fail",
                "failure_code": "zero_workflow_json_files", "invalid_files": []}
    if len(files) > MAX_WORKFLOW_JSON_FILES:
        raise StopNeedsHuman("json_profile_file_limit_rejected")
    invalid: list[dict[str, Any]] = []
    for relative, object_sha in files:
        # The blob ID was checked in the exact tree above; read that exact object,
        # never a checkout path or a commit:path revision expression.
        content = _local_git_read(root, ["cat-file", "blob", object_sha])
        if len(content) > MAX_JSON_FILE_BYTES:
            raise StopNeedsHuman("json_profile_file_rejected")
        try:
            json.loads(content.decode("utf-8"))
        except json.JSONDecodeError as exc:
            if len(invalid) >= MAX_DIAGNOSTIC_ENTRIES:
                raise StopNeedsHuman("json_profile_diagnostic_limit_rejected") from exc
            invalid.append({"path": relative, "reason_code": "json_decode_error",
                            "line": min(max(exc.lineno, 1), MAX_JSON_FILE_BYTES),
                            "column": min(max(exc.colno, 1), MAX_JSON_FILE_BYTES)})
        except UnicodeDecodeError as exc:
            raise StopNeedsHuman("json_profile_file_rejected") from exc
    return {"profile_id": "repository-validation-json-v1", "result": "fail" if invalid else "pass", "invalid_files": invalid}


def profile_invalid_paths_allowed(profile: Mapping[str, Any], root: Path, allowed_paths: list[str]) -> bool:
    entries = profile.get("invalid_files")
    if not isinstance(entries, list) or len(entries) > MAX_DIAGNOSTIC_ENTRIES:
        return False
    for entry in entries:
        if not isinstance(entry, Mapping) or set(entry) != {"path", "reason_code", "line", "column"}:
            return False
        path = entry.get("path")
        if (not isinstance(path, str) or not _safe_relative(path) or len(path) > MAX_SAFE_RELATIVE_PATH_LENGTH
                or entry.get("reason_code") != "json_decode_error" or type(entry.get("line")) is not int
                or type(entry.get("column")) is not int or entry["line"] < 1 or entry["column"] < 1):
            return False
        local = root / path
        try:
            mode = local.lstat().st_mode
        except OSError:
            return False
        if stat.S_ISLNK(mode) or not stat.S_ISREG(mode) or not any(fnmatch.fnmatchcase(path, allowed) for allowed in allowed_paths):
            return False
    return True


def profile_invalid_paths_allowed_for_commit(profile: Mapping[str, Any], allowed_paths: list[str]) -> bool:
    """Check bounded committed-tree diagnostics without consulting the checkout."""
    entries = profile.get("invalid_files")
    if not isinstance(entries, list) or not entries or len(entries) > MAX_DIAGNOSTIC_ENTRIES:
        return False
    for entry in entries:
        if (not isinstance(entry, Mapping) or set(entry) != {"path", "reason_code", "line", "column"}
                or not isinstance(entry.get("path"), str) or not _safe_relative(entry["path"])
                or len(entry["path"]) > MAX_SAFE_RELATIVE_PATH_LENGTH
                or entry.get("reason_code") != "json_decode_error" or type(entry.get("line")) is not int
                or type(entry.get("column")) is not int or entry["line"] < 1 or entry["column"] < 1
                or not any(fnmatch.fnmatchcase(entry["path"], allowed) for allowed in allowed_paths)):
            return False
    return True


def _default_runner(command: list[str], cwd: Path) -> str:
    completed = subprocess.run(command, cwd=cwd, check=False, capture_output=True, text=True, env={"PATH": os.environ.get("PATH", ""), "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1"})
    if completed.returncode != 0:
        raise StopNeedsHuman("git_command_rejected")
    return completed.stdout.strip()


class TokenProfiles:
    """Validate operation-specific provider responses without minting credentials."""

    EXPECTED = {
        "publish": {"contents": "write", "metadata": "read"},
        "pr": {"pull_requests": "write", "metadata": "read"},
        "observe": {"pull_requests": "read", "actions": "read", "statuses": "read", "metadata": "read"},
    }

    @classmethod
    def validate(cls, purpose: str, response: Mapping[str, Any]) -> None:
        if purpose not in cls.EXPECTED:
            raise StopNeedsHuman("token_purpose_rejected")
        permissions = response.get("permissions")
        if not isinstance(permissions, Mapping) or dict(permissions) != cls.EXPECTED[purpose]:
            raise StopNeedsHuman("token_permissions_rejected")
        if response.get("repository") != REPOSITORY or response.get("administration") is not False:
            raise StopNeedsHuman("token_scope_rejected")


def _run_ephemeral_token_operation(
    purpose: str,
    mint: Callable[[str], Mapping[str, Any]],
    revoke: Callable[[str], bool],
    cleanup: Callable[[], bool],
    operation: Callable[[str], Any],
) -> Any:
    """Use one purpose-bound token and fail closed if teardown is imperfect.

    The fixed lifecycle adapters supply these callables internally.  They are
    intentionally not part of the command interface: no caller can provide an
    endpoint, command, ref, or token value through B4.2's public operations.
    """
    token: str | None = None
    result: Any = None
    failure: StopNeedsHuman | None = None
    try:
        minted = mint(purpose)
        TokenProfiles.validate(purpose, minted)
        candidate = minted.get("token")
        if not isinstance(candidate, str) or not candidate:
            raise StopNeedsHuman("token_mint_rejected")
        token = candidate
        result = operation(token)
    except StopNeedsHuman as exc:
        failure = exc
    except Exception:
        failure = StopNeedsHuman("token_operation_rejected")
    finally:
        try:
            revoked = token is None or revoke(token)
        except Exception:
            revoked = False
        try:
            cleaned = cleanup()
        except Exception:
            cleaned = False
        token = None
        if not revoked:
            failure = StopNeedsHuman("revocation_failed")
        elif not cleaned:
            failure = StopNeedsHuman("cleanup_failed")
    if failure is not None:
        raise failure
    return result


def _require_live_operations_enabled() -> None:
    # This is deliberately unconditional.  A later separately reviewed
    # control-plane source change must replace this gate alongside live token
    # adapters; a contract, CLI option, environment variable, or Python global
    # cannot enable authenticated behavior in the installed v1 artifact.
    raise StopNeedsHuman("authenticated_operations_not_authorized")


def _parse_response(response: Any) -> Any:
    # Test seams may return (status, body); production adapters may return body only.
    if isinstance(response, tuple):
        status, body = response
        if status < 200 or status >= 300:
            raise StopNeedsHuman("api_response_rejected")
        return body
    return response


class Lifecycle:
    """Only public methods correspond to the six named B4.2 operations."""

    def __init__(self, repository_root: Path, lifecycle_id: str, *, state_root: Path | None = None,
                 runner: Runner | None = None, request: Request | None = None) -> None:
        if not LIFECYCLE_RE.fullmatch(lifecycle_id):
            raise StopNeedsHuman("lifecycle_id_rejected")
        self.root = repository_root.resolve()
        self.lifecycle_id = lifecycle_id
        self.contract_path = CONTRACT_ROOT / f"{lifecycle_id}.json"
        root = (state_root or (Path.home() / ".local/state/megabrain/b4.2")).expanduser().absolute()
        candidate = root
        while candidate != candidate.parent:
            if candidate.exists() and candidate.is_symlink():
                raise StopNeedsHuman("state_root_rejected")
            candidate = candidate.parent
        self.state_root = root
        if self.state_root == self.root or self.root in self.state_root.parents:
            raise StopNeedsHuman("unsafe_state_root")
        self.runner = runner or _default_runner
        self.request = request

    def _safe_existing(self, path: Path) -> None:
        candidate = path
        while candidate != candidate.parent:
            if candidate.exists() and candidate.is_symlink():
                raise StopNeedsHuman("symlink_rejected")
            candidate = candidate.parent

    def _read_regular_text(self, path: Path) -> str:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            raise StopNeedsHuman("safe_file_read_rejected") from exc
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise StopNeedsHuman("safe_file_read_rejected")
            return os.read(descriptor, 1_000_000).decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise StopNeedsHuman("safe_file_read_rejected") from exc
        finally:
            os.close(descriptor)

    def _trusted_contract_path(self) -> None:
        for control_directory in (CONTRACT_ROOT.parent.parent, CONTRACT_ROOT.parent, CONTRACT_ROOT):
            try:
                directory_status = os.lstat(control_directory)
            except OSError as exc:
                raise StopNeedsHuman("contract_root_rejected") from exc
            if (stat.S_ISLNK(directory_status.st_mode) or not stat.S_ISDIR(directory_status.st_mode)
                    or directory_status.st_uid != 0 or stat.S_IMODE(directory_status.st_mode) & 0o022):
                raise StopNeedsHuman("contract_root_rejected")
        try:
            contract_status = os.lstat(self.contract_path)
        except OSError as exc:
            raise StopNeedsHuman("contract_path_rejected") from exc
        if (stat.S_ISLNK(contract_status.st_mode) or not stat.S_ISREG(contract_status.st_mode)
                or contract_status.st_uid != 0 or stat.S_IMODE(contract_status.st_mode) & 0o022):
            raise StopNeedsHuman("contract_path_rejected")

    def _read_trusted_contract_text(self) -> str:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(self.contract_path, flags)
        except OSError as exc:
            raise StopNeedsHuman("contract_unreadable") from exc
        try:
            contract_status = os.fstat(descriptor)
            if (not stat.S_ISREG(contract_status.st_mode) or contract_status.st_uid != 0
                    or stat.S_IMODE(contract_status.st_mode) & 0o022):
                raise StopNeedsHuman("contract_unreadable")
            return os.read(descriptor, 1_000_000).decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise StopNeedsHuman("contract_unreadable") from exc
        finally:
            os.close(descriptor)

    def _contract(self) -> tuple[dict[str, Any], str]:
        self._trusted_contract_path()
        try:
            data = json.loads(self._read_trusted_contract_text())
        except (StopNeedsHuman, json.JSONDecodeError) as exc:
            raise StopNeedsHuman("contract_unreadable") from exc
        if not isinstance(data, dict) or set(data) != EXPECTED_FIELDS:
            raise StopNeedsHuman("contract_schema_rejected")
        if data["version"] != "B4.2.1" or data["lifecycle_id"] != self.lifecycle_id or data["status"] != "APPROVED":
            raise StopNeedsHuman("contract_status_rejected")
        if data["repository"] != REPOSITORY or data["origin_url"] != ORIGIN_URL or data["base"] != "dev":
            raise StopNeedsHuman("contract_identity_rejected")
        if not isinstance(data["branch"], str) or not BRANCH_RE.fullmatch(data["branch"]):
            raise StopNeedsHuman("contract_branch_rejected")
        if not isinstance(data["head_sha_initial"], str) or not SHA_RE.fullmatch(data["head_sha_initial"]):
            raise StopNeedsHuman("contract_sha_rejected")
        if not isinstance(data["allowed_paths"], list) or not all(isinstance(p, str) and _safe_relative(p) for p in data["allowed_paths"]):
            raise StopNeedsHuman("contract_paths_rejected")
        if (not isinstance(data["expected_ci_jobs"], list) or not data["expected_ci_jobs"]
                or len(set(data["expected_ci_jobs"])) != len(data["expected_ci_jobs"])
                or not all(isinstance(job, str) and job for job in data["expected_ci_jobs"])):
            raise StopNeedsHuman("contract_jobs_rejected")

        if type(data["allow_safe_refresh"]) is not bool or type(data["max_corrections"]) is not int or not 0 <= data["max_corrections"] <= 10:
            raise StopNeedsHuman("contract_types_rejected")
        if not all(isinstance(data[key], str) and data[key].strip() for key in ("poll_deadline_utc", "owner_human", "approval_reference", "pr_title", "pr_body")):
            raise StopNeedsHuman("contract_required_value_rejected")
        try:
            expires = dt.datetime.fromisoformat(data["poll_deadline_utc"].replace("Z", "+00:00"))
            if expires.tzinfo is None or expires <= dt.datetime.now(dt.timezone.utc):
                raise ValueError
        except ValueError as exc:
            raise StopNeedsHuman("contract_expired") from exc
        return data, fingerprint(data)

    def _authorization_path(self, authorization_id: str) -> Path:
        if not isinstance(authorization_id, str) or not RUN_AUTHORIZATION_RE.fullmatch(authorization_id):
            raise StopNeedsHuman("run_authorization_schema_rejected")
        return RUN_AUTHORIZATION_ROOT / f"{authorization_id}.json"

    def _trusted_authorization_path(self, authorization_id: str) -> Path:
        path = self._authorization_path(authorization_id)
        directories = (RUN_AUTHORIZATION_ROOT.parent.parent.parent, RUN_AUTHORIZATION_ROOT.parent.parent,
                       RUN_AUTHORIZATION_ROOT.parent, RUN_AUTHORIZATION_ROOT)
        for directory in directories:
            try:
                status = os.lstat(directory)
            except OSError as exc:
                raise StopNeedsHuman("run_authorization_trust_rejected") from exc
            if (stat.S_ISLNK(status.st_mode) or not stat.S_ISDIR(status.st_mode)
                    or status.st_uid != 0 or stat.S_IMODE(status.st_mode) & 0o022):
                raise StopNeedsHuman("run_authorization_trust_rejected")
        try:
            status = os.lstat(path)
        except OSError as exc:
            raise StopNeedsHuman("run_authorization_missing") from exc
        if (stat.S_ISLNK(status.st_mode) or not stat.S_ISREG(status.st_mode)
                or status.st_uid != 0 or stat.S_IMODE(status.st_mode) & 0o022):
            raise StopNeedsHuman("run_authorization_trust_rejected")
        return path

    def _read_authorization(self, authorization_id: str, contract_fingerprint: str) -> tuple[dict[str, Any], str]:
        path = self._trusted_authorization_path(authorization_id)
        try:
            data = _strict_json(self._read_regular_text(path))
        except StopNeedsHuman:
            raise
        except (ValueError, json.JSONDecodeError) as exc:
            raise StopNeedsHuman("run_authorization_schema_rejected") from exc
        if (set(data) != RUN_AUTHORIZATION_FIELDS or type(data.get("version")) is not int
                or data["version"] != 1):
            raise StopNeedsHuman("run_authorization_schema_rejected")
        if (data.get("authorization_id") != authorization_id
                or not isinstance(data.get("lifecycle_id"), str)
                or not LIFECYCLE_RE.fullmatch(data["lifecycle_id"])
                or not isinstance(data.get("task_contract_fingerprint"), str)
                or not FINGERPRINT_RE.fullmatch(data["task_contract_fingerprint"])):
            raise StopNeedsHuman("run_authorization_schema_rejected")
        if data["lifecycle_id"] != self.lifecycle_id:
            raise StopNeedsHuman("run_authorization_lifecycle_mismatch")
        operations = data.get("allowed_operations")
        if (not isinstance(operations, list) or not operations or len(set(operations)) != len(operations)
                or any(not isinstance(value, str) or value not in RUN_AUTHORIZATION_OPERATIONS for value in operations)):
            raise StopNeedsHuman("run_authorization_schema_rejected")
        issued_at = _parse_utc_timestamp(data.get("issued_at"))
        expires_at = _parse_utc_timestamp(data.get("expires_at"))
        if expires_at <= issued_at:
            raise StopNeedsHuman("run_authorization_time_rejected")
        if expires_at - issued_at > MAX_RUN_AUTHORIZATION_TTL:
            raise StopNeedsHuman("run_authorization_ttl_exceeded")
        now = _trusted_utc_now()
        if issued_at > now:
            raise StopNeedsHuman("run_authorization_not_yet_valid")
        if now >= expires_at:
            raise StopNeedsHuman("run_authorization_expired")
        if data["task_contract_fingerprint"] != contract_fingerprint:
            raise StopNeedsHuman("run_authorization_contract_mismatch")
        return data, fingerprint(data)

    def _validate_run_authorization(self, contract_fingerprint: str, state: Mapping[str, Any] | None,
                                    operation: str, authorization_id: str | None = None) -> tuple[dict[str, Any], str]:
        if operation not in RUN_AUTHORIZATION_OPERATIONS:
            raise StopNeedsHuman("run_authorization_operation_denied")
        if state is None:
            if authorization_id is None:
                raise StopNeedsHuman("run_authorization_missing")
            authorization, current = self._read_authorization(authorization_id, contract_fingerprint)
        else:
            required = ("run_authorization_id", "run_authorization_fingerprint", "run_status")
            if any(field not in state for field in required):
                raise StopNeedsHuman("run_authorization_state_missing")
            authorization_id = state.get("run_authorization_id")
            stored = state.get("run_authorization_fingerprint")
            status = state.get("run_status")
            if not isinstance(authorization_id, str) or not isinstance(stored, str) or not isinstance(status, str):
                raise StopNeedsHuman("run_authorization_state_missing")
            authorization, current = self._read_authorization(authorization_id, contract_fingerprint)
            if current != stored:
                raise StopNeedsHuman("run_authorization_fingerprint_divergent")
            if status == "READY":
                raise StopNeedsHuman("run_replay_after_ready")
            if status == "STOPPED":
                raise StopNeedsHuman("run_replay_after_stop")
            if status != "ACTIVE":
                raise StopNeedsHuman("run_not_active")
        if authorization.get("lifecycle_id") != self.lifecycle_id:
            raise StopNeedsHuman("run_authorization_lifecycle_mismatch")
        if operation not in authorization["allowed_operations"]:
            raise StopNeedsHuman("run_authorization_operation_denied")
        return authorization, current

    def _state_path(self) -> Path:
        return self.state_root / self.lifecycle_id / "state.json"

    @contextmanager
    def _publish_reservation(self):
        directory = self._state_path().parent
        lock_path = directory / "publish.lock"
        self._safe_existing(self.state_root)
        if directory.is_symlink() or not directory.is_dir() or stat.S_IMODE(directory.stat().st_mode) & 0o077:
            raise StopNeedsHuman("state_directory_unsafe")
        descriptor: int | None = None
        try:
            descriptor = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
            os.fchmod(descriptor, 0o600)
            os.fsync(descriptor)
        except FileExistsError as exc:
            raise StopNeedsHuman("publish_reservation_locked") from exc
        except OSError as exc:
            raise StopNeedsHuman("publish_reservation_rejected") from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
        try:
            yield
        finally:
            try:
                lock_stat = os.lstat(lock_path)
                if not stat.S_ISREG(lock_stat.st_mode) or stat.S_IMODE(lock_stat.st_mode) & 0o077:
                    raise OSError
                os.unlink(lock_path)
            except OSError as exc:
                raise StopNeedsHuman("publish_reservation_cleanup_failed") from exc

    def _write_state(self, state: dict[str, Any], *, exclusive: bool = False) -> None:
        directory = self._state_path().parent
        self._safe_existing(self.state_root)
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if directory.is_symlink() or stat.S_IMODE(directory.stat().st_mode) & 0o077:
            raise StopNeedsHuman("state_directory_unsafe")
        target = self._state_path()
        if target.is_symlink():
            raise StopNeedsHuman("state_symlink_rejected")
        payload = json.dumps(state, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if exclusive:
            try:
                descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
            except FileExistsError as exc:
                raise StopNeedsHuman("lifecycle_already_locked") from exc
            try:
                os.fchmod(descriptor, 0o600)
                os.write(descriptor, payload)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            return
        descriptor: int | None = None
        temporary_path: str | None = None
        try:
            descriptor, temporary_path = tempfile.mkstemp(prefix=".state-", dir=directory)
            os.fchmod(descriptor, 0o600)
            os.write(descriptor, payload)
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = None
            if target.is_symlink():
                raise StopNeedsHuman("state_symlink_rejected")
            os.replace(temporary_path, target)
            temporary_path = None
            directory_descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        except (OSError, StopNeedsHuman) as exc:
            if isinstance(exc, StopNeedsHuman):
                raise
            raise StopNeedsHuman("state_write_rejected") from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if temporary_path is not None:
                try:
                    os.unlink(temporary_path)
                except OSError:
                    pass

    def _state(self) -> dict[str, Any]:
        target = self._state_path()
        if target.is_symlink() or not target.is_file() or stat.S_IMODE(target.stat().st_mode) & 0o077:
            raise StopNeedsHuman("state_unavailable")
        try:
            value = json.loads(self._read_regular_text(target))
        except (StopNeedsHuman, json.JSONDecodeError) as exc:
            raise StopNeedsHuman("state_unavailable") from exc
        if not isinstance(value, dict):
            raise StopNeedsHuman("state_unavailable")
        return normalize_p5_state(value)

    def _guard(self, operation: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
        contract, current = self._contract()
        state = self._state()
        if state.get("fingerprint") != current or state.get("lifecycle_id") != self.lifecycle_id:
            raise StopNeedsHuman("contract_fingerprint_divergent")
        if operation is not None:
            self._validate_run_authorization(current, state, operation)
        return contract, state

    def _git(self, *arguments: str) -> str:
        return self.runner(["git", *arguments], self.root)

    def _changed_paths(self) -> list[str]:
        # Include staged, unstaged, and untracked material.  A diff against HEAD
        # alone misses untracked files and would let a control-plane change slip
        # past the local allowlist before publication.
        output = self._git("status", "--porcelain=v1", "--untracked-files=all")
        paths: list[str] = []
        for line in output.splitlines():
            if len(line) < 4:
                raise StopNeedsHuman("git_status_rejected")
            path = line[3:]
            # Rename/copy porcelain uses an additional source path.  Reject it
            # rather than parsing an ambiguous mutation in v1.
            if " -> " in path:
                raise StopNeedsHuman("git_status_rejected")
            paths.append(path)
        return paths

    @staticmethod
    def _denied(path: str) -> bool:
        return any(fnmatch.fnmatchcase(path, pattern) for pattern in DENIED_PATHS)

    def _validate_path(self, path: str, contract: Mapping[str, Any], failure_code: str) -> None:
        local = self.root / path
        if (not _safe_relative(path) or self._denied(path) or local.is_symlink()
                or not any(fnmatch.fnmatchcase(path, allowed) for allowed in contract["allowed_paths"])):
            raise StopNeedsHuman(failure_code)

    def _validate_committed_tree_mode(self, head: str, path: str) -> None:
        entry = self._git("ls-tree", "-z", head, "--", path).rstrip("\0")
        try:
            metadata, returned_path = entry.split("\t", 1)
            mode, object_type, object_id = metadata.split(" ")
        except ValueError as exc:
            raise StopNeedsHuman("committed_path_rejected") from exc
        if (returned_path != path or mode not in {"100644", "100755"}
                or object_type != "blob" or not SHA_RE.fullmatch(object_id)):
            raise StopNeedsHuman("committed_path_rejected")

    def _validate_committed_paths(self, contract: Mapping[str, Any], base: Any, head: str) -> None:
        if not isinstance(base, str) or not SHA_RE.fullmatch(base):
            raise StopNeedsHuman("published_head_missing")
        # A correction must extend the previously validated publication; rewrites
        # would make the path range ambiguous and are rejected before any push.
        self._git("merge-base", "--is-ancestor", base, head)
        output = self._git("diff", "--name-status", "-z", "--find-renames=100%", "--find-copies=100%", "--find-copies-harder", base, head)
        records = output.split("\0")
        if records[-1] != "":
            raise StopNeedsHuman("committed_path_rejected")
        index = 0
        while index < len(records) - 1:
            status = records[index]
            index += 1
            if status not in {"A", "M"} or index >= len(records) - 1:
                # v1 allows only regular-file additions and modifications.
                # Rename, copy, delete, type-change, merge-unmerged, and any
                # unfamiliar status remain fail-closed.
                raise StopNeedsHuman("committed_path_rejected")
            path = records[index]
            self._validate_path(path, contract, "committed_path_rejected")
            self._validate_committed_tree_mode(head, path)
            index += 1

    def _validate_checkout(self, contract: Mapping[str, Any]) -> str:
        if self._git("symbolic-ref", "--short", "HEAD") != contract["branch"]:
            raise StopNeedsHuman("local_branch_rejected")
        if self._git("remote", "get-url", "origin") != ORIGIN_URL:
            raise StopNeedsHuman("origin_rejected")
        head = self._git("rev-parse", "HEAD")
        if not SHA_RE.fullmatch(head):
            raise StopNeedsHuman("local_head_rejected")
        for changed in self._changed_paths():
            if not _safe_relative(changed) or self._denied(changed):
                raise StopNeedsHuman("changed_path_rejected")
            local = self.root / changed
            if local.is_symlink() or not any(fnmatch.fnmatchcase(changed, allowed) for allowed in contract["allowed_paths"]):
                raise StopNeedsHuman("changed_path_rejected")
        return head

    def _api(self, method: str, path: str, payload: Mapping[str, Any] | None = None) -> Any:
        if self.request is None or not path.startswith(f"/repos/{REPOSITORY}/"):
            raise StopNeedsHuman("api_unavailable")
        return _parse_response(self.request(method, path, payload))

    def _correction_count(self, contract: Mapping[str, Any], state: Mapping[str, Any]) -> int:
        count = state.get("corrections")
        maximum = contract.get("max_corrections")
        if type(count) is not int or type(maximum) is not int or count < 0 or count > maximum:
            raise StopNeedsHuman("correction_state_rejected")
        return count

    def _validate_remote_head(self, contract: Mapping[str, Any], sha: str) -> None:
        ref = f"refs/heads/{contract['branch']}"
        remote = self._git("ls-remote", "origin", ref).split()
        if len(remote) != 2 or remote[0] != sha or remote[1] != ref:
            raise StopNeedsHuman("remote_head_drift")

    def _validate_remote_before_publish(self, contract: Mapping[str, Any], state: Mapping[str, Any], published_once: bool) -> None:
        """Fail closed on a pre-existing first ref or later remote drift."""
        ref = f"refs/heads/{contract['branch']}"
        remote = self._git("ls-remote", "origin", ref).split()
        if not published_once:
            if remote:
                raise StopNeedsHuman("unexpected_remote_branch")
            return
        previous_head = state.get("head_sha")
        if len(remote) != 2 or remote[0] != previous_head or remote[1] != ref:
            raise StopNeedsHuman("remote_head_drift")

    def _validate_pr(self, pr: Mapping[str, Any], contract: Mapping[str, Any], sha: str) -> None:
        if not isinstance(pr, Mapping):
            raise StopNeedsHuman("pr_drift_rejected")
        head, base = pr.get("head"), pr.get("base")
        head_repository = head.get("repo") if isinstance(head, Mapping) else None
        base_repository = base.get("repo") if isinstance(base, Mapping) else None
        if (type(pr.get("number")) is not int or pr["number"] <= 0
                or pr.get("state") != "open" or pr.get("merged") is True
                or not isinstance(head, Mapping) or not isinstance(base, Mapping)
                or not isinstance(head_repository, Mapping) or not isinstance(base_repository, Mapping)
                or head.get("ref") != contract["branch"] or head.get("sha") != sha or head_repository.get("full_name") != REPOSITORY
                or base.get("ref") != "dev" or base_repository.get("full_name") != REPOSITORY):
            raise StopNeedsHuman("pr_drift_rejected")

    def _validate_correction_pr(self, contract: Mapping[str, Any], state: Mapping[str, Any], published_head: str) -> None:
        """Read exactly the full same-head collection and the stored PR before correction push."""
        number = state.get("pr_number")
        if type(number) is not int or number <= 0:
            raise StopNeedsHuman("pr_number_rejected")
        path = f"/repos/{REPOSITORY}/pulls?state=all&head=mide-lim:{contract['branch']}"
        collection = self._api("GET", path)
        if (not isinstance(collection, list) or len(collection) != 1 or not isinstance(collection[0], Mapping)
                or collection[0].get("number") != number):
            raise StopNeedsHuman("pr_count_rejected")
        pr = self._api("GET", f"/repos/{REPOSITORY}/pulls/{number}")
        marker = f"B4.2-Contract-Fingerprint: {state['fingerprint']}"
        if not isinstance(pr, Mapping) or pr.get("number") != number or marker not in str(pr.get("body", "")):
            raise StopNeedsHuman("pr_fingerprint_rejected")
        self._validate_pr(pr, contract, published_head)

    def preflight(self, authorization_id: str | None = None) -> dict[str, str]:
        contract, contract_fingerprint = self._contract()
        authorization, authorization_fingerprint = self._validate_run_authorization(
            contract_fingerprint, None, "preflight", authorization_id,
        )
        head = self._validate_checkout(contract)
        if head != contract["head_sha_initial"]:
            raise StopNeedsHuman("initial_head_mismatch")
        self._write_state({
            "lifecycle_id": self.lifecycle_id,
            "fingerprint": contract_fingerprint,
            "run_authorization_id": authorization["authorization_id"],
            "run_authorization_fingerprint": authorization_fingerprint,
            "run_status": "ACTIVE",
            "head_sha": head,
            "ci_sha": None,
            "ci_failure": None,
            "ci_jobs": None,
            "workflow_run_id": None,
            "observation_generation": 0,
            "pending_correction_sha": None,
            "pending_publish_attempted": False,
            "corrections": 0,
            "published_once": False,
        }, exclusive=True)
        return {"state": "PREFLIGHT_OK", "head_sha": head, "fingerprint": contract_fingerprint}

    def _require_clean_checkout(self) -> None:
        if self._changed_paths():
            raise StopNeedsHuman("worktree_not_clean")

    @staticmethod
    def _self_correctable_ci_failure(value: Any, contract: Mapping[str, Any], head: str, pr_number: Any) -> bool:
        if not isinstance(value, Mapping) or set(value) != {"head_sha", "pr_number", "workflow_run_id", "jobs"}:
            return False
        jobs = value.get("jobs")
        expected = contract.get("expected_ci_jobs")
        return (value.get("head_sha") == head and value.get("pr_number") == pr_number
                and type(value.get("workflow_run_id")) is int and value["workflow_run_id"] > 0
                and isinstance(jobs, Mapping) and isinstance(expected, list) and set(jobs) == set(expected)
                and jobs == {"Repository validation": "failure", "Enricher tests": "success", "Web tests": "success"})

    def authorize_correction(self) -> dict[str, Any]:
        """Local-only reproduction gate; it never contacts GitHub or a remote."""
        contract, state = self._guard("authorize-correction")
        self._require_clean_checkout()
        head = self._validate_checkout(contract)
        if (state.get("published_once") is not True or state.get("head_sha") != head or state.get("ci_sha") is not None
                or state.get("pending_correction_sha") is not None or state.get("pending_publish_attempted") is not False
                or self._correction_count(contract, state) >= contract["max_corrections"]
                or not self._self_correctable_ci_failure(state.get("ci_failure"), contract, head, state.get("pr_number"))):
            raise StopNeedsHuman("correction_not_authorized")
        profile = repository_validation_json_v1(self.root, contract["allowed_paths"])
        if (profile.get("result") != "fail" or profile.get("failure_code") is not None
                or not profile_invalid_paths_allowed(profile, self.root, contract["allowed_paths"])):
            raise StopNeedsHuman("correction_not_reproduced")
        return {"profile_id": profile["profile_id"], "result": profile["result"], "invalid_files": profile["invalid_files"]}

    def _repository_validation_json_v1_for_commit(self, sha: str, allowed_paths: list[str]) -> dict[str, Any]:
        """Capability-owned committed-tree validation seam for finalization."""
        return repository_validation_json_v1_for_commit(self.root, sha, allowed_paths)

    def finalize_correction(self) -> dict[str, str]:
        """Locally bind one validated descendant correction SHA; no network calls."""
        contract, expected_state = self._guard("finalize-correction")
        self._require_clean_checkout()
        head = self._validate_checkout(contract)
        base = expected_state.get("head_sha")
        if (not isinstance(base, str) or not SHA_RE.fullmatch(base) or head == base
                or expected_state.get("ci_sha") is not None or expected_state.get("pending_correction_sha") is not None
                or expected_state.get("pending_publish_attempted") is not False
                or self._correction_count(contract, expected_state) >= contract["max_corrections"]
                or not self._self_correctable_ci_failure(expected_state.get("ci_failure"), contract, base, expected_state.get("pr_number"))):
            raise StopNeedsHuman("correction_not_authorized")
        if self._git("rev-parse", "HEAD^") != base or self._git("rev-list", "--count", f"{base}..{head}") != "1":
            raise StopNeedsHuman("correction_commit_count_rejected")
        if self._git("log", "-1", "--format=%B", head) != CORRECTION_COMMIT_MESSAGE:
            raise StopNeedsHuman("correction_commit_message_rejected")
        self._validate_committed_paths(contract, base, head)
        self._git("diff", "--check", base, head)
        s1_profile = self._repository_validation_json_v1_for_commit(base, contract["allowed_paths"])
        if (s1_profile.get("result") != "fail" or s1_profile.get("failure_code") is not None
                or not profile_invalid_paths_allowed_for_commit(s1_profile, contract["allowed_paths"])):
            raise StopNeedsHuman("correction_not_reproduced")
        s2_profile = self._repository_validation_json_v1_for_commit(head, contract["allowed_paths"])
        if s2_profile.get("result") != "pass":
            raise StopNeedsHuman("correction_validation_failed")
        _, current_state = self._guard()
        if current_state != expected_state:
            raise StopNeedsHuman("state_changed_before_commit")
        current_head = self._validate_checkout(contract)
        self._require_clean_checkout()
        if current_head != head:
            raise StopNeedsHuman("correction_head_changed")
        current_state["pending_correction_sha"] = head
        current_state["pending_publish_attempted"] = False
        self._write_state(current_state)
        return {"state": "CORRECTION_FINALIZED", "head_sha": head}

    def publish_head(self) -> dict[str, str]:
        _require_live_operations_enabled()
        with self._publish_reservation():
            return self._publish_head_locked()

    def _publish_head_locked(self, *, state_writer: Callable[[dict[str, Any]], None] | None = None) -> dict[str, str]:
        contract, state = self._guard("publish-head")
        head = self._validate_checkout(contract)
        previous_head = state.get("head_sha")
        corrections = self._correction_count(contract, state)
        published_once = state.get("published_once")
        if type(published_once) is not bool:
            raise StopNeedsHuman("publication_state_rejected")
        pending = state.get("pending_correction_sha")
        if published_once and head != previous_head and pending is None:
            raise StopNeedsHuman("correction_finalization_required")
        self._validate_committed_paths(contract, previous_head, head)
        correction_mode = pending is not None
        if correction_mode:
            if (not isinstance(pending, str) or not SHA_RE.fullmatch(pending) or pending != head
                    or not isinstance(previous_head, str) or not SHA_RE.fullmatch(previous_head)
                    or state.get("pending_publish_attempted") is not False or not published_once
                    or corrections >= contract["max_corrections"]):
                raise StopNeedsHuman("correction_publish_rejected")
            self._require_clean_checkout()
            self._validate_correction_pr(contract, state, previous_head)
        self._validate_remote_before_publish(contract, state, published_once)

        if head != previous_head and published_once:
            # Any changed post-initial publication was already required to be
            # finalised above, so the one-shot latch and budget apply only here.
            state["corrections"] = corrections + 1
            state["pending_publish_attempted"] = True
            self._write_state(state)
        elif correction_mode:
            raise StopNeedsHuman("correction_publish_rejected")
        # Fresh contract and committed-range verification immediately precede the
        # only Git mutation. Correction mode repeats complete-clean enforcement
        # after latching, preventing an uncommitted local mutation before push.
        self._guard("publish-head")
        if correction_mode:
            self._require_clean_checkout()
        ref = f"refs/heads/{contract['branch']}"
        self._git("push", "origin", f"HEAD:{ref}")
        remote = self._git("ls-remote", "origin", ref).split()
        if len(remote) != 2 or remote[0] != head or remote[1] != ref:
            raise StopNeedsHuman("remote_head_mismatch")
        state.update({"head_sha": head, "ci_sha": None, "published_once": True})
        if correction_mode:
            state.update({"ci_failure": None, "pending_correction_sha": None, "pending_publish_attempted": False})
        (self._write_state if state_writer is None else state_writer)(state)
        return {"state": "PUBLISHED", "head_sha": head}

    def _commit_deferred_initial_publish_state(self, expected_state: Mapping[str, Any], expected_head: str,
                                               deferred_state: Mapping[str, Any]) -> None:
        """Persist initial P2 success only after token teardown and revalidation."""
        contract, current = self._guard("publish-head")
        if current != expected_state:
            raise StopNeedsHuman("state_changed_before_commit")
        if self._validate_checkout(contract) != expected_head:
            raise StopNeedsHuman("publish_state_commit_rejected")
        self._validate_remote_head(contract, expected_head)
        expected = dict(current)
        expected.update({"head_sha": expected_head, "ci_sha": None, "published_once": True})
        if dict(deferred_state) != expected:
            raise StopNeedsHuman("publish_state_commit_rejected")
        self._write_state(expected)

    def _commit_deferred_correction_publish(self, expected_latched: Mapping[str, Any], expected_head: str,
                                            deferred_state: Mapping[str, Any]) -> None:
        """Persist correction publish success only after the adapter tore down its token."""
        contract, current = self._guard("publish-head")
        if current != expected_latched or current.get("pending_correction_sha") != expected_head or current.get("pending_publish_attempted") is not True:
            raise StopNeedsHuman("state_changed_before_commit")
        if self._validate_checkout(contract) != expected_head:
            raise StopNeedsHuman("correction_head_changed")
        self._require_clean_checkout()
        expected = dict(current)
        expected.update({"head_sha": expected_head, "ci_sha": None, "ci_failure": None,
                         "pending_correction_sha": None, "pending_publish_attempted": False,
                         "published_once": True})
        if dict(deferred_state) != expected:
            raise StopNeedsHuman("publish_state_commit_rejected")
        self._write_state(expected)

    def ensure_pr(self) -> dict[str, Any]:
        _require_live_operations_enabled()
        with self._publish_reservation():
            return self._ensure_pr_locked()

    def _ensure_pr_locked(self, *, state_writer: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
        """Perform only the reviewed contract-bound ensure-pr transition.

        A closed authenticated adapter may supply a deferred state writer so the
        PR number is persisted only after its independent token teardown has
        completed.  Public lifecycle callers use the normal atomic writer.
        """
        contract, state = self._guard("ensure-pr")
        sha = self._validate_checkout(contract)
        if state.get("published_once") is not True:
            raise StopNeedsHuman("publication_required")
        if state.get("head_sha") != sha:
            raise StopNeedsHuman("publish_required")
        # Read the exact branch ref immediately before either reusing an existing
        # PR or creating one.  API head metadata alone is not a ref readback.
        self._validate_remote_head(contract, sha)
        marker = f"B4.2-Contract-Fingerprint: {state['fingerprint']}"
        # Every ensure-pr execution searches the complete same-head collection.
        # Do not add a base filter: a same-head PR to another base is still a
        # conflicting PR and must block this lifecycle permanently.
        path = f"/repos/{REPOSITORY}/pulls?state=all&head=mide-lim:{contract['branch']}"
        prs = self._api("GET", path)
        self._validate_remote_head(contract, sha)
        if not isinstance(prs, list):
            raise StopNeedsHuman("pr_count_rejected")

        stored_number = state.get("pr_number")
        if stored_number is not None:
            if type(stored_number) is not int or stored_number <= 0:
                raise StopNeedsHuman("pr_number_rejected")
            if len(prs) != 1:
                raise StopNeedsHuman("pr_count_rejected")
            listed = prs[0]
            if not isinstance(listed, Mapping) or listed.get("number") != stored_number:
                raise StopNeedsHuman("pr_drift_rejected")
            if listed.get("state") == "closed" or listed.get("merged") is True:
                raise StopNeedsHuman("pr_terminal_state")
            if marker not in str(listed.get("body", "")):
                raise StopNeedsHuman("pr_fingerprint_rejected")
            self._validate_pr(listed, contract, sha)
            pr = self._api("GET", f"/repos/{REPOSITORY}/pulls/{stored_number}")
            self._validate_remote_head(contract, sha)
            if not isinstance(pr, Mapping) or pr.get("number") != stored_number:
                raise StopNeedsHuman("pr_drift_rejected")
        elif len(prs) > 1:
            raise StopNeedsHuman("pr_count_rejected")
        elif prs:
            pr = prs[0]
        else:
            # The adapter independently permits this one POST only while the
            # immediately preceding same-head collection is known to be empty.
            self._guard("ensure-pr")
            self._validate_remote_head(contract, sha)
            pr = self._api("POST", f"/repos/{REPOSITORY}/pulls", {"title": contract["pr_title"], "head": contract["branch"], "base": "dev", "body": f"{contract['pr_body']}\n\n{marker}"})
            if not isinstance(pr, Mapping):
                raise StopNeedsHuman("pr_drift_rejected")
            self._validate_pr(pr, contract, sha)
            self._validate_remote_head(contract, sha)
            # Search again after POST.  The transition cannot continue unless
            # the server now has exactly the PR returned by this create.
            post_create_prs = self._api("GET", path)
            self._validate_remote_head(contract, sha)
            if (not isinstance(post_create_prs, list) or len(post_create_prs) != 1
                    or not isinstance(post_create_prs[0], Mapping)
                    or post_create_prs[0].get("number") != pr.get("number")):
                raise StopNeedsHuman("pr_count_rejected")
            pr = post_create_prs[0]

        if not isinstance(pr, Mapping):
            raise StopNeedsHuman("pr_drift_rejected")
        if pr.get("state") == "closed" or pr.get("merged") is True:
            raise StopNeedsHuman("pr_terminal_state")
        if marker not in str(pr.get("body", "")):
            raise StopNeedsHuman("pr_fingerprint_rejected")
        self._validate_pr(pr, contract, sha)
        # An API response cannot commit state until its exact branch ref is read
        # back again.  This closes the API-to-state time-of-check/use window.
        self._validate_remote_head(contract, sha)
        if type(pr.get("number")) is not int or pr["number"] <= 0:
            raise StopNeedsHuman("pr_number_rejected")
        state["pr_number"] = pr["number"]
        (self._write_state if state_writer is None else state_writer)(state)
        return {"state": "PR_OPEN", "pr_number": pr["number"], "head_sha": sha}

    def _commit_deferred_pr_state(self, expected_state: Mapping[str, Any], expected_fingerprint: str,
                                  expected_head: str, deferred_state: dict[str, Any]) -> None:
        """Compare-and-set a P3 result after external token teardown.

        The authenticated adapter holds the shared publish reservation while
        calling this method.  The method nevertheless reloads all mutable
        inputs so an out-of-band state, contract, local-HEAD, or remote-ref
        change cannot overwrite a newer lifecycle state.
        """
        contract, current_state = self._guard("ensure-pr")
        if (current_state != expected_state
                or current_state.get("fingerprint") != expected_fingerprint):
            raise StopNeedsHuman("state_changed_before_commit")
        current_head = self._validate_checkout(contract)
        if (current_head != expected_head or current_state.get("published_once") is not True
                or current_state.get("head_sha") != current_head):
            raise StopNeedsHuman("publish_required")
        self._validate_remote_head(contract, current_head)
        self._write_state(deferred_state)

    def _ci_candidates(self, runs: Any, sha: str, number: int) -> list[Mapping[str, Any]]:
        if not isinstance(runs, Mapping) or not isinstance(runs.get("workflow_runs"), list):
            raise StopNeedsHuman("workflow_run_ambiguous")
        return [
            run for run in runs["workflow_runs"]
            if isinstance(run, Mapping) and run.get("event") == "pull_request" and run.get("head_sha") == sha
            and isinstance(run.get("pull_requests"), list)
            and any(isinstance(entry, Mapping) and entry.get("number") == number for entry in run["pull_requests"])
        ]

    def _validate_ci_jobs(self, jobs: Any, contract: Mapping[str, Any]) -> dict[str, str]:
        if not isinstance(jobs, Mapping) or not isinstance(jobs.get("jobs"), list):
            raise StopNeedsHuman("ci_not_green_for_head")
        found: dict[str, str] = {}
        for job in jobs["jobs"]:
            if not isinstance(job, Mapping) or not isinstance(job.get("name"), str) or job["name"] in found:
                raise StopNeedsHuman("ci_not_green_for_head")
            conclusion = job.get("conclusion")
            if job.get("status") != "completed" or conclusion not in {"success", "failure"}:
                raise StopNeedsHuman("ci_not_green_for_head")
            found[job["name"]] = conclusion
        if set(found) != set(contract["expected_ci_jobs"]):
            raise StopNeedsHuman("ci_not_green_for_head")
        return found

    def _observe_ci_locked(self, *, state_writer: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
        """Observe only the exact PR head and defer any CI evidence state write."""
        contract, state = self._guard("observe-ci")
        sha = self._validate_checkout(contract)
        number = state.get("pr_number")
        if (state.get("published_once") is not True or type(number) is not int or number <= 0
                or state.get("head_sha") != sha):
            raise StopNeedsHuman("pr_or_head_missing")
        if state.get("pending_correction_sha") is not None:
            raise StopNeedsHuman("correction_pending")
        self._validate_remote_head(contract, sha)
        pr = self._api("GET", f"/repos/{REPOSITORY}/pulls/{number}")
        if not isinstance(pr, Mapping) or pr.get("number") != number:
            raise StopNeedsHuman("pr_drift_rejected")
        self._validate_pr(pr, contract, sha)
        self._validate_remote_head(contract, sha)
        runs = self._api("GET", f"/repos/{REPOSITORY}/actions/runs?event=pull_request&head_sha={sha}")
        candidates = self._ci_candidates(runs, sha, number)
        if len(candidates) != 1:
            raise StopNeedsHuman("workflow_run_ambiguous")
        run = candidates[0]
        run_id = run.get("id")
        if (type(run_id) is not int or run_id <= 0 or run.get("status") != "completed"
                or run.get("conclusion") not in {"success", "failure"}):
            raise StopNeedsHuman("ci_not_green_for_head")
        self._validate_remote_head(contract, sha)
        jobs = self._api("GET", f"/repos/{REPOSITORY}/actions/runs/{run_id}/jobs")
        found = self._validate_ci_jobs(jobs, contract)
        is_green = all(found[name] == "success" for name in contract["expected_ci_jobs"])
        if (run.get("conclusion") == "success") != is_green:
            raise StopNeedsHuman("ci_not_green_for_head")
        self._validate_remote_head(contract, sha)
        deferred = dict(state)
        if is_green:
            deferred["ci_sha"] = sha
            deferred["ci_failure"] = None
            deferred["ci_jobs"] = {name: found[name] for name in contract["expected_ci_jobs"]}
            deferred["workflow_run_id"] = run_id
            deferred["observation_generation"] = state.get("observation_generation", 0) + 1
            result_state = "CI_GREEN_FOR_HEAD"
        else:
            deferred["ci_sha"] = None
            deferred["ci_failure"] = {"head_sha": sha, "pr_number": number, "workflow_run_id": run_id,
                                      "jobs": {name: found[name] for name in contract["expected_ci_jobs"]}}
            result_state = "CI_FAILED_FOR_HEAD"
        (self._write_state if state_writer is None else state_writer)(deferred)
        return {"state": result_state, "head_sha": sha, "workflow_run_id": run_id,
                "jobs": {name: found[name] for name in contract["expected_ci_jobs"]}}

    def _commit_deferred_ci_state(self, expected_state: Mapping[str, Any], expected_fingerprint: str,
                                  expected_head: str, deferred_state: Mapping[str, Any]) -> None:
        """CAS a P4 observation only after external token teardown succeeded."""
        contract, current_state = self._guard("observe-ci")
        if (current_state != expected_state
                or current_state.get("fingerprint") != expected_fingerprint):
            raise StopNeedsHuman("state_changed_before_commit")
        current_head = self._validate_checkout(contract)
        if (current_head != expected_head or current_state.get("published_once") is not True
                or current_state.get("head_sha") != current_head
                or type(current_state.get("pr_number")) is not int or current_state["pr_number"] <= 0):
            raise StopNeedsHuman("publish_required")
        self._validate_remote_head(contract, current_head)
        expected_deferred = dict(current_state)
        if dict(deferred_state).get("ci_sha") == current_head and dict(deferred_state).get("ci_failure") is None:
            jobs = dict(deferred_state).get("ci_jobs")
            run_id = dict(deferred_state).get("workflow_run_id")
            generation = dict(deferred_state).get("observation_generation")
            if (not isinstance(jobs, Mapping) or set(jobs) != set(contract["expected_ci_jobs"])
                    or any(jobs.get(name) != "success" for name in contract["expected_ci_jobs"])
                    or type(run_id) is not int or run_id <= 0 or type(generation) is not int
                    or generation != current_state.get("observation_generation", 0) + 1):
                raise StopNeedsHuman("ci_state_commit_rejected")
            expected_deferred["ci_sha"] = current_head
            expected_deferred["ci_failure"] = None
            expected_deferred["ci_jobs"] = {name: jobs[name] for name in contract["expected_ci_jobs"]}
            expected_deferred["workflow_run_id"] = run_id
            expected_deferred["observation_generation"] = generation
        elif (dict(deferred_state).get("ci_sha") is None
                and isinstance(dict(deferred_state).get("ci_failure"), Mapping)):
            evidence = dict(deferred_state)["ci_failure"]
            jobs = evidence.get("jobs") if isinstance(evidence, Mapping) else None
            if (not isinstance(evidence, Mapping) or evidence.get("head_sha") != current_head
                    or evidence.get("pr_number") != current_state.get("pr_number")
                    or type(evidence.get("workflow_run_id")) is not int
                    or not isinstance(jobs, Mapping) or set(jobs) != set(contract["expected_ci_jobs"])
                    or any(value not in {"success", "failure"} for value in jobs.values())
                    or all(value == "success" for value in jobs.values())):
                raise StopNeedsHuman("ci_state_commit_rejected")
            expected_deferred["ci_sha"] = None
            expected_deferred["ci_failure"] = {"head_sha": current_head, "pr_number": current_state["pr_number"],
                                                "workflow_run_id": evidence["workflow_run_id"],
                                                "jobs": {name: jobs[name] for name in contract["expected_ci_jobs"]}}
        else:
            raise StopNeedsHuman("ci_state_commit_rejected")
        if dict(deferred_state) != expected_deferred:
            raise StopNeedsHuman("ci_state_commit_rejected")
        self._write_state(expected_deferred)

    def observe_ci(self) -> dict[str, Any]:
        _require_live_operations_enabled()
        with self._publish_reservation():
            return self._observe_ci_locked()

    def refresh_from_dev(self) -> dict[str, str]:
        _require_live_operations_enabled()
        contract, state = self._guard()
        if not contract["allow_safe_refresh"]:
            raise StopNeedsHuman("safe_refresh_not_allowed")
        self._validate_checkout(contract)
        self._guard()
        self._git("fetch", "origin", "dev")
        self._guard()
        self._git("merge", "--no-ff", "--no-edit", "origin/dev")
        head = self._validate_checkout(contract)
        # Keep head_sha as the last published ref.  The merged local commit must
        # remain in the next publish range for committed-path enforcement.
        state["ci_sha"] = None
        self._write_state(state)
        return {"state": "REFRESHED", "head_sha": head}

    def report_ready(self) -> dict[str, Any]:
        """Seal bounded P4 snapshot evidence; this method has no network surface."""
        contract, state = self._guard("report-ready")
        sha = self._validate_checkout(contract)
        corrections = self._correction_count(contract, state)
        jobs = state.get("ci_jobs")
        if (state.get("published_once") is not True or state.get("ci_sha") != sha or state.get("ci_failure") is not None
                or type(state.get("pr_number")) is not int or state["pr_number"] <= 0
                or type(state.get("workflow_run_id")) is not int or state["workflow_run_id"] <= 0
                or type(state.get("observation_generation")) is not int or state["observation_generation"] < 1
                or state.get("pending_correction_sha") is not None or state.get("pending_publish_attempted") is not False
                or not isinstance(jobs, Mapping) or set(jobs) != set(contract["expected_ci_jobs"])
                or any(jobs.get(name) != "success" for name in contract["expected_ci_jobs"])):
            raise StopNeedsHuman("ci_evidence_stale")
        self._require_clean_checkout()
        _, current = self._guard("report-ready")
        if current != state:
            raise StopNeedsHuman("state_changed_before_commit")
        state["run_status"] = "READY"
        self._write_state(state)
        return {"state": f"READY_FOR_HUMAN_MERGE_FOR_SHA={sha}", "lifecycle_id": self.lifecycle_id,
                "contract_fingerprint_prefix": state["fingerprint"][:12],
                "authorization_fingerprint_prefix": state["run_authorization_fingerprint"][:12],
                "pr_number": state["pr_number"], "branch": contract["branch"], "head_sha": sha,
                "workflow_run_id": state["workflow_run_id"],
                "jobs": {name: jobs[name] for name in contract["expected_ci_jobs"]},
                "corrections": corrections, "max_corrections": contract["max_corrections"],
                "merge_authority": "human_only"}


def sanitize_log(value: str) -> str:
    """Keep logs as inert, bounded data; callers must never execute this output."""
    return "".join(character if character >= " " or character in "\n\t" else "?" for character in value)[:2000]
