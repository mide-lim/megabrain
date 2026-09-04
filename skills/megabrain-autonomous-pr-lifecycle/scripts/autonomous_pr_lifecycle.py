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
CONTRACT_DIRECTORY = Path("contracts/b4.2")

PUBLIC_OPERATIONS = frozenset({"preflight", "publish-head", "ensure-pr", "observe-ci", "refresh-from-dev", "report-ready"})
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
LIFECYCLE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
BRANCH_RE = re.compile(r"^agent/[a-z0-9][a-z0-9._-]{0,62}$")

Runner = Callable[[list[str], Path], str]
Request = Callable[[str, str, Mapping[str, Any] | None], Any]


class StopNeedsHuman(RuntimeError):
    """Fail-closed terminal state; no caller should retry without a human gate."""


def canonical_json(value: Mapping[str, Any]) -> bytes:
    filtered = {key: value[key] for key in value if key != "fingerprint"}
    return json.dumps(filtered, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def fingerprint(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _safe_relative(value: str) -> bool:
    path = PurePosixPath(value)
    return bool(value) and not path.is_absolute() and ".." not in path.parts and "\\" not in value and "\x00" not in value


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
        self.contract_path = self.root / CONTRACT_DIRECTORY / f"{lifecycle_id}.json"
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

    def _contract(self) -> tuple[dict[str, Any], str]:
        self._safe_existing(self.contract_path.parent)
        if self.contract_path.is_symlink() or not self.contract_path.is_file():
            raise StopNeedsHuman("contract_path_rejected")
        try:
            data = json.loads(self._read_regular_text(self.contract_path))
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
        if not isinstance(data["expected_ci_jobs"], list) or not data["expected_ci_jobs"] or len(set(data["expected_ci_jobs"])) != len(data["expected_ci_jobs"]) or not all(isinstance(j, str) and j for j in data["expected_ci_jobs"]):
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
        return value

    def _guard(self) -> tuple[dict[str, Any], dict[str, Any]]:
        contract, current = self._contract()
        state = self._state()
        if state.get("fingerprint") != current or state.get("lifecycle_id") != self.lifecycle_id:
            raise StopNeedsHuman("contract_fingerprint_divergent")
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
            if status != "M" or index >= len(records) - 1:
                # Additions are rejected too: Git cannot reliably distinguish an
                # allowlisted new file from a modified copy in every history.
                # Rename, copy, delete, type-change, merge-unmerged, and any
                # unfamiliar status are all fail-closed in v1.
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

    def _validate_pr(self, pr: Mapping[str, Any], contract: Mapping[str, Any], sha: str) -> None:
        head, base = pr.get("head"), pr.get("base")
        if (not isinstance(pr, Mapping) or pr.get("state") != "open" or not isinstance(head, Mapping) or not isinstance(base, Mapping)
                or head.get("ref") != contract["branch"] or head.get("sha") != sha or head.get("repo", {}).get("full_name") != REPOSITORY
                or base.get("ref") != "dev" or base.get("repo", {}).get("full_name") != REPOSITORY):
            raise StopNeedsHuman("pr_drift_rejected")

    def preflight(self) -> dict[str, str]:
        contract, contract_fingerprint = self._contract()
        head = self._validate_checkout(contract)
        if head != contract["head_sha_initial"]:
            raise StopNeedsHuman("initial_head_mismatch")
        self._write_state({"lifecycle_id": self.lifecycle_id, "fingerprint": contract_fingerprint, "head_sha": head, "ci_sha": None, "corrections": 0}, exclusive=True)
        return {"state": "PREFLIGHT_OK", "head_sha": head, "fingerprint": contract_fingerprint}

    def publish_head(self) -> dict[str, str]:
        _require_live_operations_enabled()
        with self._publish_reservation():
            return self._publish_head_locked()

    def _publish_head_locked(self) -> dict[str, str]:
        contract, state = self._guard()
        head = self._validate_checkout(contract)
        previous_head = state.get("head_sha")
        self._validate_committed_paths(contract, previous_head, head)
        corrections = self._correction_count(contract, state)
        if head != previous_head:
            if corrections >= contract["max_corrections"]:
                raise StopNeedsHuman("correction_budget_exhausted")
            # Reserve the correction before a network mutation.  A failed push
            # consumes the approval budget rather than allowing silent retries.
            state["corrections"] = corrections + 1
            self._write_state(state)
        # Fresh contract and committed-range verification immediately precede the
        # only Git mutation.
        self._guard()
        ref = f"refs/heads/{contract['branch']}"
        self._git("push", "origin", f"HEAD:{ref}")
        remote = self._git("ls-remote", "origin", ref).split()
        if len(remote) < 2 or remote[0] != head or remote[1] != ref:
            raise StopNeedsHuman("remote_head_mismatch")
        state.update({"head_sha": head, "ci_sha": None})
        self._write_state(state)
        return {"state": "PUBLISHED", "head_sha": head}

    def ensure_pr(self) -> dict[str, Any]:
        _require_live_operations_enabled()
        contract, state = self._guard()
        sha = self._validate_checkout(contract)
        if state.get("head_sha") != sha:
            raise StopNeedsHuman("publish_required")
        # Read the exact branch ref immediately before either reusing an existing
        # PR or creating one.  API head metadata alone is not a ref readback.
        self._validate_remote_head(contract, sha)
        marker = f"B4.2-Contract-Fingerprint: {state['fingerprint']}"
        stored_number = state.get("pr_number")
        if stored_number is not None:
            if not isinstance(stored_number, int):
                raise StopNeedsHuman("pr_number_rejected")
            pr = self._api("GET", f"/repos/{REPOSITORY}/pulls/{stored_number}")
            self._validate_remote_head(contract, sha)
            if not isinstance(pr, Mapping):
                raise StopNeedsHuman("pr_drift_rejected")
            if pr.get("state") == "closed" or pr.get("merged") is True:
                raise StopNeedsHuman("pr_terminal_state")
            if marker not in str(pr.get("body", "")):
                raise StopNeedsHuman("pr_fingerprint_rejected")
            self._validate_pr(pr, contract, sha)
        else:
            # Deliberately do not filter base server-side: a same-head PR to any
            # other base is still a conflicting PR for this execution and must stop.
            path = f"/repos/{REPOSITORY}/pulls?state=all&head=mide-lim:{contract['branch']}"
            prs = self._api("GET", path)
            self._validate_remote_head(contract, sha)
            if not isinstance(prs, list) or len(prs) > 1:
                raise StopNeedsHuman("pr_count_rejected")
            if prs:
                pr = prs[0]
                if not isinstance(pr, Mapping):
                    raise StopNeedsHuman("pr_drift_rejected")
                if pr.get("state") == "closed" or pr.get("merged") is True:
                    raise StopNeedsHuman("pr_terminal_state")
                if marker not in str(pr.get("body", "")):
                    raise StopNeedsHuman("pr_fingerprint_rejected")
                self._validate_pr(pr, contract, sha)
            else:
                self._guard()
                self._validate_remote_head(contract, sha)
                pr = self._api("POST", f"/repos/{REPOSITORY}/pulls", {"title": contract["pr_title"], "head": contract["branch"], "base": "dev", "body": f"{contract['pr_body']}\n\n{marker}"})
                if not isinstance(pr, Mapping):
                    raise StopNeedsHuman("pr_drift_rejected")
                self._validate_pr(pr, contract, sha)
        if not isinstance(pr.get("number"), int):
            raise StopNeedsHuman("pr_number_rejected")
        state["pr_number"] = pr["number"]
        self._write_state(state)
        return {"state": "PR_OPEN", "pr_number": pr["number"], "head_sha": sha}

    def observe_ci(self) -> dict[str, Any]:
        _require_live_operations_enabled()
        contract, state = self._guard()
        sha = self._validate_checkout(contract)
        number = state.get("pr_number")
        if not isinstance(number, int) or state.get("head_sha") != sha:
            raise StopNeedsHuman("pr_or_head_missing")
        pr = self._api("GET", f"/repos/{REPOSITORY}/pulls/{number}")
        self._validate_pr(pr, contract, sha)
        runs = self._api("GET", f"/repos/{REPOSITORY}/actions/runs?event=pull_request&head_sha={sha}")
        candidates = [run for run in runs.get("workflow_runs", []) if isinstance(run, Mapping) and run.get("head_sha") == sha and isinstance(run.get("pull_requests"), list) and number in [entry.get("number") for entry in run["pull_requests"] if isinstance(entry, Mapping)]] if isinstance(runs, Mapping) else []
        if len(candidates) != 1:
            raise StopNeedsHuman("workflow_run_ambiguous")
        run = candidates[0]
        jobs = self._api("GET", f"/repos/{REPOSITORY}/actions/runs/{run.get('id')}/jobs")
        found = {job.get("name"): job.get("conclusion") for job in jobs.get("jobs", []) if isinstance(job, Mapping) and isinstance(job.get("name"), str)} if isinstance(jobs, Mapping) else {}
        if set(found) != set(contract["expected_ci_jobs"]) or any(found.get(name) != "success" for name in contract["expected_ci_jobs"]):
            raise StopNeedsHuman("ci_not_green_for_head")
        state["ci_sha"] = sha
        self._write_state(state)
        return {"state": "CI_GREEN", "head_sha": sha, "jobs": {name: found[name] for name in contract["expected_ci_jobs"]}}

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
        _require_live_operations_enabled()
        contract, state = self._guard()
        sha = self._validate_checkout(contract)
        if state.get("ci_sha") != sha or not isinstance(state.get("pr_number"), int):
            raise StopNeedsHuman("ci_evidence_stale")
        pr = self._api("GET", f"/repos/{REPOSITORY}/pulls/{state['pr_number']}")
        self._validate_pr(pr, contract, sha)
        evidence = self.observe_ci()
        return {"state": "READY", "pr_number": state["pr_number"], "head_sha": sha, "jobs": evidence["jobs"]}


def sanitize_log(value: str) -> str:
    """Keep logs as inert, bounded data; callers must never execute this output."""
    return "".join(character if character >= " " or character in "\n\t" else "?" for character in value)[:2000]
