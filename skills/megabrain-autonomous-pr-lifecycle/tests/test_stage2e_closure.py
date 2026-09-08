"""Stage 2E direct hermetic closure tests for R1 run authorization."""
from __future__ import annotations

import copy
import importlib.util
import json
import os
import stat
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent


def load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, SKILL / relative)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


L = load("b42_stage2e_lifecycle", "scripts/autonomous_pr_lifecycle.py")
P2 = load("b42_stage2e_p2", "scripts/authenticated_publish_head.py")
P3 = load("b42_stage2e_p3", "scripts/authenticated_ensure_pr.py")
P4 = load("b42_stage2e_p4", "scripts/authenticated_observe_ci.py")
SHA_A = "a" * 40
SHA_B = "b" * 40


def contract(lifecycle_id="life-1"):
    return {
        "version": "B4.2.1", "lifecycle_id": lifecycle_id, "status": "APPROVED",
        "repository": L.REPOSITORY, "origin_url": L.ORIGIN_URL,
        "branch": "agent/b4-2-stage2e", "base": "dev", "head_sha_initial": SHA_A,
        "allowed_paths": ["docs/EVIDENCE.md"],
        "expected_ci_jobs": ["Repository validation", "Enricher tests", "Web tests"],
        "allow_safe_refresh": False, "max_corrections": 1,
        "poll_deadline_utc": "2099-01-01T00:00:00Z", "owner_human": "owner",
        "approval_reference": "approved", "pr_title": "B4.2 test", "pr_body": "body",
    }


def authorization(data, authorization_id="run-authorization-1", operations=None, **changes):
    value = {
        "version": 1, "authorization_id": authorization_id, "lifecycle_id": data["lifecycle_id"],
        "task_contract_fingerprint": L.fingerprint(data),
        "allowed_operations": operations or ["preflight", "publish-head", "ensure-pr", "observe-ci", "authorize-correction", "finalize-correction", "report-ready"],
        "issued_at": "2026-01-01T00:00:00Z", "expires_at": "2026-01-01T00:00:10Z",
    }
    value.update(changes)
    return value


class Clock:
    def __init__(self):
        self.now = L.dt.datetime(2026, 1, 1, tzinfo=L.dt.timezone.utc)

    def expired(self):
        self.now = L.dt.datetime(2026, 1, 1, 0, 0, 10, tzinfo=L.dt.timezone.utc)


class Harness:
    def __init__(self, root: Path, state_root: Path, data: dict):
        self.root, self.state_root, self.data = root, state_root, data
        self.root.mkdir()
        self.head = SHA_A
        self.remote = SHA_A
        self.remote_exists = True
        self.commands: list[list[str]] = []
        self.push_count = 0
        self.pr_posts = 0
        self.observations = 0

    def runner(self, command, cwd):
        self.commands.append(command)
        args = tuple(command[1:])
        if args == ("symbolic-ref", "--short", "HEAD"):
            return self.data["branch"]
        if args == ("remote", "get-url", "origin"):
            return L.ORIGIN_URL
        if args == ("rev-parse", "HEAD"):
            return self.head
        if args == ("status", "--porcelain=v1", "--untracked-files=all"):
            return ""
        if args[:3] == ("diff", "--name-status", "-z"):
            return ""
        if args[:2] == ("merge-base", "--is-ancestor"):
            return ""
        if args[:2] == ("ls-tree", "-z"):
            path = args[-1]
            return f"100644 blob {'d' * 40}\t{path}\0"
        if args[:1] == ("push",):
            self.push_count += 1
            self.remote_exists = True
            self.remote = self.head
            return ""
        if args[:1] == ("ls-remote",):
            return f"{self.remote}\t{args[-1]}" if self.remote_exists else ""
        raise AssertionError(command)


class DirectGuardFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.contract_root = base / "external" / "megabrain" / "hermes-contracts" / "b4.2"
        self.authorization_root = base / "external" / "megabrain" / "hermes-authorizations" / "b4.3"
        self.contract_root.mkdir(parents=True)
        self.authorization_root.mkdir(parents=True)
        for path in (
            base / "external", base / "external" / "megabrain",
            self.contract_root.parent, self.contract_root,
            self.authorization_root.parent, self.authorization_root,
        ):
            path.chmod(0o700)
        self.data = contract()
        (self.contract_root / "life-1.json").write_text(json.dumps(self.data), encoding="utf-8")
        (self.contract_root / "life-1.json").chmod(0o600)
        self.auth_path = self.authorization_root / "run-authorization-1.json"
        self.auth_path.write_text(json.dumps(authorization(self.data)), encoding="utf-8")
        self.auth_path.chmod(0o600)
        self.h = Harness(base / "repo", base / "state", self.data)
        self.clock = Clock()
        self.real_lstat, self.real_fstat = os.lstat, os.fstat
        self.trusted = {
            os.path.abspath(os.fspath(item)) for item in (
                self.contract_root.parent.parent, self.contract_root.parent, self.contract_root,
                self.authorization_root.parent.parent.parent, self.authorization_root.parent.parent,
                self.authorization_root.parent, self.authorization_root, self.contract_root / "life-1.json", self.auth_path,
            )
        }
        self.stack = ExitStack()
        self.stack.enter_context(mock.patch.object(L, "CONTRACT_ROOT", self.contract_root))
        self.stack.enter_context(mock.patch.object(L, "RUN_AUTHORIZATION_ROOT", self.authorization_root))
        self.stack.enter_context(mock.patch.object(L, "_trusted_utc_now", side_effect=lambda: self.clock.now))
        self.stack.enter_context(mock.patch.object(L.os, "lstat", side_effect=self.lstat))
        self.stack.enter_context(mock.patch.object(L.os, "fstat", side_effect=self.fstat))

    def tearDown(self):
        self.stack.close()
        self.temp.cleanup()

    def lstat(self, path, *args, **kwargs):
        value = self.real_lstat(path, *args, **kwargs)
        if args or kwargs:
            return value
        if os.path.abspath(os.fspath(path)) in self.trusted:
            parts = list(value); parts[4] = 0
            return os.stat_result(parts)
        return value

    def fstat(self, descriptor):
        value = self.real_fstat(descriptor)
        target = Path(os.readlink(f"/proc/self/fd/{descriptor}"))
        if target in {self.contract_root / "life-1.json", self.auth_path}:
            parts = list(value); parts[4] = 0
            return os.stat_result(parts)
        return value

    def life(self):
        return L.Lifecycle(self.h.root, "life-1", state_root=self.h.state_root, runner=self.h.runner)

    def preflight(self):
        return self.life().preflight("run-authorization-1")

    def read_state(self):
        return json.loads((self.h.state_root / "life-1" / "state.json").read_text(encoding="utf-8"))

    def write_state(self, value):
        (self.h.state_root / "life-1" / "state.json").write_text(json.dumps(value), encoding="utf-8")


