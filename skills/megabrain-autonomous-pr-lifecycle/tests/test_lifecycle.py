"""Hermetic safety tests for the closed B4.2 lifecycle capability."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import tempfile
import threading
import unittest
import copy
from unittest import mock
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
MODULE_PATH = SKILL / "scripts" / "autonomous_pr_lifecycle.py"
INSTALLER_PATH = SKILL / "scripts" / "install_skill.py"
SHA = "a" * 40


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


L = load("b42_lifecycle", MODULE_PATH)


def contract(lifecycle_id="life-1", **changes):
    data = {
        "version": "B4.2.1", "lifecycle_id": lifecycle_id, "status": "APPROVED",
        "repository": L.REPOSITORY, "origin_url": L.ORIGIN_URL,
        "branch": "agent/b4-2-autonomous-pr-lifecycle", "base": "dev",
        "head_sha_initial": SHA, "allowed_paths": ["docs/EVIDENCE.md"],
        "expected_ci_jobs": ["Repository validation", "Enricher tests", "Web tests"],
        "allow_safe_refresh": False, "max_corrections": 1,
        "poll_deadline_utc": "2099-01-01T00:00:00Z", "owner_human": "owner",
        "approval_reference": "approved", "pr_title": "B4.2 test", "pr_body": "body",
    }
    data.update(changes)
    return data


def run_authorization(data, authorization_id="run-authorization-1", **changes):
    value = {
        "version": 1, "authorization_id": authorization_id, "lifecycle_id": data["lifecycle_id"],
        "task_contract_fingerprint": L.fingerprint(data),
        "allowed_operations": ["preflight", "publish-head", "ensure-pr", "observe-ci", "authorize-correction", "finalize-correction", "report-ready"],
        "issued_at": "2026-01-01T00:00:00Z", "expires_at": "2026-01-02T00:00:00Z",
    }
    value.update(changes)
    return value


class Harness:
    def __init__(self, root: Path, state: Path, data: dict, *, changed=(), committed=(), branch=None, head=SHA):
        self.root, self.state, self.data = root, state, data
        self.commands = []
        self.requests = []
        self.changed = list(changed)
        self.committed = list(committed)
        self.branch = branch or data["branch"]
        self.head = head
        self.remote_sha = SHA
        self.remote_exists = False
        self.remote_after_push: str | None = None
        self.tree_modes = {}
        path = L.CONTRACT_ROOT
        path.mkdir(parents=True, exist_ok=True)
        (path / f"{data['lifecycle_id']}.json").write_text(json.dumps(data), encoding="utf-8")
        authorization = run_authorization(data)
        (L.RUN_AUTHORIZATION_ROOT / f"{authorization['authorization_id']}.json").write_text(json.dumps(authorization), encoding="utf-8")
        self.pr = self.pr_body(SHA)
        self.same_head_responses: list[list[dict]] | None = None
        self.post_response: dict | None = None
        self.runs_sha = SHA
        self.runs = None
        self.run_status = "completed"
        self.run_conclusion = "success"
        self.jobs = None

    def pr_body(self, sha, *, base="dev"):
        return {"number": 7, "state": "open", "body": "B4.2-Contract-Fingerprint: " + L.fingerprint(self.data),
                "head": {"ref": self.data["branch"], "sha": sha, "repo": {"full_name": L.REPOSITORY}},
                "base": {"ref": base, "repo": {"full_name": L.REPOSITORY}}}

    def runner(self, command, cwd):
        self.commands.append(command)
        args = tuple(command[1:])
        if args == ("symbolic-ref", "--short", "HEAD"): return self.branch
        if args == ("remote", "get-url", "origin"): return L.ORIGIN_URL
        if args == ("rev-parse", "HEAD"): return self.head
        if args == ("status", "--porcelain=v1", "--untracked-files=all"): return "\n".join(" M " + path for path in self.changed)
        if args[:3] == ("diff", "--name-status", "-z"):
            return "".join(f"{status}\0{path}\0" for status, path in self.committed)
        if args[:2] == ("merge-base", "--is-ancestor"): return ""
        if args[:2] == ("ls-tree", "-z"):
            path = args[-1]
            return f"{self.tree_modes.get(path, '100644')} blob {'d' * 40}\t{path}\0"
        if args[:1] == ("push",):
            self.remote_exists = True
            self.remote_sha = self.head if self.remote_after_push is None else self.remote_after_push
            return ""
        if args[:1] == ("ls-remote",): return f"{self.remote_sha}\t{args[-1]}" if self.remote_exists else ""
        if args[:1] in (("fetch",), ("merge",)): return ""
        raise AssertionError(command)

    def request(self, method, path, payload=None):
        self.requests.append((method, path, payload))
        if path.endswith("/pulls?state=all&head=mide-lim:" + self.data["branch"]):
            if self.same_head_responses is not None:
                if not self.same_head_responses:
                    raise AssertionError("unexpected_same_head_search")
                return (200, copy.deepcopy(self.same_head_responses.pop(0)))
            return (200, [self.pr])
        if path.endswith("/pulls/7"):
            return (200, self.pr)
        if path.endswith("actions/runs?event=pull_request&head_sha=" + SHA):
            runs = self.runs if self.runs is not None else [{"id": 5, "event": "pull_request", "head_sha": self.runs_sha, "status": self.run_status, "conclusion": self.run_conclusion, "pull_requests": [{"number": 7}]}]
            return (200, {"workflow_runs": copy.deepcopy(runs)})
        if path.endswith("/actions/runs/5/jobs"):
            jobs = self.jobs if self.jobs is not None else [{"name": name, "status": "completed", "conclusion": "success"} for name in self.data["expected_ci_jobs"]]
            return (200, {"jobs": copy.deepcopy(jobs)})
        if method == "POST" and path.endswith("/pulls"):
            return (201, copy.deepcopy(self.post_response if self.post_response is not None else self.pr))
        raise AssertionError((method, path, payload))

    def lifecycle(self):
        lifecycle = L.Lifecycle(self.root, self.data["lifecycle_id"], state_root=self.state, runner=self.runner, request=self.request)
        original_preflight = lifecycle.preflight
        lifecycle.preflight = lambda authorization_id="run-authorization-1": original_preflight(authorization_id)
        return lifecycle


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "repo"; self.root.mkdir()
        self.state = Path(self.temp.name) / "state"
        self.contract_root = Path(self.temp.name) / "external" / "megabrain" / "hermes-contracts" / "b4.2"
        self.authorization_root = Path(self.temp.name) / "external" / "megabrain" / "hermes-authorizations" / "b4.3"
        self.contract_root.mkdir(parents=True)
        self.authorization_root.mkdir(parents=True)
        self.control_directories = (
            self.contract_root.parent.parent, self.contract_root.parent, self.contract_root,
            self.authorization_root.parent.parent.parent, self.authorization_root.parent.parent,
            self.authorization_root.parent, self.authorization_root,
        )
        self.contract_metadata: dict[Path, dict[str, int]] = {}
        self.real_lstat = os.lstat
        self.real_fstat = os.fstat
        self.contract_root_patch = mock.patch.object(L, "CONTRACT_ROOT", self.contract_root)
        self.authorization_root_patch = mock.patch.object(L, "RUN_AUTHORIZATION_ROOT", self.authorization_root)
        self.now_patch = mock.patch.object(L, "_trusted_utc_now", return_value=L.dt.datetime(2026, 1, 1, 12, tzinfo=L.dt.timezone.utc))
        self.lstat_patch = mock.patch.object(L.os, "lstat", side_effect=self.trusted_lstat)
        self.fstat_patch = mock.patch.object(L.os, "fstat", side_effect=self.trusted_fstat)
        self.contract_root_patch.start(); self.authorization_root_patch.start(); self.now_patch.start(); self.lstat_patch.start(); self.fstat_patch.start()
        self.h = Harness(self.root, self.state, contract())
        self.live = mock.patch.object(L, "_require_live_operations_enabled", return_value=None)
        self.live.start()

    def tearDown(self):
        self.live.stop(); self.fstat_patch.stop(); self.lstat_patch.stop(); self.now_patch.stop(); self.authorization_root_patch.stop(); self.contract_root_patch.stop(); self.temp.cleanup()

    def trusted_lstat(self, path, *args, **kwargs):
        result = self.real_lstat(path, *args, **kwargs)
        if args or kwargs:
            return result
        target = Path(path)
        metadata = self.contract_metadata.get(target, {})
        if target in self.control_directories or target.parent in {self.contract_root, self.authorization_root}:
            values = list(result)
            values[4] = metadata.get("uid", 0)
            default_mode = 0o755 if target in self.control_directories else 0o644
            values[0] = (result.st_mode & ~0o777) | metadata.get("mode", default_mode)
            return os.stat_result(values)
        return result

    def trusted_fstat(self, descriptor):
        result = self.real_fstat(descriptor)
        target = Path(os.readlink(f"/proc/self/fd/{descriptor}"))
        metadata = self.contract_metadata.get(target, {})
        if stat.S_ISREG(result.st_mode) and target.parent in {self.contract_root, self.authorization_root}:
            values = list(result); values[0] = (result.st_mode & ~0o777) | metadata.get("mode", 0o644); values[4] = metadata.get("uid", 0)
            return os.stat_result(values)
        return result

    def preflight(self):
        return self.h.lifecycle().preflight("run-authorization-1")

    def test_preflight_requires_run_authorization(self):
        with self.assertRaisesRegex(L.StopNeedsHuman, "run_authorization_missing"):
            self.h.lifecycle().preflight("missing-authorization")

    def test_run_authorization_requires_integer_schema_version(self):
        authorization = run_authorization(self.h.data, version=True)
        path = self.authorization_root / "run-authorization-1.json"
        path.write_text(json.dumps(authorization), encoding="utf-8")
        with self.assertRaisesRegex(L.StopNeedsHuman, "run_authorization_schema_rejected"):
            self.preflight()

    def test_run_authorization_wrong_lifecycle_has_precise_failure(self):
        authorization = run_authorization(self.h.data, lifecycle_id="other-life")
        path = self.authorization_root / "run-authorization-1.json"
        path.write_text(json.dumps(authorization), encoding="utf-8")
        with self.assertRaisesRegex(L.StopNeedsHuman, "run_authorization_lifecycle_mismatch"):
            self.preflight()

    def test_closed_operations_are_exactly_required(self):
        self.assertEqual(L.PUBLIC_OPERATIONS, frozenset({"preflight", "publish-head", "ensure-pr", "observe-ci", "refresh-from-dev", "report-ready", "authorize-correction", "finalize-correction"}))
        self.assertEqual(
            {n.replace("_", "-") for n in L.Lifecycle.__dict__ if not n.startswith("_")},
            set(L.PUBLIC_OPERATIONS),
        )

    def test_happy_path_publishes_pr_observes_and_reports_ready(self):
        self.preflight(); life = self.h.lifecycle()
        self.assertEqual(life.publish_head()["state"], "PUBLISHED")
        self.assertEqual(life.ensure_pr()["state"], "PR_OPEN")
        self.assertEqual(life.observe_ci()["state"], "CI_GREEN_FOR_HEAD")
        self.assertEqual(life.report_ready()["state"], "READY_FOR_HUMAN_MERGE_FOR_SHA=" + SHA)
        push = next(c for c in self.h.commands if c[1] == "push")
        self.assertEqual(push, ["git", "push", "origin", "HEAD:refs/heads/agent/b4-2-autonomous-pr-lifecycle"])
        self.assertFalse(any(any(x in part for x in ("--force", "--delete", "tag")) for c in self.h.commands for part in c))

    def test_report_ready_rejects_exhausted_correction_budget_before_ready_state(self):
        self.preflight()
        life = self.h.lifecycle()
        life.publish_head()
        life.ensure_pr()
        life.observe_ci()
        state_path = self.h.state / "life-1/state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["corrections"] = self.h.data["max_corrections"] + 1
        state_path.write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaisesRegex(L.StopNeedsHuman, "correction_state_rejected"):
            life.report_ready()
        self.assertEqual(json.loads(state_path.read_text(encoding="utf-8"))["run_status"], "ACTIVE")

    def test_changed_post_initial_head_requires_finalized_correction_before_push_or_budget_use(self):
        self.preflight(); life = self.h.lifecycle()
        self.assertEqual(life.publish_head()["state"], "PUBLISHED")  # Initial P2 behavior remains intact.
        self.h.head = "b" * 40; self.h.committed = [("M", "docs/EVIDENCE.md")]
        with self.assertRaisesRegex(L.StopNeedsHuman, "correction_finalization_required"):
            life.publish_head()
        current = json.loads((self.h.state / "life-1/state.json").read_text(encoding="utf-8"))
        self.assertEqual(current["corrections"], 0)
        self.assertIsNone(current["pending_correction_sha"])
        self.assertEqual(len([command for command in self.h.commands if command[1:2] == ["push"]]), 1)

    def test_default_installation_stops_all_authenticated_lifecycle_operations(self):
        self.live.stop()
        self.preflight()
        life = self.h.lifecycle()
        for operation in (life.publish_head, life.ensure_pr, life.observe_ci, life.refresh_from_dev):
            with self.assertRaisesRegex(L.StopNeedsHuman, "authenticated_operations_not_authorized"):
                operation()
        self.assertFalse(any(command[1:2] == ["push"] for command in self.h.commands))
        self.assertFalse(self.h.requests)
        self.live.start()

    def test_changed_contract_fingerprint_stops_every_operation(self):
        self.preflight()
        path = self.contract_root / "life-1.json"; altered = contract(pr_title="changed"); path.write_text(json.dumps(altered), encoding="utf-8")
        with self.assertRaisesRegex(L.StopNeedsHuman, "contract_fingerprint_divergent"): self.h.lifecycle().publish_head()

    def test_repository_local_contract_is_ignored(self):
        local = self.root / "contracts/b4.2"; local.mkdir(parents=True)
        (local / "life-1.json").write_text("not-json", encoding="utf-8")
        self.assertEqual(self.preflight()["state"], "PREFLIGHT_OK")

    def test_missing_external_contract_fails_closed_even_with_repository_contract(self):
        local = self.root / "contracts/b4.2"; local.mkdir(parents=True)
        (local / "life-1.json").write_text(json.dumps(contract()), encoding="utf-8")
        (self.contract_root / "life-1.json").unlink()
        with self.assertRaisesRegex(L.StopNeedsHuman, "contract_path_rejected"):
            self.preflight()

    def test_symlink_external_contract_is_rejected(self):
        path = self.contract_root / "life-1.json"; target = self.contract_root / "target.json"
        target.write_text(json.dumps(contract()), encoding="utf-8"); path.unlink(); path.symlink_to(target)
        with self.assertRaisesRegex(L.StopNeedsHuman, "contract_path_rejected"):
            self.preflight()

    def test_group_or_other_writable_external_contract_is_rejected(self):
        self.contract_metadata[self.contract_root / "life-1.json"] = {"mode": 0o664}
        with self.assertRaisesRegex(L.StopNeedsHuman, "contract_path_rejected"):
            self.preflight()

    def test_group_or_other_writable_external_control_directory_is_rejected(self):
        self.contract_metadata[self.contract_root] = {"mode": 0o775}
        with self.assertRaisesRegex(L.StopNeedsHuman, "contract_root_rejected"):
            self.preflight()

    def test_symlink_intermediate_contract_directory_is_rejected(self):
        intermediate = self.contract_root.parent
        replacement = intermediate.with_name("replacement-contracts")
        intermediate.rename(replacement)
        intermediate.symlink_to(replacement, target_is_directory=True)
        with self.assertRaisesRegex(L.StopNeedsHuman, "contract_root_rejected"):
            self.preflight()

    def test_non_root_owned_intermediate_contract_directory_is_rejected(self):
        self.contract_metadata[self.contract_root.parent] = {"uid": 1000}
        with self.assertRaisesRegex(L.StopNeedsHuman, "contract_root_rejected"):
            self.preflight()

    def test_group_or_other_writable_intermediate_contract_directory_is_rejected(self):
        self.contract_metadata[self.contract_root.parent] = {"mode": 0o775}
        with self.assertRaisesRegex(L.StopNeedsHuman, "contract_root_rejected"):
            self.preflight()

    def test_non_root_owned_external_contract_is_rejected(self):
        self.contract_metadata[self.contract_root / "life-1.json"] = {"uid": 1000}
        with self.assertRaisesRegex(L.StopNeedsHuman, "contract_path_rejected"):
            self.preflight()

    def test_root_owned_read_only_external_contract_is_accepted(self):
        self.contract_metadata[self.contract_root / "life-1.json"] = {"uid": 0, "mode": 0o444}
        self.assertEqual(self.preflight()["state"], "PREFLIGHT_OK")

    def test_fully_trusted_contract_directory_chain_is_accepted(self):
        self.assertEqual(self.preflight()["state"], "PREFLIGHT_OK")

    def test_clean_committed_workflow_change_stops_publish(self):
        h = Harness(self.root / "clean-workflow", self.state / "clean-workflow", contract(), committed=[("M", ".github/workflows/ci.yml")])
        h.lifecycle().preflight()
        h.head = "b" * 40
        with self.assertRaisesRegex(L.StopNeedsHuman, "committed_path_rejected"):
            h.lifecycle().publish_head()

    def test_clean_committed_skill_change_stops_publish(self):
        h = Harness(self.root / "clean-skill", self.state / "clean-skill", contract(), committed=[("M", "skills/example/SKILL.md")])
        h.lifecycle().preflight()
        h.head = "b" * 40
        with self.assertRaisesRegex(L.StopNeedsHuman, "committed_path_rejected"):
            h.lifecycle().publish_head()

    def test_clean_committed_allowed_path_publishes(self):
        h = Harness(self.root / "clean-allowed", self.state / "clean-allowed", contract(allowed_paths=["docs/EVIDENCE.md"]), committed=[("M", "docs/EVIDENCE.md")])
        h.lifecycle().preflight()
        h.head = "b" * 40
        self.assertEqual(h.lifecycle().publish_head()["head_sha"], "b" * 40)

    def test_clean_committed_rename_stops_publish(self):
        h = Harness(self.root / "clean-rename", self.state / "clean-rename", contract(), committed=[("R100", "docs/EVIDENCE.md")])
        h.lifecycle().preflight()
        h.head = "b" * 40
        with self.assertRaisesRegex(L.StopNeedsHuman, "committed_path_rejected"):
            h.lifecycle().publish_head()

    def test_clean_committed_delete_stops_publish(self):
        h = Harness(self.root / "clean-delete", self.state / "clean-delete", contract(), committed=[("D", "docs/EVIDENCE.md")])
        h.lifecycle().preflight()
        h.head = "b" * 40
        with self.assertRaisesRegex(L.StopNeedsHuman, "committed_path_rejected"):
            h.lifecycle().publish_head()

    def test_clean_committed_allowed_addition_publishes(self):
        h = Harness(self.root / "clean-add", self.state / "clean-add", contract(allowed_paths=["docs/EVIDENCE.md"]), committed=[("A", "docs/EVIDENCE.md")])
        h.lifecycle().preflight()
        h.head = "b" * 40
        self.assertEqual(h.lifecycle().publish_head()["head_sha"], "b" * 40)

    def test_clean_committed_workflow_addition_stops_publish(self):
        h = Harness(
            self.root / "clean-workflow-add",
            self.state / "clean-workflow-add",
            contract(allowed_paths=[".github/workflows/ci.yml"]),
            committed=[("A", ".github/workflows/ci.yml")],
        )
        h.lifecycle().preflight()
        h.head = "b" * 40
        with self.assertRaisesRegex(L.StopNeedsHuman, "committed_path_rejected"):
            h.lifecycle().publish_head()

    def test_clean_committed_skill_addition_stops_publish(self):
        h = Harness(
            self.root / "clean-skill-add",
            self.state / "clean-skill-add",
            contract(allowed_paths=["skills/example/SKILL.md"]),
            committed=[("A", "skills/example/SKILL.md")],
        )
        h.lifecycle().preflight()
        h.head = "b" * 40
        with self.assertRaisesRegex(L.StopNeedsHuman, "committed_path_rejected"):
            h.lifecycle().publish_head()

    def test_clean_committed_copy_below_full_similarity_stops_publish(self):
        h = Harness(self.root / "clean-copy-partial", self.state / "clean-copy-partial", contract(), committed=[("C099", "docs/EVIDENCE.md")])
        h.lifecycle().preflight()
        h.head = "b" * 40
        with self.assertRaisesRegex(L.StopNeedsHuman, "committed_path_rejected"):
            h.lifecycle().publish_head()

    def test_clean_committed_symlink_stops_publish_by_tree_mode(self):
        h = Harness(self.root / "clean-symlink", self.state / "clean-symlink", contract(allowed_paths=["docs/EVIDENCE.md"]), committed=[("M", "docs/EVIDENCE.md")])
        h.lifecycle().preflight()
        h.head = "b" * 40
        h.tree_modes["docs/EVIDENCE.md"] = "120000"
        with self.assertRaisesRegex(L.StopNeedsHuman, "committed_path_rejected"):
            h.lifecycle().publish_head()

    def test_clean_committed_copy_stops_publish(self):
        h = Harness(self.root / "clean-copy", self.state / "clean-copy", contract(), committed=[("C100", "docs/EVIDENCE.md")])
        h.lifecycle().preflight()
        h.head = "b" * 40
        with self.assertRaisesRegex(L.StopNeedsHuman, "committed_path_rejected"):
            h.lifecycle().publish_head()

    def test_control_plane_and_capability_paths_are_denied(self):
        for path in ("skills/megabrain-autonomous-pr-lifecycle/scripts/autonomous_pr_lifecycle.py", "skills/megabrain-github-app-auth/scripts/github_app_auth.py", "skills/another-capability/SKILL.md", ".github/workflows/ci.yml", "AGENTS.md", "docs/RISK_POLICY.md", "docs/DEFINITION_OF_DONE.md", "docs/TASK_CONTRACT_X.md", "docs/DEVELOPMENT_WORKFLOW.md", "contracts/b4.2/life-1.json"):
            h = Harness(self.root / hashlib.sha1(path.encode()).hexdigest(), self.state / hashlib.sha1(path.encode()).hexdigest(), contract(), changed=[path])
            with self.assertRaisesRegex(L.StopNeedsHuman, "changed_path_rejected"): h.lifecycle().preflight()

    def test_active_task_and_evidence_need_explicit_allowance(self):
        h = Harness(self.root / "allowed", self.state / "allowed", contract(allowed_paths=["docs/ACTIVE_TASK.md", "docs/EVIDENCE.md"]), changed=["docs/ACTIVE_TASK.md", "docs/EVIDENCE.md"])
        self.assertEqual(h.lifecycle().preflight()["state"], "PREFLIGHT_OK")
        h = Harness(self.root / "unallowed", self.state / "unallowed", contract(), changed=["docs/ACTIVE_TASK.md"])
        with self.assertRaises(L.StopNeedsHuman): h.lifecycle().preflight()

    def test_traversal_symlink_and_similar_branch_stop(self):
        bad = contract(allowed_paths=["../AGENTS.md"])
        h = Harness(self.root / "bad", self.state / "bad", bad)
        with self.assertRaisesRegex(L.StopNeedsHuman, "contract_paths_rejected"): h.lifecycle().preflight()
        h = Harness(self.root / "branch", self.state / "branch", contract(), branch="agent/b4-2-autonomous-pr-lifecycle-x")
        with self.assertRaisesRegex(L.StopNeedsHuman, "local_branch_rejected"): h.lifecycle().preflight()
        linkroot = self.root / "link"; linkroot.mkdir(); (linkroot / "contracts").symlink_to(self.root / "contracts")
        self.assertEqual(L.Lifecycle(linkroot, "life-1", state_root=self.state, runner=self.h.runner).preflight("run-authorization-1")["state"], "PREFLIGHT_OK")
        state_target = self.root / "state-target"; state_target.mkdir()
        state_link = self.root / "state-link"; state_link.symlink_to(state_target, target_is_directory=True)
        with self.assertRaisesRegex(L.StopNeedsHuman, "state_root_rejected"):
            L.Lifecycle(self.root, "life-1", state_root=state_link, runner=self.h.runner)

    def test_alternative_unique_nonempty_ci_job_contract_is_valid(self):
        h = Harness(
            self.root / "alternative-ci-jobs",
            self.state / "alternative-ci-jobs",
            contract(expected_ci_jobs=["Alternative validation", "Alternative tests"]),
        )
        self.assertEqual(h.lifecycle().preflight()["state"], "PREFLIGHT_OK")

    def test_preflight_binds_the_declared_initial_head(self):
        h = Harness(self.root / "initial", self.state / "initial", contract(), head="b" * 40)
        with self.assertRaisesRegex(L.StopNeedsHuman, "initial_head_mismatch"):
            h.lifecycle().preflight()

    def test_remote_head_drift_stops_before_ensure_pr_mutation(self):
        self.preflight()
        life = self.h.lifecycle()
        life.publish_head()
        self.h.remote_sha = "b" * 40
        with self.assertRaisesRegex(L.StopNeedsHuman, "remote_head_drift"):
            life.ensure_pr()
        self.assertFalse(any(method == "POST" for method, _, _ in self.h.requests))

    def test_unexpected_first_remote_branch_and_later_drift_stop_before_push(self):
        self.preflight()
        self.h.remote_exists = True
        with self.assertRaisesRegex(L.StopNeedsHuman, "unexpected_remote_branch"):
            self.h.lifecycle().publish_head()
        self.assertFalse(any(command[1:2] == ["push"] for command in self.h.commands))

        self.h.remote_exists = False
        self.h.lifecycle().publish_head()
        self.h.head = "b" * 40
        state_path = self.h.state / "life-1/state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state.update({"pr_number": 7, "pending_correction_sha": self.h.head, "pending_publish_attempted": False,
                      "ci_failure": {"head_sha": SHA, "pr_number": 7, "workflow_run_id": 5,
                                     "jobs": {"Repository validation": "failure", "Enricher tests": "success", "Web tests": "success"}}})
        state_path.write_text(json.dumps(state), encoding="utf-8")
        self.h.remote_sha = "c" * 40
        with self.assertRaisesRegex(L.StopNeedsHuman, "remote_head_drift"):
            self.h.lifecycle().publish_head()
        self.assertEqual(len([command for command in self.h.commands if command[1:2] == ["push"]]), 1)

    def test_publish_requires_exact_remote_sha_readback(self):
        self.preflight()
        self.h.remote_after_push = "b" * 40
        with self.assertRaisesRegex(L.StopNeedsHuman, "remote_head_mismatch"):
            self.h.lifecycle().publish_head()

    def test_remote_head_drift_during_pr_reuse_stops_before_acceptance(self):
        self.preflight()
        life = self.h.lifecycle()
        life.publish_head()
        original_request = self.h.request
        def drift_after_lookup(method, path, payload=None):
            response = original_request(method, path, payload)
            if "pulls?" in path:
                self.h.remote_sha = "b" * 40
            return response
        self.h.request = drift_after_lookup
        with self.assertRaisesRegex(L.StopNeedsHuman, "remote_head_drift"):
            self.h.lifecycle().ensure_pr()

    def _published_state_with_stored_pr(self, number=7):
        self.preflight()
        self.h.lifecycle().publish_head()
        state_path = self.h.state / "life-1/state.json"
        value = json.loads(state_path.read_text(encoding="utf-8"))
        value["pr_number"] = number
        state_path.write_text(json.dumps(value), encoding="utf-8")

    def test_stored_pr_requires_exactly_one_matching_same_head_pr_and_direct_get(self):
        self._published_state_with_stored_pr()
        self.h.same_head_responses = [[self.h.pr_body(SHA)]]
        result = self.h.lifecycle().ensure_pr()
        self.assertEqual(result["pr_number"], 7)
        paths = [path for _, path, _ in self.h.requests]
        self.assertIn(f"/repos/{L.REPOSITORY}/pulls?state=all&head=mide-lim:{self.h.data['branch']}", paths)
        self.assertIn(f"/repos/{L.REPOSITORY}/pulls/7", paths)

    def test_stored_pr_second_same_head_pr_stops(self):
        self._published_state_with_stored_pr()
        self.h.same_head_responses = [[self.h.pr_body(SHA), self.h.pr_body(SHA)]]
        with self.assertRaisesRegex(L.StopNeedsHuman, "pr_count_rejected"):
            self.h.lifecycle().ensure_pr()

    def test_stored_pr_missing_from_same_head_collection_stops(self):
        self._published_state_with_stored_pr()
        self.h.same_head_responses = [[]]
        with self.assertRaisesRegex(L.StopNeedsHuman, "pr_count_rejected"):
            self.h.lifecycle().ensure_pr()

    def test_stored_pr_must_match_the_sole_same_head_pr(self):
        self._published_state_with_stored_pr()
        self.h.same_head_responses = [[self.h.pr_body(SHA) | {"number": 8}]]
        with self.assertRaisesRegex(L.StopNeedsHuman, "pr_drift_rejected"):
            self.h.lifecycle().ensure_pr()

    def test_post_create_second_same_head_pr_stops_without_state_commit(self):
        self.preflight()
        self.h.lifecycle().publish_head()
        created = self.h.pr_body(SHA)
        conflicting = self.h.pr_body(SHA) | {"number": 8}
        self.h.post_response = created
        self.h.same_head_responses = [[], [created, conflicting]]
        with self.assertRaisesRegex(L.StopNeedsHuman, "pr_count_rejected"):
            self.h.lifecycle().ensure_pr()
        value = json.loads((self.h.state / "life-1/state.json").read_text(encoding="utf-8"))
        self.assertNotIn("pr_number", value)

    def test_post_create_requires_exactly_the_returned_same_head_pr(self):
        self.preflight()
        self.h.lifecycle().publish_head()
        created = self.h.pr_body(SHA) | {"number": 11}
        self.h.post_response = created
        self.h.same_head_responses = [[], [created]]
        self.assertEqual(self.h.lifecycle().ensure_pr()["pr_number"], 11)
        searches = [path for _, path, _ in self.h.requests if "pulls?state=all" in path]
        self.assertEqual(len(searches), 2)

    def _deferred_pr_commit_inputs(self):
        self.preflight()
        self.h.lifecycle().publish_head()
        life = self.h.lifecycle()
        _, expected = life._guard()
        deferred = copy.deepcopy(expected)
        deferred["pr_number"] = 7
        return life, expected, deferred

    def test_deferred_pr_commit_rejects_lifecycle_state_change_without_overwrite(self):
        life, expected, deferred = self._deferred_pr_commit_inputs()
        state_path = self.h.state / "life-1/state.json"
        changed = json.loads(state_path.read_text(encoding="utf-8"))
        changed["ci_sha"] = SHA
        state_path.write_text(json.dumps(changed), encoding="utf-8")
        with self.assertRaisesRegex(L.StopNeedsHuman, "state_changed_before_commit"):
            life._commit_deferred_pr_state(expected, expected["fingerprint"], SHA, deferred)
        self.assertEqual(json.loads(state_path.read_text(encoding="utf-8")), changed)

    def test_deferred_pr_commit_revalidates_remote_sha_before_state_write(self):
        life, expected, deferred = self._deferred_pr_commit_inputs()
        self.h.remote_sha = "b" * 40
        with self.assertRaisesRegex(L.StopNeedsHuman, "remote_head_drift"):
            life._commit_deferred_pr_state(expected, expected["fingerprint"], SHA, deferred)
        value = json.loads((self.h.state / "life-1/state.json").read_text(encoding="utf-8"))
        self.assertNotIn("pr_number", value)

    def test_deferred_pr_commit_revalidates_contract_fingerprint_before_state_write(self):
        life, expected, deferred = self._deferred_pr_commit_inputs()
        altered = contract(pr_title="changed")
        (self.contract_root / "life-1.json").write_text(json.dumps(altered), encoding="utf-8")
        with self.assertRaisesRegex(L.StopNeedsHuman, "contract_fingerprint_divergent"):
            life._commit_deferred_pr_state(expected, expected["fingerprint"], SHA, deferred)
        value = json.loads((self.h.state / "life-1/state.json").read_text(encoding="utf-8"))
        self.assertNotIn("pr_number", value)

    def test_max_corrections_zero_allows_initial_publish_then_stops_first_fix(self):
        h = Harness(self.root / "budget-zero", self.state / "budget-zero", contract(max_corrections=0, allowed_paths=["docs/EVIDENCE.md"]), committed=[("M", "docs/EVIDENCE.md")])
        h.lifecycle().preflight()

        h.head = "b" * 40
        self.assertEqual(h.lifecycle().publish_head()["state"], "PUBLISHED")

        state = json.loads((h.state / "life-1/state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["corrections"], 0)
        self.assertTrue(state["published_once"])

        h.head = "c" * 40
        with self.assertRaisesRegex(L.StopNeedsHuman, "correction_finalization_required"):
            h.lifecycle().publish_head()

        pushes = [command for command in h.commands if command[1:2] == ["push"]]
        self.assertEqual(len(pushes), 1)

    def test_existing_publish_reservation_stops_second_correction_before_push(self):
        h = Harness(self.root / "budget-locked", self.state / "budget-locked", contract(max_corrections=1, allowed_paths=["docs/EVIDENCE.md"]), committed=[("M", "docs/EVIDENCE.md")])
        h.lifecycle().preflight()
        h.head = "b" * 40
        (h.state / "life-1/publish.lock").write_text("reserved", encoding="utf-8")
        with self.assertRaisesRegex(L.StopNeedsHuman, "publish_reservation_locked"):
            h.lifecycle().publish_head()
        self.assertFalse(any(command[1:2] == ["push"] for command in h.commands))

    def test_publish_reservation_serializes_concurrent_corrections(self):
        h = Harness(self.root / "budget-concurrent", self.state / "budget-concurrent", contract(max_corrections=1, allowed_paths=["docs/EVIDENCE.md"]), committed=[("M", "docs/EVIDENCE.md")])
        h.lifecycle().preflight()
        h.head = "b" * 40
        entered = threading.Event()
        release = threading.Event()
        result = []
        original_runner = h.runner
        def blocking_runner(command, cwd):
            if command[1:2] == ["push"]:
                entered.set()
                self.assertTrue(release.wait(timeout=2))
            return original_runner(command, cwd)
        first = L.Lifecycle(h.root, "life-1", state_root=h.state, runner=blocking_runner, request=h.request)
        thread = threading.Thread(target=lambda: result.append(first.publish_head()))
        thread.start()
        self.assertTrue(entered.wait(timeout=2))
        with self.assertRaisesRegex(L.StopNeedsHuman, "publish_reservation_locked"):
            h.lifecycle().publish_head()
        release.set()
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result[0]["state"], "PUBLISHED")

    def test_p2_publication_reservation_blocks_concurrent_p3_transition(self):
        h = Harness(self.root / "p2-blocks-p3", self.state / "p2-blocks-p3", contract())
        h.lifecycle().preflight()
        entered = threading.Event()
        release = threading.Event()
        original_runner = h.runner

        def blocking_runner(command, cwd):
            if command[1:2] == ["push"]:
                entered.set()
                self.assertTrue(release.wait(timeout=2))
            return original_runner(command, cwd)

        thread = threading.Thread(target=lambda: L.Lifecycle(h.root, "life-1", state_root=h.state, runner=blocking_runner, request=h.request).publish_head())
        thread.start()
        self.assertTrue(entered.wait(timeout=2))
        with self.assertRaisesRegex(L.StopNeedsHuman, "publish_reservation_locked"):
            h.lifecycle().ensure_pr()
        release.set()
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())

    def test_p3_reservation_blocks_concurrent_p2_publication(self):
        h = Harness(self.root / "p3-blocks-p2", self.state / "p3-blocks-p2", contract())
        h.lifecycle().preflight()
        h.lifecycle().publish_head()
        entered = threading.Event()
        release = threading.Event()
        original_request = h.request

        def blocking_request(method, path, payload=None):
            if "pulls?state=all" in path:
                entered.set()
                self.assertTrue(release.wait(timeout=2))
            return original_request(method, path, payload)

        result = []
        thread = threading.Thread(target=lambda: result.append(L.Lifecycle(h.root, "life-1", state_root=h.state, runner=h.runner, request=blocking_request).ensure_pr()))
        thread.start()
        self.assertTrue(entered.wait(timeout=2))
        with self.assertRaisesRegex(L.StopNeedsHuman, "publish_reservation_locked"):
            h.lifecycle().publish_head()
        release.set()
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result[0]["state"], "PR_OPEN")

    def test_correction_budget_allows_exact_limit_and_persists_count(self):
        h = Harness(self.root / "budget-exact", self.state / "budget-exact", contract(max_corrections=1, allowed_paths=["docs/EVIDENCE.md"]), committed=[("M", "docs/EVIDENCE.md")])
        h.lifecycle().preflight()

        h.head = "b" * 40
        self.assertEqual(h.lifecycle().publish_head()["state"], "PUBLISHED")

        state = json.loads((h.state / "life-1/state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["corrections"], 0)
        self.assertTrue(state["published_once"])

        h.head = "c" * 40
        state.update({"pr_number": 7, "pending_correction_sha": h.head, "pending_publish_attempted": False,
                      "ci_failure": {"head_sha": "b" * 40, "pr_number": 7, "workflow_run_id": 5,
                                     "jobs": {"Repository validation": "failure", "Enricher tests": "success", "Web tests": "success"}}})
        (h.state / "life-1/state.json").write_text(json.dumps(state), encoding="utf-8")
        h.pr = h.pr_body("b" * 40)
        self.assertEqual(h.lifecycle().publish_head()["state"], "PUBLISHED")

        state = json.loads((h.state / "life-1/state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["corrections"], 1)

    def test_correction_budget_stops_above_limit(self):
        h = Harness(self.root / "budget-over", self.state / "budget-over", contract(max_corrections=1, allowed_paths=["docs/EVIDENCE.md"]), committed=[("M", "docs/EVIDENCE.md")])
        h.lifecycle().preflight()

        # Initial implementation publish: does not consume correction budget.
        h.head = "b" * 40
        h.lifecycle().publish_head()

        # First correction: a finalized pending state is required and allowed.
        h.head = "c" * 40
        state_path = h.state / "life-1/state.json"; state = json.loads(state_path.read_text(encoding="utf-8"))
        state.update({"pr_number": 7, "pending_correction_sha": h.head, "pending_publish_attempted": False,
                      "ci_failure": {"head_sha": "b" * 40, "pr_number": 7, "workflow_run_id": 5,
                                     "jobs": {"Repository validation": "failure", "Enricher tests": "success", "Web tests": "success"}}})
        state_path.write_text(json.dumps(state), encoding="utf-8"); h.pr = h.pr_body("b" * 40)
        h.lifecycle().publish_head()

        # Second finalized correction exceeds max_corrections=1.
        h.head = "d" * 40
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state.update({"pending_correction_sha": h.head, "pending_publish_attempted": False,
                      "ci_failure": {"head_sha": "c" * 40, "pr_number": 7, "workflow_run_id": 6,
                                     "jobs": {"Repository validation": "failure", "Enricher tests": "success", "Web tests": "success"}}})
        state_path.write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaisesRegex(L.StopNeedsHuman, "correction_publish_rejected"):
            h.lifecycle().publish_head()

        pushes = [command for command in h.commands if command[1:2] == ["push"]]
        self.assertEqual(len(pushes), 2)

    def test_missing_publication_state_fails_closed(self):
        h = Harness(self.root / "publication-state", self.state / "publication-state", contract())
        h.lifecycle().preflight()

        state_path = h.state / "life-1/state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state.pop("published_once")
        state_path.write_text(json.dumps(state), encoding="utf-8")

        with self.assertRaisesRegex(L.StopNeedsHuman, "publication_state_rejected"):
            h.lifecycle().publish_head()

    def test_closed_prior_pr_without_state_stops_second_creation(self):
        self.preflight()
        life = self.h.lifecycle()
        life.publish_head()
        self.h.pr["state"] = "closed"
        with self.assertRaisesRegex(L.StopNeedsHuman, "pr_terminal_state"):
            life.ensure_pr()
        self.assertTrue(any("pulls?state=all" in path for _, path, _ in self.h.requests))
        self.assertFalse(any(method == "POST" for method, _, _ in self.h.requests))

    def test_previously_closed_pr_stops_without_second_creation(self):
        self.preflight()
        life = self.h.lifecycle()
        life.publish_head()
        life.ensure_pr()
        self.h.pr["state"] = "closed"
        self.h.requests.clear()
        with self.assertRaisesRegex(L.StopNeedsHuman, "pr_terminal_state"):
            life.ensure_pr()
        self.assertFalse(any(method == "POST" for method, _, _ in self.h.requests))

    def test_previously_merged_pr_stops_without_second_creation(self):
        self.preflight()
        life = self.h.lifecycle()
        life.publish_head()
        life.ensure_pr()
        self.h.pr["state"] = "closed"
        self.h.pr["merged"] = True
        self.h.requests.clear()
        with self.assertRaisesRegex(L.StopNeedsHuman, "pr_terminal_state"):
            life.ensure_pr()
        self.assertFalse(any(method == "POST" for method, _, _ in self.h.requests))

    def test_second_pr_base_drift_remote_head_and_old_green_ci_stop(self):
        self.preflight(); life = self.h.lifecycle(); life.publish_head()
        original_request = self.h.request
        self.h.request = lambda m,p,payload=None: (200, [self.h.pr, self.h.pr]) if "pulls?" in p else original_request(m,p,payload)
        with self.assertRaisesRegex(L.StopNeedsHuman, "pr_count_rejected"): self.h.lifecycle().ensure_pr()
        self.h = Harness(self.root / "remote", self.state / "remote", contract()); self.preflight(); life=self.h.lifecycle(); life.publish_head(); life.ensure_pr(); self.h.pr=self.h.pr_body("b"*40)
        with self.assertRaisesRegex(L.StopNeedsHuman, "pr_drift_rejected"): life.observe_ci()
        self.h = Harness(self.root / "old", self.state / "old", contract()); self.preflight(); life=self.h.lifecycle(); life.publish_head(); life.ensure_pr(); self.h.runs_sha="b"*40
        with self.assertRaisesRegex(L.StopNeedsHuman, "workflow_run_ambiguous"): life.observe_ci()
        self.h = Harness(self.root / "base", self.state / "base", contract()); self.preflight(); life=self.h.lifecycle(); life.publish_head(); self.h.pr=self.h.pr_body(SHA, base="main")
        with self.assertRaisesRegex(L.StopNeedsHuman, "pr_drift_rejected"): life.ensure_pr()
        self.h = Harness(self.root / "extra", self.state / "extra", contract()); self.preflight(); life=self.h.lifecycle(); life.publish_head(); life.ensure_pr()
        original_request = self.h.request
        def extra_check(method, path, payload=None):
            if path.endswith("/actions/runs/5/jobs"):
                return (200, {"jobs": [{"name": name, "conclusion": "success"} for name in self.h.data["expected_ci_jobs"]] + [{"name": "unexpected", "conclusion": "success"}]})
            return original_request(method, path, payload)
        self.h.request = extra_check
        with self.assertRaisesRegex(L.StopNeedsHuman, "ci_not_green_for_head"): self.h.lifecycle().observe_ci()

    def test_p4_ci_preconditions_and_exact_pr_are_fail_closed(self):
        for change, code in (({"pr_number": None}, "pr_or_head_missing"), ({"pr_number": "7"}, "pr_or_head_missing"), ({"head_sha": "b" * 40}, "pr_or_head_missing")):
            with self.subTest(change=change):
                self._published_state_with_stored_pr()
                state_path = self.h.state / "life-1/state.json"
                value = json.loads(state_path.read_text(encoding="utf-8")); value.update(change); state_path.write_text(json.dumps(value), encoding="utf-8")
                with self.assertRaisesRegex(L.StopNeedsHuman, code): self.h.lifecycle().observe_ci()
                self.h = Harness(self.root / hashlib.sha1(repr(change).encode()).hexdigest(), self.state / hashlib.sha1(repr(change).encode()).hexdigest(), contract())
        self._published_state_with_stored_pr()
        for altered in (self.h.pr_body(SHA, base="main"), self.h.pr_body("b" * 40), self.h.pr_body(SHA) | {"state": "closed"}, self.h.pr_body(SHA) | {"merged": True}):
            self.h.pr = altered
            with self.subTest(pr=altered):
                with self.assertRaisesRegex(L.StopNeedsHuman, "pr_drift_rejected"):
                    self.h.lifecycle().observe_ci()
            self.h.pr = self.h.pr_body(SHA)

    def test_p4_writes_exact_structured_failure_and_keeps_ci_sha_green_only(self):
        self._published_state_with_stored_pr()
        self.h.run_conclusion = "failure"
        self.h.jobs = [{"name": "Repository validation", "status": "completed", "conclusion": "failure"},
                       {"name": "Enricher tests", "status": "completed", "conclusion": "success"},
                       {"name": "Web tests", "status": "completed", "conclusion": "success"}]
        observed = self.h.lifecycle().observe_ci()
        self.assertEqual(observed["state"], "CI_FAILED_FOR_HEAD")
        current = json.loads((self.h.state / "life-1/state.json").read_text(encoding="utf-8"))
        self.assertIsNone(current["ci_sha"])
        self.assertEqual(current["ci_failure"], {"head_sha": SHA, "pr_number": 7, "workflow_run_id": 5,
                                                  "jobs": {"Repository validation": "failure", "Enricher tests": "success", "Web tests": "success"}})

    def test_p4_runs_and_jobs_require_exact_completed_success(self):
        self._published_state_with_stored_pr()
        run = {"id": 5, "event": "pull_request", "head_sha": SHA, "status": "completed", "conclusion": "success", "pull_requests": [{"number": 7}]}
        for runs, code in (([], "workflow_run_ambiguous"), ([run, run | {"id": 6}], "workflow_run_ambiguous"), ([run | {"head_sha": "b" * 40}], "workflow_run_ambiguous"), ([run | {"pull_requests": [{"number": 8}]}], "workflow_run_ambiguous"), ([run | {"event": "push"}], "workflow_run_ambiguous"), ([{key: value for key, value in run.items() if key != "event"}], "workflow_run_ambiguous"), ([run | {"status": "in_progress"}], "ci_not_green_for_head"), ([run | {"conclusion": "failure"}], "ci_not_green_for_head")):
            with self.subTest(runs=runs):
                self.h.runs = runs
                with self.assertRaisesRegex(L.StopNeedsHuman, code): self.h.lifecycle().observe_ci()
        self.h.runs = [run]
        expected = self.h.data["expected_ci_jobs"]
        green = [{"name": name, "status": "completed", "conclusion": "success"} for name in expected]
        invalid_jobs = [green[:-1], green + [{"name": "extra", "status": "completed", "conclusion": "success"}], green + [green[0]],
                        [{"name": name, "status": "queued", "conclusion": None} for name in expected],
                        [{"name": name, "status": "in_progress", "conclusion": None} for name in expected]]
        for conclusion in ("cancelled", "skipped", "timed_out"):
            invalid_jobs.append([{"name": name, "status": "completed", "conclusion": conclusion} for name in expected])
        for jobs in invalid_jobs:
            with self.subTest(jobs=jobs):
                self.h.jobs = jobs
                with self.assertRaisesRegex(L.StopNeedsHuman, "ci_not_green_for_head"): self.h.lifecycle().observe_ci()
        self.h.jobs = green
        self.assertEqual(self.h.lifecycle().observe_ci()["state"], "CI_GREEN_FOR_HEAD")
        self.assertFalse(any("logs" in path for _, path, _ in self.h.requests))

    def test_p4_deferred_cas_rejects_state_contract_and_remote_drift(self):
        self._published_state_with_stored_pr()
        life = self.h.lifecycle(); _, expected = life._guard(); deferred = dict(expected, ci_sha=SHA)
        state_path = self.h.state / "life-1/state.json"
        changed = dict(expected, ci_sha="b" * 40); state_path.write_text(json.dumps(changed), encoding="utf-8")
        with self.assertRaisesRegex(L.StopNeedsHuman, "state_changed_before_commit"):
            life._commit_deferred_ci_state(expected, expected["fingerprint"], SHA, deferred)
        self.assertEqual(json.loads(state_path.read_text(encoding="utf-8")), changed)
        state_path.write_text(json.dumps(expected), encoding="utf-8")
        altered = contract(pr_title="changed"); (self.contract_root / "life-1.json").write_text(json.dumps(altered), encoding="utf-8")
        with self.assertRaisesRegex(L.StopNeedsHuman, "contract_fingerprint_divergent"):
            life._commit_deferred_ci_state(expected, expected["fingerprint"], SHA, deferred)
        (self.contract_root / "life-1.json").write_text(json.dumps(self.h.data), encoding="utf-8")
        self.h.remote_sha = "b" * 40
        with self.assertRaisesRegex(L.StopNeedsHuman, "remote_head_drift"):
            life._commit_deferred_ci_state(expected, expected["fingerprint"], SHA, deferred)

    def test_correction_p2_latches_then_publishes_same_pr_and_clears_pending(self):
        self.preflight(); life = self.h.lifecycle(); life.publish_head(); life.ensure_pr()
        self.h.head = "b" * 40
        self.h.committed = [("M", "docs/EVIDENCE.md")]
        state_path = self.h.state / "life-1/state.json"
        current = json.loads(state_path.read_text(encoding="utf-8"))
        current.update({"pending_correction_sha": self.h.head, "pending_publish_attempted": False,
                        "ci_failure": {"head_sha": SHA, "pr_number": 7, "workflow_run_id": 5,
                                       "jobs": {"Repository validation": "failure", "Enricher tests": "success", "Web tests": "success"}}})
        state_path.write_text(json.dumps(current), encoding="utf-8")
        self.assertEqual(life.publish_head()["state"], "PUBLISHED")
        final = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(final["head_sha"], self.h.head)
        self.assertEqual(final["corrections"], 1)
        self.assertFalse(final["pending_publish_attempted"])
        self.assertIsNone(final["pending_correction_sha"])
        self.assertIsNone(final["ci_failure"])

    def test_correction_p2_rejects_dirty_or_duplicate_same_head_pr_before_push(self):
        self.preflight(); life = self.h.lifecycle(); life.publish_head(); life.ensure_pr()
        self.h.head = "b" * 40; self.h.committed = [("M", "docs/EVIDENCE.md")]
        state_path = self.h.state / "life-1/state.json"; current = json.loads(state_path.read_text(encoding="utf-8"))
        current.update({"pending_correction_sha": self.h.head, "pending_publish_attempted": False}); state_path.write_text(json.dumps(current), encoding="utf-8")
        self.h.changed = ["docs/EVIDENCE.md"]
        with self.assertRaisesRegex(L.StopNeedsHuman, "worktree_not_clean"): life.publish_head()
        self.h.changed = []; self.h.same_head_responses = [[self.h.pr, self.h.pr]]
        with self.assertRaisesRegex(L.StopNeedsHuman, "pr_count_rejected"): life.publish_head()

    def test_p2_and_p4_share_one_reservation(self):
        self._published_state_with_stored_pr()
        entered, release = threading.Event(), threading.Event()
        original = self.h.request
        def blocking(method, path, payload=None):
            if "actions/runs?" in path:
                entered.set(); self.assertTrue(release.wait(timeout=2))
            return original(method, path, payload)
        result = []
        thread = threading.Thread(target=lambda: result.append(L.Lifecycle(self.h.root, "life-1", state_root=self.h.state, runner=self.h.runner, request=blocking).observe_ci()))
        thread.start(); self.assertTrue(entered.wait(timeout=2))
        with self.assertRaisesRegex(L.StopNeedsHuman, "publish_reservation_locked"):
            self.h.lifecycle().publish_head()
        release.set(); thread.join(timeout=2)
        self.assertFalse(thread.is_alive()); self.assertEqual(result[0]["state"], "CI_GREEN_FOR_HEAD")

    def test_p2_reservation_blocks_p4_observation(self):
        h = Harness(self.root / "p2-blocks-p4", self.state / "p2-blocks-p4", contract())
        h.lifecycle().preflight()
        entered, release = threading.Event(), threading.Event()
        original_runner = h.runner
        def blocking_runner(command, cwd):
            if command[1:2] == ["push"]:
                entered.set(); self.assertTrue(release.wait(timeout=2))
            return original_runner(command, cwd)
        result = []
        thread = threading.Thread(target=lambda: result.append(L.Lifecycle(h.root, "life-1", state_root=h.state, runner=blocking_runner, request=h.request).publish_head()))
        thread.start(); self.assertTrue(entered.wait(timeout=2))
        with self.assertRaisesRegex(L.StopNeedsHuman, "publish_reservation_locked"):
            h.lifecycle().observe_ci()
        release.set(); thread.join(timeout=2)
        self.assertFalse(thread.is_alive()); self.assertEqual(result[0]["state"], "PUBLISHED")

    def test_refresh_requires_opt_in_and_conflict_stops(self):
        self.preflight()
        with self.assertRaisesRegex(L.StopNeedsHuman, "safe_refresh_not_allowed"): self.h.lifecycle().refresh_from_dev()
        h = Harness(self.root / "refresh", self.state / "refresh", contract(allow_safe_refresh=True))
        h.lifecycle().preflight()
        def conflict(command, cwd):
            if command[1:2] == ["merge"]: raise L.StopNeedsHuman("git_command_rejected")
            return h.runner(command, cwd)
        with self.assertRaisesRegex(L.StopNeedsHuman, "git_command_rejected"): L.Lifecycle(h.root, "life-1", state_root=h.state, runner=conflict, request=h.request).refresh_from_dev()

    def test_refresh_keeps_last_published_head_for_next_publish_range(self):
        h = Harness(self.root / "refresh-range", self.state / "refresh-range", contract(allow_safe_refresh=True))
        h.lifecycle().preflight()
        h.head = "b" * 40
        h.lifecycle().refresh_from_dev()
        state = json.loads((h.state / "life-1/state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["head_sha"], SHA)
        self.assertIsNone(state["ci_sha"])

    def test_token_profiles_reject_read_write_scope_or_administration(self):
        valid = {"permissions": {"pull_requests":"read", "actions":"read", "statuses":"read", "metadata":"read"}, "repository": L.REPOSITORY, "administration": False}
        L.TokenProfiles.validate("observe", valid)
        for changed in ({"permissions": {"pull_requests":"write", "actions":"read", "statuses":"read", "metadata":"read"}, "repository": L.REPOSITORY, "administration": False}, {"permissions": valid["permissions"], "repository": "other/repo", "administration": False}, {"permissions": valid["permissions"], "repository": L.REPOSITORY, "administration": True}):
            with self.assertRaises(L.StopNeedsHuman): L.TokenProfiles.validate("observe", changed)

    def test_revocation_and_cleanup_fail_closed_without_token_reuse(self):
        minted = {"permissions": {"contents": "write", "metadata": "read"}, "repository": L.REPOSITORY, "administration": False, "token": "fixture"}
        with self.assertRaisesRegex(L.StopNeedsHuman, "revocation_failed"):
            L._run_ephemeral_token_operation("publish", lambda purpose: minted, lambda token: False, lambda: True, lambda token: "done")
        with self.assertRaisesRegex(L.StopNeedsHuman, "cleanup_failed"):
            L._run_ephemeral_token_operation("publish", lambda purpose: minted, lambda token: True, lambda: False, lambda token: "done")

    def test_sanitize_logs_is_inert_and_bounded(self):
        value = L.sanitize_log("$(rm -rf /)\x00" + "x" * 3000)
        self.assertIn("$(rm -rf /)?", value); self.assertEqual(len(value), 2000)


class RunAuthorizationSecurityCoverageTests(unittest.TestCase):
    setUp = LifecycleTests.setUp
    tearDown = LifecycleTests.tearDown
    preflight = LifecycleTests.preflight
    trusted_lstat = LifecycleTests.trusted_lstat
    trusted_fstat = LifecycleTests.trusted_fstat

    def _authorization_path(self) -> Path:
        return self.authorization_root / "run-authorization-1.json"

    def _write_authorization(self, **changes):
        value = run_authorization(self.h.data, **changes)
        self._authorization_path().write_text(json.dumps(value), encoding="utf-8")
        return value

    def test_run_authorization_ttl_and_timestamp_boundaries(self):
        cases = (
            ({"issued_at": "2026-01-01T12:00:00Z", "expires_at": "2026-01-02T12:00:01Z"}, "run_authorization_ttl_exceeded"),
            ({"issued_at": "2026-01-01T12:00:00Z", "expires_at": "2026-01-01T12:00:00Z"}, "run_authorization_time_rejected"),
            ({"issued_at": "2026-01-01T12:00:01Z", "expires_at": "2026-01-01T13:00:00Z"}, "run_authorization_not_yet_valid"),
            ({"issued_at": "2026-01-01T11:00:00Z", "expires_at": "2026-01-01T12:00:00Z"}, "run_authorization_expired"),
            ({"issued_at": "2026-01-01T13:00:00Z", "expires_at": "2026-01-01T12:00:00Z"}, "run_authorization_time_rejected"),
            ({"issued_at": "2026-01-01T12:00:00+00:00"}, "run_authorization_time_rejected"),
            ({"issued_at": "2026-01-01T12:00:00"}, "run_authorization_time_rejected"),
            ({"issued_at": "2026-01-01T12:00:00.000Z"}, "run_authorization_time_rejected"),
            ({"issued_at": "not-a-time"}, "run_authorization_time_rejected"),
            ({"issued_at": "2026-02-30T12:00:00Z"}, "run_authorization_time_rejected"),
        )
        for changes, code in cases:
            with self.subTest(changes=changes):
                self._write_authorization(**changes)
                with self.assertRaisesRegex(L.StopNeedsHuman, code):
                    self.preflight()
        self._write_authorization(issued_at="2025-12-31T12:00:01Z", expires_at="2026-01-01T12:00:01Z")
        self.h.lifecycle()._read_authorization("run-authorization-1", L.fingerprint(self.h.data))
        self._write_authorization(issued_at="2026-01-01T12:00:00Z", expires_at="2026-01-02T12:00:00Z")
        self.assertEqual(self.preflight()["state"], "PREFLIGHT_OK")

    def test_run_authorization_trust_chain_and_identifier_rejection(self):
        lifecycle = self.h.lifecycle()
        self.assertEqual(lifecycle._trusted_authorization_path("run-authorization-1"), self._authorization_path())
        for parent, mode in ((self.authorization_root.parent, 0o775), (self.authorization_root.parent, 0o777),
                             (self.authorization_root, 0o775)):
            with self.subTest(parent=parent, mode=oct(mode)):
                self.contract_metadata[parent] = {"mode": mode}
                with self.assertRaisesRegex(L.StopNeedsHuman, "run_authorization_trust_rejected"):
                    lifecycle._trusted_authorization_path("run-authorization-1")
                self.contract_metadata.pop(parent)
        for metadata in ({"mode": 0o664}, {"uid": 1000}):
            with self.subTest(metadata=metadata):
                self.contract_metadata[self._authorization_path()] = metadata
                with self.assertRaisesRegex(L.StopNeedsHuman, "run_authorization_trust_rejected"):
                    lifecycle._trusted_authorization_path("run-authorization-1")
                self.contract_metadata.pop(self._authorization_path())
        target = self.authorization_root / "target.json"
        target.write_text(json.dumps(run_authorization(self.h.data)), encoding="utf-8")
        self._authorization_path().unlink()
        self._authorization_path().symlink_to(target)
        with self.assertRaisesRegex(L.StopNeedsHuman, "run_authorization_trust_rejected"):
            lifecycle._trusted_authorization_path("run-authorization-1")
        self._authorization_path().unlink()
        self._authorization_path().mkdir()
        with self.assertRaisesRegex(L.StopNeedsHuman, "run_authorization_trust_rejected"):
            lifecycle._trusted_authorization_path("run-authorization-1")
        for identifier in ("../run", "run/authorization", "", "A" * 65):
            with self.subTest(identifier=identifier):
                with self.assertRaisesRegex(L.StopNeedsHuman, "run_authorization_schema_rejected"):
                    lifecycle._authorization_path(identifier)

    def test_run_authorization_strict_json_and_operation_schema(self):
        cases = (
            ({"extra": "denied"}, "run_authorization_schema_rejected"),
            ({"allowed_operations": []}, "run_authorization_schema_rejected"),
            ({"allowed_operations": ["preflight", "preflight"]}, "run_authorization_schema_rejected"),
            ({"allowed_operations": ["preflight", "merge"]}, "run_authorization_schema_rejected"),
            ({"authorization_id": 1}, "run_authorization_schema_rejected"),
            ({"lifecycle_id": 1}, "run_authorization_schema_rejected"),
            ({"task_contract_fingerprint": 1}, "run_authorization_schema_rejected"),
            ({"allowed_operations": "preflight"}, "run_authorization_schema_rejected"),
            ({"issued_at": 1}, "run_authorization_time_rejected"),
            ({"expires_at": 1}, "run_authorization_time_rejected"),
        )
        for changes, code in cases:
            with self.subTest(changes=changes):
                self._write_authorization(**changes)
                with self.assertRaisesRegex(L.StopNeedsHuman, code):
                    self.preflight()
        duplicate = json.dumps(run_authorization(self.h.data), separators=(",", ":"))
        duplicate = duplicate.replace('"version":1', '"version":1,"version":1', 1)
        self._authorization_path().write_text(duplicate, encoding="utf-8")
        with self.assertRaisesRegex(L.StopNeedsHuman, "run_authorization_schema_rejected"):
            self.preflight()
    def test_fingerprint_contract_legacy_and_rebind_fail_closed(self):
        self.preflight()
        authorization = self._write_authorization(allowed_operations=["report-ready", "preflight"])
        with self.assertRaisesRegex(L.StopNeedsHuman, "run_authorization_fingerprint_divergent"):
            self.h.lifecycle().report_ready()
        state_path = self.h.state / "life-1/state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        replacement = run_authorization(self.h.data, authorization_id="run-authorization-2")
        (self.authorization_root / "run-authorization-2.json").write_text(json.dumps(replacement), encoding="utf-8")
        state["run_authorization_id"] = "run-authorization-2"
        state_path.write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaisesRegex(L.StopNeedsHuman, "run_authorization_binding_divergent"):
            self.h.lifecycle().publish_head()
        self.assertEqual(json.loads(state_path.read_text(encoding="utf-8"))["run_authorization_id"], "run-authorization-2")
        state = {"lifecycle_id": "life-1", "fingerprint": L.fingerprint(self.h.data)}
        state_path.write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaisesRegex(L.StopNeedsHuman, "run_authorization_state_missing"):
            self.h.lifecycle().publish_head()

    def test_authorization_operation_separation_and_ready_stop_replay(self):
        self._write_authorization(allowed_operations=["preflight", "authorize-correction", "finalize-correction"])
        self.preflight()
        with self.assertRaisesRegex(L.StopNeedsHuman, "run_authorization_operation_denied"):
            self.h.lifecycle().publish_head()
        state_path = self.h.state / "life-1/state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["run_status"] = "READY"
        state_path.write_text(json.dumps(state), encoding="utf-8")
        for operation in (self.h.lifecycle().report_ready, self.h.lifecycle().publish_head,
                          self.h.lifecycle().ensure_pr, self.h.lifecycle().observe_ci,
                          self.h.lifecycle().authorize_correction, self.h.lifecycle().finalize_correction):
            with self.subTest(operation=operation.__name__):
                with self.assertRaisesRegex(L.StopNeedsHuman, "run_replay_after_ready"):
                    operation()
        state["run_status"] = "STOPPED"
        state_path.write_text(json.dumps(state), encoding="utf-8")
        for operation in (self.h.lifecycle().report_ready, self.h.lifecycle().publish_head):
            with self.subTest(stopped=operation.__name__):
                with self.assertRaisesRegex(L.StopNeedsHuman, "run_replay_after_stop"):
                    operation()

    def test_ready_uses_local_snapshot_and_no_network_entrypoint(self):
        self.preflight()
        life = self.h.lifecycle()
        life.publish_head(); life.ensure_pr(); life.observe_ci()
        original_runner = self.h.runner

        def local_only(command, cwd):
            if command[1] in {"ls-remote", "fetch", "push"}:
                raise AssertionError("network_git_called")
            return original_runner(command, cwd)

        life.runner = local_only
        life.request = lambda *_: (_ for _ in ()).throw(AssertionError("api_called"))
        with mock.patch.object(L, "_run_ephemeral_token_operation", side_effect=AssertionError("token_called")):
            ready = life.report_ready()
        self.assertEqual(ready["state"], "READY_FOR_HUMAN_MERGE_FOR_SHA=" + SHA)
        self.assertEqual(json.loads((self.h.state / "life-1/state.json").read_text())["run_status"], "READY")

    def test_old_snapshot_cannot_make_new_head_ready(self):
        self.preflight()
        life = self.h.lifecycle()
        life.publish_head(); life.ensure_pr(); life.observe_ci()
        self.h.head = "b" * 40
        with self.assertRaisesRegex(L.StopNeedsHuman, "ci_evidence_stale"):
            life.report_ready()


class InstallationTests(unittest.TestCase):
    def test_clean_install_reinstall_hashes_modes_and_no_unsafe_files(self):
        installer = load("b42_installer", INSTALLER_PATH)
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "profile" / "megabrain-autonomous-pr-lifecycle"
            installer.install(destination, test_only=True); (destination / "stale").write_text("x")
            installer.install(destination, test_only=True)
            symlink_target = Path(temp) / "unsafe-target"
            symlink_target.mkdir()
            symlink_destination = Path(temp) / "unsafe-link"
            symlink_destination.symlink_to(symlink_target, target_is_directory=True)
            with self.assertRaisesRegex(RuntimeError, "destination_rejected"):
                installer.install(symlink_destination, test_only=True)
            parent_link = Path(temp) / "unsafe-parent"
            parent_link.symlink_to(symlink_target, target_is_directory=True)
            with self.assertRaisesRegex(RuntimeError, "destination_rejected"):
                installer.install(parent_link / "megabrain-autonomous-pr-lifecycle", test_only=True)
            expected = installer.ARTIFACTS
            files = {p.relative_to(destination) for p in destination.rglob("*") if p.is_file()}
            self.assertEqual(files, set(expected))
            for relative, mode in expected.items():
                self.assertEqual(hashlib.sha256((SKILL / relative).read_bytes()).digest(), hashlib.sha256((destination / relative).read_bytes()).digest())
                self.assertEqual(stat.S_IMODE((destination / relative).stat().st_mode), mode)
            self.assertFalse(any(p.suffix in {".pem", ".key"} or p.name == ".env" for p in files))


if __name__ == "__main__": unittest.main()
