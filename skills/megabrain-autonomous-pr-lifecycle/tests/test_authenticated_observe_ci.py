"""Hermetic tests for the fixed B4.2 P4 controlled CI observation adapter."""
from __future__ import annotations

import copy
import importlib.util
import json
import os
import stat
import subprocess
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

SKILL = Path(__file__).resolve().parents[1]
MODULE_PATH = SKILL / "scripts" / "authenticated_observe_ci.py"
SHA = "a" * 40
BRANCH = "agent/b4-2-ci-observation"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


OBSERVE = load("b42_authenticated_observe_ci", MODULE_PATH)


def contract():
    return {"branch": BRANCH, "expected_ci_jobs": ["Repository validation", "Enricher tests", "Web tests"]}


def state(**changes):
    value = {"fingerprint": "f" * 64, "head_sha": SHA, "published_once": True, "pr_number": 7}
    value.update(changes)
    return value


class FakeLifecycle:
    data = contract()
    current_state = state()
    writes = []
    failure: str | None = None
    observed_jobs: dict[str, str] | None = None

    def __init__(self, root, lifecycle_id):
        self.root, self.lifecycle_id, self.runner, self.request = root, lifecycle_id, None, None

    @contextmanager
    def _publish_reservation(self):
        yield

    def _guard(self):
        return copy.deepcopy(self.data), copy.deepcopy(self.current_state)

    def _validate_checkout(self, value):
        return SHA

    def _validate_remote_head(self, value, sha):
        assert value["branch"] == BRANCH and sha == SHA

    def _observe_ci_locked(self, *, state_writer=None):
        assert self.request is not None
        if type(self).failure:
            raise OBSERVE.LIFECYCLE.StopNeedsHuman(type(self).failure)
        pr = self.request("GET", f"/repos/{OBSERVE.REPOSITORY}/pulls/7")
        runs = self.request("GET", f"/repos/{OBSERVE.REPOSITORY}/actions/runs?event=pull_request&head_sha={SHA}")
        run_id = runs["workflow_runs"][0]["id"]
        self.request("GET", f"/repos/{OBSERVE.REPOSITORY}/actions/runs/{run_id}/jobs")
        deferred = dict(self.current_state, ci_sha=SHA)
        assert state_writer is not None
        state_writer(deferred)
        return {"state": "CI_GREEN", "head_sha": SHA, "workflow_run_id": run_id,
                "jobs": type(self).observed_jobs or {name: "success" for name in self.data["expected_ci_jobs"]}}

    def _commit_deferred_ci_state(self, expected, fingerprint, head, deferred):
        assert expected == self.current_state and fingerprint == self.current_state["fingerprint"] and head == SHA
        type(self).writes.append(copy.deepcopy(deferred))