class TerminalAndOperationClosureTests(DirectGuardFixture):
    def test_terminal_status_precedes_rebind_fingerprint_and_expiry(self):
        self.preflight()
        state = self.read_state()
        cases = (
            ("new-id", {"run_authorization_id": "run-authorization-2", "run_authorization_binding_id": "run-authorization-2"}, authorization(self.data, "run-authorization-2")),
            ("fingerprint", {"run_authorization_fingerprint": "0" * 64}, None),
            ("extended-expiry", {}, authorization(self.data, expires_at="2026-01-01T00:00:11Z")),
            ("replacement", {}, authorization(self.data, operations=["preflight", "report-ready"])),
        )
        for status, code in (("READY", "run_replay_after_ready"), ("STOPPED", "run_replay_after_stop")):
            for name, change, artifact in cases:
                with self.subTest(status=status, case=name):
                    candidate = dict(state, run_status=status)
                    candidate.update(change)
                    self.write_state(candidate)
                    if artifact is not None:
                        target = self.authorization_root / f"{artifact['authorization_id']}.json"
                        target.write_text(json.dumps(artifact), encoding="utf-8")
                        target.chmod(0o600)
                        self.trusted.add(target)
                    with self.assertRaisesRegex(L.StopNeedsHuman, code):
                        self.life()._guard("publish-head")
                    self.assertEqual(self.read_state()["run_status"], status)
                    self.auth_path.write_text(json.dumps(authorization(self.data)), encoding="utf-8")
                    self.auth_path.chmod(0o600)

    def test_full_operation_separation_and_no_transitive_publish(self):
        denied = {
            "publish-head": ["ensure-pr", "observe-ci", "authorize-correction", "finalize-correction", "report-ready"],
            "ensure-pr": ["publish-head", "observe-ci", "report-ready"],
            "observe-ci": ["publish-head", "ensure-pr", "report-ready"],
            "authorize-correction": ["finalize-correction", "publish-head", "ensure-pr", "observe-ci", "report-ready"],
            "finalize-correction": ["authorize-correction", "publish-head", "ensure-pr", "observe-ci", "report-ready"],
            "report-ready": ["publish-head", "ensure-pr", "observe-ci", "authorize-correction", "finalize-correction"],
        }
        for allowed, values in denied.items():
            with self.subTest(allowed=allowed):
                self.auth_path.write_text(json.dumps(authorization(self.data, operations=["preflight", allowed])), encoding="utf-8")
                self.auth_path.chmod(0o600)
                self.preflight()
                for denied_operation in values:
                    with self.subTest(denied=denied_operation):
                        with self.assertRaisesRegex(L.StopNeedsHuman, "run_authorization_operation_denied"):
                            self.life()._guard(denied_operation)
                state_path = self.h.state_root / "life-1" / "state.json"
                state_path.unlink()
        self.auth_path.write_text(json.dumps(authorization(self.data, operations=["preflight", "authorize-correction", "finalize-correction"])), encoding="utf-8")
        self.auth_path.chmod(0o600)
        self.preflight()
        with self.assertRaisesRegex(L.StopNeedsHuman, "run_authorization_operation_denied"):
            self.life()._guard("publish-head")
        self.assertEqual(self.h.push_count, 0)

    def _ready_state(self, current_head=SHA_A):
        self.h.head = SHA_A
        self.preflight()
        self.h.head = current_head
        jobs = {name: "success" for name in self.data["expected_ci_jobs"]}
        state = self.read_state()
        state.update({
            "published_once": True, "pr_number": 7, "head_sha": current_head, "ci_sha": current_head,
            "ci_jobs": jobs, "workflow_run_id": 5, "observation_generation": 1,
            "ci_snapshot": {
                "pr_number": 7, "branch": self.data["branch"], "head_sha": current_head,
                "ci_sha": current_head, "ci_jobs": jobs, "workflow_run_id": 5,
                "observation_generation": 1,
                "job_generations": {name: 1 for name in self.data["expected_ci_jobs"]},
            },
        })
        self.write_state(state)
        return state

    def test_exact_state_snapshot_identity_mismatches_cannot_ready(self):
        def a(state):
            state["head_sha"] = SHA_B

        def b(state):
            state["ci_snapshot"]["head_sha"] = SHA_A

        def c(state):
            state["ci_snapshot"]["ci_sha"] = SHA_A

        def d(state):
            state["ci_snapshot"].update({"head_sha": SHA_A, "ci_sha": SHA_A, "workflow_run_id": 6,
                                         "observation_generation": 0,
                                         "job_generations": {name: 0 for name in self.data["expected_ci_jobs"]}})

        def e(state):
            state["observation_generation"] = 2

        def f(state):
            state["ci_snapshot"]["job_generations"]["Web tests"] = 2

        cases = (("state-head-b-ci-a", SHA_A, a), ("snapshot-head-a-state-head-b", SHA_B, b),
                 ("snapshot-ci-a-state-ci-b", SHA_B, c), ("snapshot-evidence-a-current-head-b", SHA_B, d),
                 ("generation-mismatch", SHA_A, e), ("job-generation-mismatch", SHA_A, f))
        state_path = self.h.state_root / "life-1" / "state.json"
        for name, current_head, mutate in cases:
            with self.subTest(case=name):
                if state_path.exists():
                    state_path.unlink()
                value = self._ready_state(current_head)
                mutate(value)
                self.write_state(value)
                with self.assertRaisesRegex(L.StopNeedsHuman, "ci_evidence_stale"):
                    self.life().report_ready()
                self.assertEqual(self.read_state()["run_status"], "ACTIVE")

    def test_new_publish_invalidates_ci_snapshot(self):
        self.preflight()
        state = self.read_state()
        state.update({
            "ci_sha": SHA_A, "ci_jobs": {name: "success" for name in self.data["expected_ci_jobs"]},
            "workflow_run_id": 5, "observation_generation": 1,
            "ci_snapshot": {"untrusted": "stale evidence"},
        })
        self.write_state(state)
        self.h.remote_exists = False
        self.life()._publish_head_locked()
        current = self.read_state()
        self.assertIsNone(current["ci_snapshot"])
        self.assertIsNone(current["ci_sha"])
        self.assertIsNone(current["ci_jobs"])
        self.assertIsNone(current["workflow_run_id"])


