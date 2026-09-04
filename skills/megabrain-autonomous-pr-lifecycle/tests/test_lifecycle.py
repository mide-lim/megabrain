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
        self.tree_modes = {}
        path = root / "contracts/b4.2"
        path.mkdir(parents=True)
        (path / f"{data['lifecycle_id']}.json").write_text(json.dumps(data), encoding="utf-8")
        self.pr = self.pr_body(SHA)
        self.runs_sha = SHA

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
            self.remote_sha = self.head
            return ""
        if args[:1] == ("ls-remote",): return f"{self.remote_sha}\t{args[-1]}"
        if args[:1] in (("fetch",), ("merge",)): return ""
        raise AssertionError(command)

    def request(self, method, path, payload=None):
        self.requests.append((method, path, payload))
        if path.endswith("/pulls?state=all&head=mide-lim:" + self.data["branch"]):
            return (200, [self.pr])
        if path.endswith("/pulls/7"):
            return (200, self.pr)
        if path.endswith("actions/runs?event=pull_request&head_sha=" + SHA):
            return (200, {"workflow_runs": [{"id": 5, "head_sha": self.runs_sha, "pull_requests": [{"number": 7}]}]})
        if path.endswith("/actions/runs/5/jobs"):
            return (200, {"jobs": [{"name": name, "conclusion": "success"} for name in self.data["expected_ci_jobs"]]})
        if method == "POST" and path.endswith("/pulls"):
            return (201, self.pr)
        raise AssertionError((method, path, payload))

    def lifecycle(self):
        return L.Lifecycle(self.root, self.data["lifecycle_id"], state_root=self.state, runner=self.runner, request=self.request)


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "repo"; self.root.mkdir()
        self.state = Path(self.temp.name) / "state"
        self.h = Harness(self.root, self.state, contract())
        self.live = mock.patch.object(L, "_require_live_operations_enabled", return_value=None)
        self.live.start()

    def tearDown(self): self.live.stop(); self.temp.cleanup()

    def preflight(self):
        return self.h.lifecycle().preflight()

    def test_closed_operations_are_exactly_required(self):
        self.assertEqual(L.PUBLIC_OPERATIONS, frozenset({"preflight", "publish-head", "ensure-pr", "observe-ci", "refresh-from-dev", "report-ready"}))
        self.assertEqual(
            {n.replace("_", "-") for n in L.Lifecycle.__dict__ if not n.startswith("_")},
            set(L.PUBLIC_OPERATIONS),
        )

    def test_happy_path_publishes_pr_observes_and_reports_ready(self):
        self.preflight(); life = self.h.lifecycle()
        self.assertEqual(life.publish_head()["state"], "PUBLISHED")
        self.assertEqual(life.ensure_pr()["state"], "PR_OPEN")
        self.assertEqual(life.observe_ci()["state"], "CI_GREEN")
        self.assertEqual(life.report_ready()["state"], "READY")
        push = next(c for c in self.h.commands if c[1] == "push")
        self.assertEqual(push, ["git", "push", "origin", "HEAD:refs/heads/agent/b4-2-autonomous-pr-lifecycle"])
        self.assertFalse(any(any(x in part for x in ("--force", "--delete", "tag")) for c in self.h.commands for part in c))

    def test_default_installation_stops_all_authenticated_operations(self):
        self.live.stop()
        self.preflight()
        with self.assertRaisesRegex(L.StopNeedsHuman, "authenticated_operations_not_authorized"):
            self.h.lifecycle().publish_head()
        self.live.start()

    def test_changed_contract_fingerprint_stops_every_operation(self):
        self.preflight()
        path = self.root / "contracts/b4.2/life-1.json"; altered = contract(pr_title="changed"); path.write_text(json.dumps(altered), encoding="utf-8")
        with self.assertRaisesRegex(L.StopNeedsHuman, "contract_fingerprint_divergent"): self.h.lifecycle().publish_head()

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

    def test_clean_committed_addition_stops_publish_to_prevent_undetected_copy(self):
        h = Harness(self.root / "clean-add", self.state / "clean-add", contract(allowed_paths=["docs/EVIDENCE.md"]), committed=[("A", "docs/EVIDENCE.md")])
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
        for path in ("skills/megabrain-autonomous-pr-lifecycle/scripts/autonomous_pr_lifecycle.py", "skills/megabrain-github-app-auth/scripts/github_app_auth.py", "skills/another-capability/SKILL.md", ".github/workflows/ci.yml", "AGENTS.md", "docs/RISK_POLICY.md", "docs/DEFINITION_OF_DONE.md", "docs/TASK_CONTRACT_X.md", "docs/DEVELOPMENT_WORKFLOW.md"):
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
        with self.assertRaises(L.StopNeedsHuman): L.Lifecycle(linkroot, "life-1", state_root=self.state, runner=self.h.runner).preflight()
        state_target = self.root / "state-target"; state_target.mkdir()
        state_link = self.root / "state-link"; state_link.symlink_to(state_target, target_is_directory=True)
        with self.assertRaisesRegex(L.StopNeedsHuman, "state_root_rejected"):
            L.Lifecycle(self.root, "life-1", state_root=state_link, runner=self.h.runner)

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

    def test_max_corrections_zero_stops_changed_head_before_push(self):
        h = Harness(self.root / "budget-zero", self.state / "budget-zero", contract(max_corrections=0, allowed_paths=["docs/EVIDENCE.md"]), committed=[("M", "docs/EVIDENCE.md")])
        h.lifecycle().preflight()
        h.head = "b" * 40
        with self.assertRaisesRegex(L.StopNeedsHuman, "correction_budget_exhausted"):
            h.lifecycle().publish_head()
        self.assertFalse(any(command[1:2] == ["push"] for command in h.commands))

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

    def test_correction_budget_allows_exact_limit_and_persists_count(self):
        h = Harness(self.root / "budget-exact", self.state / "budget-exact", contract(max_corrections=1, allowed_paths=["docs/EVIDENCE.md"]), committed=[("M", "docs/EVIDENCE.md")])
        h.lifecycle().preflight()
        h.head = "b" * 40
        self.assertEqual(h.lifecycle().publish_head()["state"], "PUBLISHED")
        state = json.loads((h.state / "life-1/state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["corrections"], 1)

    def test_correction_budget_stops_above_limit(self):
        h = Harness(self.root / "budget-over", self.state / "budget-over", contract(max_corrections=1, allowed_paths=["docs/EVIDENCE.md"]), committed=[("M", "docs/EVIDENCE.md")])
        h.lifecycle().preflight()
        h.head = "b" * 40
        h.lifecycle().publish_head()
        h.head = "c" * 40
        with self.assertRaisesRegex(L.StopNeedsHuman, "correction_budget_exhausted"):
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
