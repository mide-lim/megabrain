"""Hermetic tests for the fixed B4.2 P3 controlled ensure-pr adapter."""
from __future__ import annotations

import copy
import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SKILL = Path(__file__).resolve().parents[1]
MODULE_PATH = SKILL / "scripts" / "authenticated_ensure_pr.py"
SHA = "a" * 40
BRANCH = "agent/b4-2-controlled-pr"


def load(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


ENSURE = load("b42_authenticated_ensure_pr", MODULE_PATH)


def contract():
    return {
        "branch": BRANCH,
        "pr_title": "Controlled PR",
        "pr_body": "Contract-bound body",
    }


def state(**changes):
    value = {"fingerprint": "f" * 64, "head_sha": SHA, "published_once": True}
    value.update(changes)
    return value


def pr(number=7, *, base="dev", sha=SHA, body=None, status="open", merged=False):
    return {
        "number": number,
        "state": status,
        "merged": merged,
        "body": body if body is not None else "B4.2-Contract-Fingerprint: " + "f" * 64,
        "head": {"ref": BRANCH, "sha": sha, "repo": {"full_name": ENSURE.REPOSITORY}},
        "base": {"ref": base, "repo": {"full_name": ENSURE.REPOSITORY}},
    }


class FakeLifecycle:
    data = contract()
    current_state = state()
    existing_prs = []
    returned_pr = pr()
    ensure_failure: str | None = None
    state_writes = []
    remote_checks = 0

    def __init__(self, root, lifecycle_id):
        self.root = root
        self.lifecycle_id = lifecycle_id
        self.runner = None
        self.request = None

    def _guard(self):
        return copy.deepcopy(self.data), copy.deepcopy(self.current_state)

    def _validate_checkout(self, value):
        self.last_checkout_contract = value
        return SHA

    def _validate_remote_head(self, value, sha):
        assert value["branch"] == BRANCH
        assert sha == SHA
        type(self).remote_checks += 1

    def _ensure_pr_locked(self, *, state_writer=None):
        assert self.request is not None
        active_contract, active_state = self._guard()
        listing_path = f"/repos/{ENSURE.REPOSITORY}/pulls?state=all&head=mide-lim:{BRANCH}"
        listed = self.request("GET", listing_path)
        if not isinstance(listed, list):
            raise ENSURE.LIFECYCLE.StopNeedsHuman("pr_drift_rejected")
        if len(listed) > 1:
            raise ENSURE.LIFECYCLE.StopNeedsHuman("pr_count_rejected")
        if listed:
            selected = listed[0]
        else:
            selected = self.request("POST", f"/repos/{ENSURE.REPOSITORY}/pulls", ENSURE._expected_create_payload(active_contract, active_state))
        if self.ensure_failure is not None:
            raise ENSURE.LIFECYCLE.StopNeedsHuman(self.ensure_failure)
        self._validate_remote_head(active_contract, SHA)
        if not isinstance(selected, dict) or type(selected.get("number")) is not int:
            raise ENSURE.LIFECYCLE.StopNeedsHuman("pr_drift_rejected")
        active_state["pr_number"] = selected["number"]
        assert state_writer is not None
        state_writer(active_state)
        return {"state": "PR_OPEN", "pr_number": selected["number"], "head_sha": SHA}

    def _write_state(self, value):
        type(self).state_writes.append(copy.deepcopy(value))


class AuthenticatedEnsurePrTests(unittest.TestCase):
    def setUp(self):
        self.environment = {
            "MEGABRAIN_GITHUB_APP_ID": "123",
            "MEGABRAIN_GITHUB_APP_INSTALLATION_ID": "456",
            "MEGABRAIN_GITHUB_APP_KEY_PATH": "/not/a/real/key",
        }
        FakeLifecycle.data = contract()
        FakeLifecycle.current_state = state()
        FakeLifecycle.existing_prs = []
        FakeLifecycle.returned_pr = pr()
        FakeLifecycle.ensure_failure = None
        FakeLifecycle.state_writes = []
        FakeLifecycle.remote_checks = 0

    def api_success(self, method, path, authorization, payload=None):
        if method == "GET" and path == "/app/installations/456":
            self.assertEqual(authorization, "Bearer JWT_FIXTURE")
            return 200, {"permissions": ENSURE.EXPECTED_INSTALLATION_PERMISSIONS}
        if method == "POST" and path == "/app/installations/456/access_tokens":
            self.assertEqual(authorization, "Bearer JWT_FIXTURE")
            self.assertEqual(payload, {"repositories": ["megabrain"], "permissions": {"pull_requests": "write"}})
            return 201, {"token": "TOKEN_FIXTURE", "permissions": {"pull_requests": "write", "metadata": "read"}}
        if method == "GET" and path == "/installation/repositories":
            self.assertEqual(authorization, "token TOKEN_FIXTURE")
            return 200, {"total_count": 1, "repositories": [{"full_name": ENSURE.REPOSITORY}]}
        if method == "GET" and "pulls?state=all&head=" in path:
            self.assertEqual(authorization, "token TOKEN_FIXTURE")
            return 200, copy.deepcopy(FakeLifecycle.existing_prs)
        if method == "POST" and path == f"/repos/{ENSURE.REPOSITORY}/pulls":
            self.assertEqual(authorization, "token TOKEN_FIXTURE")
            self.assertEqual(payload, ENSURE._expected_create_payload(FakeLifecycle.data, FakeLifecycle.current_state))
            return 201, copy.deepcopy(FakeLifecycle.returned_pr)
        if method == "DELETE" and path == "/installation/token":
            self.assertEqual(authorization, "token TOKEN_FIXTURE")
            return 204, {}
        self.fail(f"unexpected request: {method} {path}")

    def patches(self, api=None):
        return (
            mock.patch.object(ENSURE, "configured_origin", return_value=ENSURE.ORIGIN),
            mock.patch.object(ENSURE, "validate_privileged_executable"),
            mock.patch.object(ENSURE, "validate_key_path"),
            mock.patch.object(ENSURE, "make_jwt", return_value="JWT_FIXTURE"),
            mock.patch.object(ENSURE, "request_json", side_effect=api or self.api_success),
            mock.patch.object(ENSURE.LIFECYCLE, "Lifecycle", FakeLifecycle),
        )

    def run_success(self, api=None):
        patches = self.patches(api)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            return ENSURE.run_operation(ENSURE.OPERATION, "life-1", True, self.environment)

    def test_exact_pr_token_scope_create_payload_and_sanitized_result(self):
        result = self.run_success()
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["contract_valid"])
        self.assertTrue(result["preconditions_valid"])
        self.assertTrue(result["pr_token_permissions_valid"])
        self.assertTrue(result["scope_valid"])
        self.assertEqual(result["pr_number"], 7)
        self.assertEqual(result["remote_sha_verified"], SHA)
        self.assertEqual(result["revocation"], "ok")
        self.assertTrue(result["temporary_cleanup"])
        self.assertEqual(FakeLifecycle.state_writes, [dict(state(), pr_number=7)])
        encoded = json.dumps(result, sort_keys=True)
        self.assertNotIn("TOKEN_FIXTURE", encoded)
        self.assertNotIn("JWT_FIXTURE", encoded)
        self.assertNotIn(self.environment["MEGABRAIN_GITHUB_APP_KEY_PATH"], encoded)

    def test_missing_gate_and_wrong_operation_do_not_authenticate(self):
        with mock.patch.object(ENSURE, "configured_origin") as origin:
            gated = ENSURE.run_operation(ENSURE.OPERATION, "life-1", False, self.environment)
            wrong = ENSURE.run_operation("publish-head", "life-1", True, self.environment)
        origin.assert_not_called()
        self.assertEqual(gated["failure_code"], "operational_gate_required")
        self.assertEqual(wrong["failure_code"], "operation_rejected")

    def test_wrong_or_extra_permissions_and_scope_are_rejected(self):
        for permissions in (
            {"pull_requests": "read"},
            {"pull_requests": "write", "contents": "write"},
            {"pull_requests": "write", "metadata": "write"},
            {"pull_requests": "write", "administration": "read"},
        ):
            with self.subTest(permissions=permissions):
                self.assertFalse(ENSURE._valid_pr_token_permissions(permissions))
        self.assertTrue(ENSURE._valid_pr_token_permissions({"pull_requests": "write"}))
        self.assertTrue(ENSURE._valid_pr_token_permissions({"pull_requests": "write", "metadata": "read"}))
        self.assertFalse(ENSURE._valid_scope({"total_count": 2, "repositories": [{"full_name": ENSURE.REPOSITORY}, {"full_name": "other/repo"}]}))
        self.assertFalse(ENSURE._valid_scope({"total_count": 1, "repositories": [{"full_name": "other/repo"}]}))

    def test_unpublished_and_local_state_divergence_stop_before_authentication(self):
        for changed, expected in (({"published_once": False}, "publication_required"), ({"head_sha": "b" * 40}, "publish_required")):
            with self.subTest(changed=changed):
                FakeLifecycle.current_state = state(**changed)
                patches = self.patches()
                with patches[0], patches[1], patches[2], patches[3] as signer, patches[4], patches[5]:
                    result = ENSURE.run_operation(ENSURE.OPERATION, "life-1", True, self.environment)
                signer.assert_not_called()
                self.assertEqual(result["failure_code"], expected)
                self.assertFalse(FakeLifecycle.state_writes)

    def test_remote_drift_stops_before_authentication(self):
        with mock.patch.object(ENSURE, "validate_source_for_ensure_pr", side_effect=ENSURE.LIFECYCLE.StopNeedsHuman("remote_head_drift")), mock.patch.object(ENSURE, "make_jwt") as signer, mock.patch.object(ENSURE.LIFECYCLE, "Lifecycle", FakeLifecycle), mock.patch.object(ENSURE, "configured_origin", return_value=ENSURE.ORIGIN), mock.patch.object(ENSURE, "validate_privileged_executable"), mock.patch.object(ENSURE, "validate_key_path"):
            result = ENSURE.run_operation(ENSURE.OPERATION, "life-1", True, self.environment)
        signer.assert_not_called()
        self.assertEqual(result["failure_code"], "remote_head_drift")

    def test_existing_valid_pr_is_reused_and_duplicates_fail_closed(self):
        FakeLifecycle.existing_prs = [pr(11)]
        result = self.run_success()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["pr_number"], 11)
        self.assertEqual(FakeLifecycle.state_writes[-1]["pr_number"], 11)
        FakeLifecycle.state_writes = []
        FakeLifecycle.existing_prs = [pr(11), pr(12)]
        result = self.run_success()
        self.assertEqual(result["failure_code"], "pr_count_rejected")
        self.assertFalse(FakeLifecycle.state_writes)

    def test_terminal_and_drift_prs_fail_without_state_commit(self):
        for selected, code in (
            (pr(base="main"), "pr_drift_rejected"),
            (pr(sha="b" * 40), "pr_drift_rejected"),
            (pr(status="closed"), "pr_terminal_state"),
            (pr(status="closed", merged=True), "pr_terminal_state"),
            (pr(body="unbound"), "pr_fingerprint_rejected"),
        ):
            with self.subTest(selected=selected):
                FakeLifecycle.state_writes = []
                FakeLifecycle.existing_prs = [selected]
                FakeLifecycle.ensure_failure = code
                result = self.run_success()
                self.assertEqual(result["failure_code"], code)
                self.assertFalse(FakeLifecycle.state_writes)
                FakeLifecycle.ensure_failure = None

    def test_api_boundary_rejects_arbitrary_endpoint_and_mutating_methods(self):
        request = ENSURE.authenticated_pr_request("TOKEN_FIXTURE", contract(), state())
        for method, path, payload in (
            ("PATCH", f"/repos/{ENSURE.REPOSITORY}/pulls/7", {}),
            ("PUT", f"/repos/{ENSURE.REPOSITORY}/pulls/7", {}),
            ("DELETE", f"/repos/{ENSURE.REPOSITORY}/pulls/7", None),
            ("POST", f"/repos/{ENSURE.REPOSITORY}/pulls/7/merge", {}),
            ("POST", f"/repos/{ENSURE.REPOSITORY}/pulls/7/reviews", {}),
            ("POST", f"/repos/{ENSURE.REPOSITORY}/issues/7/comments", {}),
            ("GET", f"/repos/{ENSURE.REPOSITORY}/actions/runs", None),
            ("POST", "/repos/other/repo/pulls", {}),
            ("POST", f"/repos/{ENSURE.REPOSITORY}/pulls", {"title": "caller supplied"}),
        ):
            with self.subTest(method=method, path=path):
                with self.assertRaisesRegex(ENSURE.LIFECYCLE.StopNeedsHuman, "api_request_rejected"):
                    request(method, path, payload)

    def test_post_api_remote_drift_and_teardown_failures_do_not_commit_state(self):
        FakeLifecycle.ensure_failure = "remote_head_drift"
        result = self.run_success()
        self.assertEqual(result["failure_code"], "remote_head_drift")
        self.assertFalse(FakeLifecycle.state_writes)

        def revocation_fails(method, path, authorization, payload=None):
            if method == "DELETE":
                return 500, {}
            return self.api_success(method, path, authorization, payload)
        FakeLifecycle.ensure_failure = None
        result = self.run_success(revocation_fails)
        self.assertEqual(result["failure_code"], "revocation_failed")
        self.assertFalse(FakeLifecycle.state_writes)

        class BrokenTemporaryDirectory:
            name = "/fixture/tmp"
            def cleanup(self):
                raise OSError("fixture")
        patches = self.patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], mock.patch.object(ENSURE.tempfile, "TemporaryDirectory", return_value=BrokenTemporaryDirectory()):
            result = ENSURE.run_operation(ENSURE.OPERATION, "life-1", True, self.environment)
        self.assertEqual(result["failure_code"], "cleanup_failed")
        self.assertFalse(FakeLifecycle.state_writes)

    def test_fixed_git_and_openssl_ignore_malicious_path_and_never_receive_token(self):
        command = ["git", "ls-remote", "origin", f"refs/heads/{BRANCH}"]
        completed = subprocess.CompletedProcess(command, 0, f"{SHA}\t{command[-1]}\n", "")
        with mock.patch.dict(ENSURE.os.environ, {"PATH": "/fixture/malicious-bin", "MEGABRAIN_GITHUB_APP_TOKEN": "TOKEN_FIXTURE"}, clear=True), mock.patch.object(ENSURE, "validate_privileged_executable"), mock.patch.object(ENSURE.subprocess, "run", return_value=completed) as execute:
            self.assertEqual(ENSURE.source_runner("/fixture/home", BRANCH)(command, Path("/fixture/repo")), f"{SHA}\t{command[-1]}")
        invoked = execute.call_args.args[0]
        environment = execute.call_args.kwargs["env"]
        self.assertEqual(invoked[0], ENSURE.GIT_BINARY)
        self.assertNotIn("PATH", environment)
        self.assertNotIn("MEGABRAIN_GITHUB_APP_TOKEN", environment)
        self.assertNotIn("GIT_ASKPASS", environment)

        signed = subprocess.CompletedProcess([ENSURE.OPENSSL_BINARY], 0, b"signature", b"")
        with mock.patch.object(ENSURE, "validate_privileged_executable") as validate, mock.patch.object(ENSURE.subprocess, "run", return_value=signed) as execute:
            ENSURE.make_jwt("123", "/fixture/key", now=1_700_000_000)
        validate.assert_called_once_with(ENSURE.OPENSSL_BINARY)
        self.assertEqual(execute.call_args.args[0], [ENSURE.OPENSSL_BINARY, "dgst", "-sha256", "-sign", "/fixture/key"])

    def test_privileged_executable_validation_requires_exact_root_owned_regular_nonwritable_paths(self):
        valid = os.stat_result((stat.S_IFREG | 0o755, 0, 0, 0, 0, 0, 0, 0, 0, 0))
        with mock.patch.object(ENSURE.os, "lstat", return_value=valid):
            ENSURE.validate_privileged_executable(ENSURE.GIT_BINARY)
            ENSURE.validate_privileged_executable(ENSURE.OPENSSL_BINARY)
        for invalid in (
            os.stat_result((stat.S_IFLNK | 0o777, 0, 0, 0, 0, 0, 0, 0, 0, 0)),
            os.stat_result((stat.S_IFREG | 0o755, 0, 0, 0, 1000, 0, 0, 0, 0, 0)),
            os.stat_result((stat.S_IFREG | 0o775, 0, 0, 0, 0, 0, 0, 0, 0, 0)),
            os.stat_result((stat.S_IFREG | 0o644, 0, 0, 0, 0, 0, 0, 0, 0, 0)),
        ):
            with self.subTest(mode=invalid.st_mode, uid=invalid.st_uid), mock.patch.object(ENSURE.os, "lstat", return_value=invalid):
                with self.assertRaisesRegex(ENSURE.SafeFailure, "privileged_executable_invalid"):
                    ENSURE.validate_privileged_executable(ENSURE.GIT_BINARY)
        with self.assertRaisesRegex(ENSURE.SafeFailure, "privileged_executable_invalid"):
            ENSURE.validate_privileged_executable("git")


if __name__ == "__main__":
    unittest.main()