class AdapterTimingClosureTests(DirectGuardFixture):
    environment = {"MEGABRAIN_GITHUB_APP_ID": "123", "MEGABRAIN_GITHUB_APP_INSTALLATION_ID": "456", "MEGABRAIN_GITHUB_APP_KEY_PATH": "/fixture/key"}

    def adapter_context(self, module, api):
        actual = L.Lifecycle
        def factory(root, lifecycle_id):
            return actual(root, lifecycle_id, state_root=self.h.state_root, runner=self.h.runner)
        stack = ExitStack()
        stack.enter_context(mock.patch.object(module.LIFECYCLE, "CONTRACT_ROOT", self.contract_root))
        stack.enter_context(mock.patch.object(module.LIFECYCLE, "RUN_AUTHORIZATION_ROOT", self.authorization_root))
        stack.enter_context(mock.patch.object(module.LIFECYCLE, "_trusted_utc_now", side_effect=lambda: self.clock.now))
        stack.enter_context(mock.patch.object(module.LIFECYCLE.os, "lstat", side_effect=self.lstat))
        stack.enter_context(mock.patch.object(module.LIFECYCLE.os, "fstat", side_effect=self.fstat))
        stack.enter_context(mock.patch.object(module.LIFECYCLE, "Lifecycle", side_effect=factory))
        stack.enter_context(mock.patch.object(module.LIFECYCLE, "StopNeedsHuman", L.StopNeedsHuman))
        stack.enter_context(mock.patch.object(module, "validate_privileged_executable"))
        stack.enter_context(mock.patch.object(module, "validate_key_path"))
        stack.enter_context(mock.patch.object(module, "make_jwt", return_value="JWT"))
        stack.enter_context(mock.patch.object(module, "configured_origin", return_value=module.ORIGIN))
        stack.enter_context(mock.patch.object(module, "source_runner", return_value=self.h.runner))
        stack.enter_context(mock.patch.object(module, "request_json", side_effect=api))
        if module is P2:
            stack.enter_context(mock.patch.object(module, "validate_push_destination"))
            stack.enter_context(mock.patch.object(module, "controlled_runner", return_value=self.h.runner))
            stack.enter_context(mock.patch.object(module, "create_askpass", return_value="/fixture/askpass"))
            stack.enter_context(mock.patch.object(module, "create_isolated_staging_repository", side_effect=lambda _s, target, *_: target.mkdir(parents=True, exist_ok=True)))
        return stack

    def prepare(self, operation):
        self.clock = Clock()
        self.h.head = SHA_A
        self.h.remote = SHA_A
        self.h.remote_exists = operation != "publish-head"
        self.h.push_count = 0
        self.auth_path.write_text(json.dumps(authorization(self.data, operations=["preflight", operation])), encoding="utf-8")
        self.auth_path.chmod(0o600)
        self.preflight()
        state = self.read_state()
        if operation in {"ensure-pr", "observe-ci"}:
            state.update({"published_once": True, "head_sha": SHA_A})
        if operation == "observe-ci":
            state["pr_number"] = 7
        self.write_state(state)

    def _pr(self):
        return {
            "number": 7, "state": "open", "merged": False,
            "head": {"ref": self.data["branch"], "sha": SHA_A, "repo": {"full_name": L.REPOSITORY}},
            "base": {"ref": "dev", "repo": {"full_name": L.REPOSITORY}},
            "body": f"B4.2-Contract-Fingerprint: {L.fingerprint(self.data)}",
        }

    def _adapter_case(self, module, operation, phase):
        self.prepare(operation)
        counts = {"authorization_checks": 0, "token_mint_count": 0, "remote_mutation_count": 0,
                  "revoke_count": 0, "cleanup_count": 0}
        created = False
        pr = self._pr()

        def api(method, path, auth, payload=None):
            nonlocal created
            if method == "GET" and path.startswith("/app/installations/"):
                if phase == "pre_mint":
                    self.clock.expired()
                return 200, {"permissions": module.EXPECTED_INSTALLATION_PERMISSIONS}
            if method == "POST" and path.endswith("/access_tokens"):
                counts["token_mint_count"] += 1
                if hasattr(module, "PUBLISH_TOKEN_REQUEST_PERMISSIONS"):
                    permissions = module.PUBLISH_TOKEN_REQUEST_PERMISSIONS
                elif hasattr(module, "PR_TOKEN_REQUEST_PERMISSIONS"):
                    permissions = module.PR_TOKEN_REQUEST_PERMISSIONS
                else:
                    permissions = module.OBSERVE_TOKEN_REQUEST_PERMISSIONS
                return 201, {"token": "fixture", "permissions": permissions}
            if method == "GET" and path == "/installation/repositories":
                if phase == "pre_mutation" and operation in {"publish-head", "observe-ci"}:
                    self.clock.expired()
                return 200, {"total_count": 1, "repositories": [{"full_name": module.REPOSITORY}]}
            if method == "DELETE" and path == "/installation/token":
                counts["revoke_count"] += 1
                if phase == "post_remote_pre_cas":
                    self.clock.expired()
                return 204, {}
            if operation == "ensure-pr":
                pulls = f"/repos/{module.REPOSITORY}/pulls"
                if method == "GET" and path == f"{pulls}?state=all&head=mide-lim:{self.data['branch']}":
                    if phase == "pre_mutation" and not created:
                        self.clock.expired()
                    return 200, [pr] if created else []
                if method == "POST" and path == pulls:
                    counts["remote_mutation_count"] += 1
                    created = True
                    return 201, pr
            if operation == "observe-ci":
                if method == "GET" and path == f"/repos/{module.REPOSITORY}/pulls/7":
                    counts["remote_mutation_count"] += 1
                    return 200, pr
                if method == "GET" and path == f"/repos/{module.REPOSITORY}/actions/runs?event=pull_request&head_sha={SHA_A}":
                    counts["remote_mutation_count"] += 1
                    return 200, {"workflow_runs": [{"id": 5, "event": "pull_request", "head_sha": SHA_A,
                                                       "pull_requests": [{"number": 7}], "status": "completed", "conclusion": "success"}]}
                if method == "GET" and path == f"/repos/{module.REPOSITORY}/actions/runs/5/jobs":
                    counts["remote_mutation_count"] += 1
                    return 200, {"jobs": [{"name": name, "status": "completed", "conclusion": "success"}
                                           for name in self.data["expected_ci_jobs"]]}
            raise AssertionError((method, path, payload))

        actual = L.Lifecycle
        original = actual._validate_run_authorization
        def counted(lifecycle, *args, **kwargs):
            counts["authorization_checks"] += 1
            return original(lifecycle, *args, **kwargs)
        with self.adapter_context(module, api), mock.patch.object(actual, "_validate_run_authorization", autospec=True, side_effect=counted):
            result = module.run_operation(operation, "life-1", self.environment)
        counts["remote_mutation_count"] += self.h.push_count
        counts["cleanup_count"] = int(result["temporary_cleanup"] is True)
        state = self.read_state()
        return result, counts, state

    def test_p2_p3_p4_progressing_clock_authorization_timing(self):
        cases = (
            (P2, "publish-head", "pre_mint", 0, 0),
            (P2, "publish-head", "pre_mutation", 1, 0),
            (P2, "publish-head", "post_remote_pre_cas", 1, 1),
            (P3, "ensure-pr", "pre_mint", 0, 0),
            (P3, "ensure-pr", "pre_mutation", 1, 0),
            (P3, "ensure-pr", "post_remote_pre_cas", 1, 1),
            (P4, "observe-ci", "pre_mint", 0, 0),
            (P4, "observe-ci", "pre_mutation", 1, 0),
            (P4, "observe-ci", "post_remote_pre_cas", 1, 3),
        )
        state_path = self.h.state_root / "life-1" / "state.json"
        for module, operation, phase, expected_mints, expected_remote in cases:
            with self.subTest(operation=operation, phase=phase):
                result, counts, state = self._adapter_case(module, operation, phase)
                state_path.unlink()
                self.assertEqual(result["failure_code"], "run_authorization_expired")
                self.assertGreaterEqual(counts["authorization_checks"], 2)
                self.assertEqual(counts["token_mint_count"], expected_mints)
                self.assertEqual(counts["remote_mutation_count"], expected_remote)
                self.assertEqual(counts["revoke_count"], int(expected_mints == 1))
                self.assertEqual(counts["cleanup_count"], 1)
                self.assertEqual(state["run_status"], "ACTIVE")
                if operation == "ensure-pr":
                    self.assertIsNone(state.get("pr_number"))
                if operation == "observe-ci":
                    self.assertIsNone(state["ci_sha"])
                    self.assertIsNone(state["ci_jobs"])
                    self.assertIsNone(state["workflow_run_id"])
                    self.assertIsNone(state["ci_snapshot"])


if __name__ == "__main__":
    unittest.main()