class ObserveAdapterTests(unittest.TestCase):
    def setUp(self):
        self.environment = {"MEGABRAIN_GITHUB_APP_ID": "123", "MEGABRAIN_GITHUB_APP_INSTALLATION_ID": "456", "MEGABRAIN_GITHUB_APP_KEY_PATH": "/fixture/key"}
        FakeLifecycle.data, FakeLifecycle.current_state, FakeLifecycle.writes, FakeLifecycle.failure, FakeLifecycle.observed_jobs = contract(), state(), [], None, None

    def api(self, method, path, authorization, payload=None):
        if method == "GET" and path == "/app/installations/456":
            self.assertEqual(authorization, "Bearer JWT_FIXTURE")
            return 200, {"permissions": OBSERVE.EXPECTED_INSTALLATION_PERMISSIONS}
        if method == "POST" and path == "/app/installations/456/access_tokens":
            self.assertEqual(payload, {"repositories": ["megabrain"], "permissions": OBSERVE.OBSERVE_TOKEN_REQUEST_PERMISSIONS})
            return 201, {"token": "TOKEN_FIXTURE", "permissions": OBSERVE.OBSERVE_TOKEN_REQUEST_PERMISSIONS}
        if method == "GET" and path == "/installation/repositories":
            return 200, {"total_count": 1, "repositories": [{"full_name": OBSERVE.REPOSITORY}]}
        if method == "GET" and path.endswith("/pulls/7"):
            return 200, {"number": 7}
        if method == "GET" and "actions/runs?" in path:
            return 200, {"workflow_runs": [{"id": 5, "event": "pull_request", "head_sha": SHA, "pull_requests": [{"number": 7}]}]}
        if method == "GET" and path.endswith("/actions/runs/5/jobs"):
            return 200, {"jobs": []}
        if method == "DELETE" and path == "/installation/token":
            return 204, {}
        self.fail((method, path, payload))

    def patches(self, api=None):
        return (mock.patch.object(OBSERVE, "configured_origin", return_value=OBSERVE.ORIGIN),
                mock.patch.object(OBSERVE, "validate_privileged_executable"), mock.patch.object(OBSERVE, "validate_key_path"),
                mock.patch.object(OBSERVE, "make_jwt", return_value="JWT_FIXTURE"), mock.patch.object(OBSERVE, "request_json", side_effect=api or self.api),
                mock.patch.object(OBSERVE.LIFECYCLE, "Lifecycle", FakeLifecycle))

    def run_adapter(self, api=None):
        patches = self.patches(api)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            return OBSERVE.run_operation("observe-ci", "life-1", True, self.environment)

    def test_exact_observe_scope_and_deferred_commit_after_teardown(self):
        result = self.run_adapter()
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["observe_token_permissions_valid"])
        self.assertEqual(result["workflow_run_id"], 5)
        self.assertEqual(result["jobs"], {"Repository validation": "success", "Enricher tests": "success", "Web tests": "success"})
        self.assertEqual(FakeLifecycle.writes, [dict(state(), ci_sha=SHA)])
        self.assertNotIn("TOKEN_FIXTURE", json.dumps(result))
        self.assertNotIn("JWT_FIXTURE", json.dumps(result))

    def test_run_matching_requires_pull_request_event(self):
        matching = {"workflow_runs": [{"id": 5, "event": "pull_request", "head_sha": SHA, "pull_requests": [{"number": 7}]}]}
        self.assertEqual(OBSERVE._matching_run_ids(matching, SHA, 7), [5])
        for event in ("push", None):
            run = dict(matching["workflow_runs"][0])
            if event is None:
                del run["event"]
            else:
                run["event"] = event
            with self.subTest(event=event):
                self.assertEqual(OBSERVE._matching_run_ids({"workflow_runs": [run]}, SHA, 7), [])

    def test_invalid_observed_jobs_fail_closed_before_state_commit(self):
        FakeLifecycle.observed_jobs = {"Repository validation": "success"}
        result = self.run_adapter()
        self.assertEqual(result["failure_code"], "ci_result_rejected")
        self.assertFalse(FakeLifecycle.writes)

    def test_operation_gate_and_preconditions_stop_before_authentication(self):
        self.assertEqual(OBSERVE.run_operation("ensure-pr", "life-1", True, self.environment)["failure_code"], "operation_rejected")
        self.assertEqual(OBSERVE.run_operation("observe-ci", "life-1", False, self.environment)["failure_code"], "operational_gate_required")
        FakeLifecycle.current_state = state(pr_number=None)
        patches = self.patches()
        with patches[0], patches[1], patches[2], patches[3] as signer, patches[4], patches[5]:
            result = OBSERVE.run_operation("observe-ci", "life-1", True, self.environment)
        signer.assert_not_called(); self.assertEqual(result["failure_code"], "pr_or_head_missing"); self.assertFalse(FakeLifecycle.writes)

    def test_no_commit_on_observation_revocation_or_cleanup_failure(self):
        FakeLifecycle.failure = "ci_not_green_for_head"
        self.assertEqual(self.run_adapter()["failure_code"], "ci_not_green_for_head"); self.assertFalse(FakeLifecycle.writes)
        FakeLifecycle.failure = None
        def revoke_failure(method, path, authorization, payload=None):
            if method == "DELETE": return 500, {}
            return self.api(method, path, authorization, payload)
        self.assertEqual(self.run_adapter(revoke_failure)["failure_code"], "revocation_failed"); self.assertFalse(FakeLifecycle.writes)
        class BrokenTemporaryDirectory:
            name = "/fixture/tmp"
            def cleanup(self): raise OSError("fixture")
        patches = self.patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], mock.patch.object(OBSERVE.tempfile, "TemporaryDirectory", return_value=BrokenTemporaryDirectory()):
            result = OBSERVE.run_operation("observe-ci", "life-1", True, self.environment)
        self.assertEqual(result["failure_code"], "cleanup_failed"); self.assertFalse(FakeLifecycle.writes)

    def test_api_boundary_allows_only_exact_gets_and_never_logs_or_actions_mutations(self):
        request = OBSERVE.authenticated_observe_request("TOKEN_FIXTURE", state())
        for method, path, payload in (("POST", f"/repos/{OBSERVE.REPOSITORY}/actions/runs/5/rerun", {}), ("POST", f"/repos/{OBSERVE.REPOSITORY}/actions/runs/5/cancel", {}), ("POST", f"/repos/{OBSERVE.REPOSITORY}/dispatches", {}), ("PATCH", f"/repos/{OBSERVE.REPOSITORY}/pulls/7", {}), ("POST", f"/repos/{OBSERVE.REPOSITORY}/pulls/7/merge", {}), ("GET", f"/repos/{OBSERVE.REPOSITORY}/actions/runs/5/logs", None), ("GET", f"/repos/{OBSERVE.REPOSITORY}/contents/x", None)):
            with self.subTest(path=path):
                with self.assertRaisesRegex(OBSERVE.LIFECYCLE.StopNeedsHuman, "api_request_rejected"):
                    request(method, path, payload)

    def test_fixed_git_never_receives_token(self):
        command = ["git", "ls-remote", "origin", f"refs/heads/{BRANCH}"]
        completed = subprocess.CompletedProcess(command, 0, f"{SHA}\t{command[-1]}\n", "")
        with mock.patch.dict(OBSERVE.os.environ, {"MEGABRAIN_GITHUB_APP_TOKEN": "TOKEN_FIXTURE"}, clear=True), mock.patch.object(OBSERVE, "validate_privileged_executable"), mock.patch.object(OBSERVE.subprocess, "run", return_value=completed) as execute:
            OBSERVE.source_runner("/fixture/home", BRANCH)(command, Path("/fixture/repo"))
        self.assertEqual(execute.call_args.args[0][0], OBSERVE.GIT_BINARY)
        environment = execute.call_args.kwargs["env"]
        self.assertNotIn("MEGABRAIN_GITHUB_APP_TOKEN", environment)
        self.assertNotIn("GIT_ASKPASS", environment)

    def test_token_permissions_reject_contents_and_privileged_paths_are_fixed(self):
        self.assertTrue(OBSERVE._valid_observe_token_permissions(OBSERVE.OBSERVE_TOKEN_REQUEST_PERMISSIONS))
        for bad in ({"pull_requests": "read", "actions": "read", "statuses": "read", "contents": "read", "metadata": "read"}, {"pull_requests": "read"}):
            self.assertFalse(OBSERVE._valid_observe_token_permissions(bad))
        valid = os.stat_result((stat.S_IFREG | 0o755, 0, 0, 0, 0, 0, 0, 0, 0, 0))
        with mock.patch.object(OBSERVE.os, "lstat", return_value=valid):
            OBSERVE.validate_privileged_executable(OBSERVE.GIT_BINARY)
            OBSERVE.validate_privileged_executable(OBSERVE.OPENSSL_BINARY)
        with self.assertRaises(OBSERVE.SafeFailure): OBSERVE.validate_privileged_executable("git")


if __name__ == "__main__":
    unittest.main()
