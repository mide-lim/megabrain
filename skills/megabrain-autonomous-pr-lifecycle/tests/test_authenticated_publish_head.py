"""Hermetic tests for the fixed B4.2 P2 controlled publish adapter."""
from __future__ import annotations

from contextlib import contextmanager
import importlib.util
import json
import os
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from pathlib import Path
from unittest import mock

SKILL = Path(__file__).resolve().parents[1]
MODULE_PATH = SKILL / "scripts" / "authenticated_publish_head.py"
SHA = "a" * 40
BRANCH = "agent/b4-2-controlled-push"


def load(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


PUBLISH = load("b42_authenticated_publish_head", MODULE_PATH)
REAL_LIFECYCLE = PUBLISH.LIFECYCLE.Lifecycle


class FakeLifecycle:
    branch = BRANCH
    published_sha = SHA
    commands: list[list[str]] = []
    roots: list[Path] = []
    deferred_initial_commits: list[tuple[dict, str, dict]] = []

    def __init__(self, root, lifecycle_id):
        self.root = root
        self.roots.append(root)
        self.lifecycle_id = lifecycle_id
        self.runner = None

    def _guard(self, *args):
        return {"branch": self.branch}, {"head_sha": SHA, "published_once": False, "corrections": 0}

    def _state(self):
        return {"head_sha": SHA, "published_once": False, "corrections": 0}

    def _validate_checkout(self, contract):
        return SHA

    def _validate_committed_paths(self, contract, base, head):
        return None

    def _correction_count(self, contract, state):
        return 0

    @contextmanager
    def _publish_reservation(self):
        yield

    def _publish_head_locked(self, *, state_writer=None):
        assert self.runner is not None
        command = ["git", "push", "origin", f"HEAD:refs/heads/{self.branch}"]
        self.commands.append(command)
        self.runner(command, self.root)
        deferred = {"head_sha": self.published_sha, "published_once": True, "corrections": 0}
        if state_writer is not None:
            state_writer(deferred)
        return {"state": "PUBLISHED", "head_sha": self.published_sha}

    def _commit_deferred_initial_publish_state(self, expected_state, expected_head, deferred_state):
        self.deferred_initial_commits.append((expected_state, expected_head, deferred_state))


class AuthenticatedPublishHeadTests(unittest.TestCase):
    def setUp(self):
        self.environment = {
            "MEGABRAIN_GITHUB_APP_ID": "123",
            "MEGABRAIN_GITHUB_APP_INSTALLATION_ID": "456",
            "MEGABRAIN_GITHUB_APP_KEY_PATH": "/not/a/real/key",
        }
        FakeLifecycle.branch = BRANCH
        FakeLifecycle.published_sha = SHA
        FakeLifecycle.commands = []
        FakeLifecycle.roots = []
        FakeLifecycle.deferred_initial_commits = []

    def api_success(self, method, path, authorization, payload=None):
        if method == "GET" and path == "/app/installations/456":
            self.assertEqual(authorization, "Bearer JWT_FIXTURE")
            self.assertIsNone(payload)
            return 200, {"permissions": PUBLISH.EXPECTED_INSTALLATION_PERMISSIONS}
        if method == "POST" and path == "/app/installations/456/access_tokens":
            self.assertEqual(authorization, "Bearer JWT_FIXTURE")
            self.assertEqual(payload, {"repositories": ["megabrain"], "permissions": {"contents": "write"}})
            return 201, {"token": "TOKEN_FIXTURE", "permissions": {"contents": "write", "metadata": "read"}}
        if method == "GET" and path == "/installation/repositories":
            self.assertEqual(authorization, "token TOKEN_FIXTURE")
            return 200, {"total_count": 1, "repositories": [{"full_name": PUBLISH.REPOSITORY}]}
        if method == "DELETE" and path == "/installation/token":
            self.assertEqual(authorization, "token TOKEN_FIXTURE")
            return 204, {}
        self.fail(f"unexpected request: {method} {path}")

    def patches(self, api=None, stage=None):
        def runner(temp, askpass, token, branch, staging_root):
            self.assertEqual(branch, BRANCH)
            self.assertEqual(token, "TOKEN_FIXTURE")
            return lambda command, cwd: ""
        return (
            mock.patch.object(PUBLISH, "configured_origin", return_value=PUBLISH.ORIGIN),
            mock.patch.object(PUBLISH, "validate_push_destination"),
            mock.patch.object(PUBLISH.RUNTIME_CONFIG, "load_runtime_settings", side_effect=[SimpleNamespace(app_id="123", installation_id="456", key_path="/fixture/key")] * 2),
            mock.patch.object(PUBLISH, "make_jwt", return_value="JWT_FIXTURE"),
            mock.patch.object(PUBLISH, "request_json", side_effect=api or self.api_success),
            mock.patch.object(PUBLISH.LIFECYCLE, "Lifecycle", FakeLifecycle),
            mock.patch.object(PUBLISH, "create_askpass", return_value="/fixture/askpass"),
            mock.patch.object(PUBLISH, "controlled_runner", side_effect=runner),
            mock.patch.object(PUBLISH, "create_isolated_staging_repository", side_effect=stage),
        )

    def test_source_staging_blocks_unfinalized_changed_head_before_any_token_path(self):
        lifecycle = mock.Mock()
        lifecycle._validate_checkout.return_value = "b" * 40
        state = {"published_once": True, "head_sha": SHA, "pending_correction_sha": None, "corrections": 0}
        with self.assertRaisesRegex(PUBLISH.LIFECYCLE.StopNeedsHuman, "correction_finalization_required"):
            PUBLISH.validate_source_for_staging(lifecycle, {"branch": BRANCH}, state)
        lifecycle._validate_committed_paths.assert_not_called()
        lifecycle._correction_count.assert_not_called()

    def test_exact_contents_write_single_scope_exact_branch_and_sanitized_result(self):
        patches = self.patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8]:
            result = PUBLISH.run_operation(PUBLISH.OPERATION, "life-1", self.environment)
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["origin_valid"])
        self.assertTrue(result["installation_permissions_valid"])
        self.assertTrue(result["publish_token_permissions_valid"])
        self.assertTrue(result["scope_valid"])
        self.assertTrue(result["publish"])
        self.assertEqual(result["remote_sha_verified"], SHA)
        self.assertEqual(result["revocation"], "ok")
        self.assertTrue(result["temporary_cleanup"])
        self.assertEqual(FakeLifecycle.commands, [["git", "push", "origin", f"HEAD:refs/heads/{BRANCH}"]])
        encoded = json.dumps(result, sort_keys=True)
        self.assertNotIn("TOKEN_FIXTURE", encoded)
        self.assertNotIn("JWT_FIXTURE", encoded)
        self.assertNotIn(self.environment["MEGABRAIN_GITHUB_APP_KEY_PATH"], encoded)

    def test_initial_publish_defers_success_state_until_after_token_teardown(self):
        events = []

        def api(method, path, authorization, payload=None):
            if method == "DELETE" and path == "/installation/token":
                events.append("revoked")
            return self.api_success(method, path, authorization, payload)

        patches = self.patches(api)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8]:
            result = PUBLISH.run_operation(PUBLISH.OPERATION, "life-1", self.environment)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(FakeLifecycle.deferred_initial_commits), 1)
        self.assertEqual(events, ["revoked"])
        self.assertEqual(FakeLifecycle.deferred_initial_commits[0][1], SHA)

    def test_real_lifecycle_deferred_initial_commit_revalidates_exact_remote_before_state_write(self):
        events = []
        contract = {"branch": BRANCH}
        initial_state = {"head_sha": SHA, "published_once": False, "corrections": 0}
        expected_state = dict(initial_state)
        expected_state.update({
            "head_sha": SHA, "ci_sha": None, "ci_failure": None, "ci_jobs": None,
            "workflow_run_id": None, "ci_snapshot": None, "published_once": True,
        })

        def runner(command, _cwd):
            if command == ["git", "symbolic-ref", "--short", "HEAD"]:
                return BRANCH
            if command == ["git", "remote", "get-url", "origin"]:
                return PUBLISH.ORIGIN
            if command == ["git", "rev-parse", "HEAD"]:
                return SHA
            if command == ["git", "status", "--porcelain=v1", "--untracked-files=all"]:
                return ""
            if command == ["git", "ls-remote", "origin", f"refs/heads/{BRANCH}"]:
                events.append("remote_revalidation")
                return f"{SHA}\trefs/heads/{BRANCH}"
            self.fail(f"unexpected real lifecycle command: {command}")

        with tempfile.TemporaryDirectory() as temporary:
            state_root = Path(temporary) / "state"
            lifecycle = REAL_LIFECYCLE(Path(temporary) / "source", "life-1", state_root=state_root, runner=runner)
            lifecycle._guard = mock.Mock(return_value=(contract, initial_state))
            original_write_state = lifecycle._write_state

            def write_state(value):
                events.append("state_write")
                original_write_state(value)

            lifecycle._write_state = write_state
            lifecycle._commit_deferred_initial_publish_state(initial_state, SHA, expected_state)
            written = json.loads((state_root / "life-1" / "state.json").read_text(encoding="utf-8"))

        self.assertEqual(events, ["remote_revalidation", "state_write"])
        self.assertTrue(written["published_once"])
        self.assertEqual(written["head_sha"], SHA)

    def test_initial_publish_uses_fresh_real_lifecycle_after_teardown(self):
        events = []
        instances = []
        contract = {"branch": BRANCH}
        initial_state = {"head_sha": SHA, "published_once": False, "corrections": 0}
        expected_state = dict(initial_state)
        expected_state.update({
            "head_sha": SHA, "ci_sha": None, "ci_failure": None, "ci_jobs": None,
            "workflow_run_id": None, "ci_snapshot": None, "published_once": True,
        })

        class RecordingTemporaryDirectory:
            name = "/fixture/temporary-credentials"

            def cleanup(self):
                events.append("cleanup")

        def post_teardown_runner(command, _cwd):
            self.assertNotIn("MEGABRAIN_GITHUB_APP_TOKEN", os.environ)
            self.assertNotIn("GIT_ASKPASS", os.environ)
            if command == ["git", "symbolic-ref", "--short", "HEAD"]:
                return BRANCH
            if command == ["git", "remote", "get-url", "origin"]:
                return PUBLISH.ORIGIN
            if command == ["git", "rev-parse", "HEAD"]:
                return SHA
            if command == ["git", "status", "--porcelain=v1", "--untracked-files=all"]:
                return ""
            if command == ["git", "ls-remote", "origin", f"refs/heads/{BRANCH}"]:
                events.append("post_teardown_remote_revalidation")
                return f"{SHA}\trefs/heads/{BRANCH}"
            self.fail(f"unexpected post-teardown command: {command}")

        with tempfile.TemporaryDirectory() as temporary:
            state_root = Path(temporary) / "state"

            def lifecycle_factory(root, lifecycle_id):
                if len(instances) < 2:
                    instance = FakeLifecycle(root, lifecycle_id)
                else:
                    events.append("fresh_lifecycle")
                    instance = REAL_LIFECYCLE(root, lifecycle_id, state_root=state_root, runner=post_teardown_runner)
                    instance._guard = mock.Mock(return_value=(contract, initial_state))
                    original_write_state = instance._write_state

                    def write_state(value):
                        events.append("state_write")
                        original_write_state(value)

                    instance._write_state = write_state
                instances.append(instance)
                return instance

            def controlled(_temporary, _askpass, token, _branch, _staging_root):
                self.assertEqual(token, "TOKEN_FIXTURE")

                def run(command, _cwd):
                    self.assertEqual(command, ["git", "push", "origin", f"HEAD:refs/heads/{BRANCH}"])
                    events.append("push")
                    return ""

                return run

            def publish_with_readback(self, *, state_writer=None):
                self.runner(["git", "push", "origin", f"HEAD:refs/heads/{BRANCH}"], self.root)
                events.append("remote_readback")
                state_writer(expected_state)
                return {"state": "PUBLISHED", "head_sha": SHA}

            def api(method, path, authorization, payload=None):
                if method == "DELETE" and path == "/installation/token":
                    events.append("revoke")
                return self.api_success(method, path, authorization, payload)

            patches = self.patches(api)
            with (
                patches[0], patches[1], patches[2], patches[3], patches[4],
                mock.patch.object(PUBLISH.LIFECYCLE, "Lifecycle", side_effect=lifecycle_factory),
                patches[6], mock.patch.object(PUBLISH, "controlled_runner", side_effect=controlled), patches[8],
                mock.patch.object(PUBLISH.tempfile, "TemporaryDirectory", return_value=RecordingTemporaryDirectory()),
                mock.patch.object(FakeLifecycle, "_publish_head_locked", publish_with_readback),
            ):
                result = PUBLISH.run_operation(PUBLISH.OPERATION, "life-1", self.environment)
            written = (json.loads((state_root / "life-1" / "state.json").read_text(encoding="utf-8"))
                       if len(instances) == 3 else None)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["remote_sha_verified"], SHA)
        self.assertEqual(result["revocation"], "ok")
        self.assertTrue(result["temporary_cleanup"])
        self.assertEqual(len(instances), 3)
        self.assertIsNot(instances[2], instances[0])
        self.assertIsNotNone(written)
        assert written is not None
        with self.assertRaisesRegex(PUBLISH.LIFECYCLE.StopNeedsHuman, "git_command_rejected"):
            instances[0].runner(["git", "ls-remote", "origin", f"refs/heads/{BRANCH}"], instances[0].root)
        with self.assertRaisesRegex(PUBLISH.LIFECYCLE.StopNeedsHuman, "git_command_rejected"):
            instances[0].runner(["git", "push", "origin", f"HEAD:refs/heads/{BRANCH}"], instances[0].root)
        self.assertEqual(
            events,
            ["push", "remote_readback", "revoke", "cleanup", "fresh_lifecycle", "post_teardown_remote_revalidation", "state_write"],
        )
        self.assertTrue(written["published_once"])
        self.assertEqual(written["head_sha"], SHA)

    def test_isolated_staging_directory_is_removed_after_authenticated_publish(self):
        staging_parents = []

        def stage(source, staging, branch, approved_head, temporary_home):
            staging.mkdir()
            staging_parents.append(staging.parent)

        patches = self.patches(stage=stage)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8]:
            result = PUBLISH.run_operation(PUBLISH.OPERATION, "life-1", self.environment)
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["temporary_cleanup"])
        self.assertEqual(len(staging_parents), 1)
        self.assertFalse(staging_parents[0].exists())

    def test_extra_or_wrong_write_permission_is_rejected_and_revoked(self):
        def api(method, path, authorization, payload=None):
            if method == "GET" and path == "/app/installations/456":
                return 200, {"permissions": PUBLISH.EXPECTED_INSTALLATION_PERMISSIONS}
            if method == "POST":
                return 201, {"token": "TOKEN_FIXTURE", "permissions": {"contents": "write", "workflows": "write"}}
            if method == "DELETE":
                return 204, {}
            self.fail("scope and push must not run")
        patches = self.patches(api)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8]:
            result = PUBLISH.run_operation(PUBLISH.OPERATION, "life-1", self.environment)
        self.assertEqual(result["failure_code"], "token_permissions_rejected")
        self.assertIs(result["publish_token_permissions_valid"], False)
        self.assertEqual(result["revocation"], "ok")
        self.assertFalse(FakeLifecycle.commands)

    def test_wrong_repository_scope_is_rejected_and_revoked(self):
        def api(method, path, authorization, payload=None):
            if method == "GET" and path == "/app/installations/456":
                return 200, {"permissions": PUBLISH.EXPECTED_INSTALLATION_PERMISSIONS}
            if method == "POST":
                return 201, {"token": "TOKEN_FIXTURE", "permissions": {"contents": "write"}}
            if path == "/installation/repositories":
                return 200, {"total_count": 2, "repositories": [{"full_name": PUBLISH.REPOSITORY}, {"full_name": "other/repo"}]}
            if method == "DELETE":
                return 204, {}
            self.fail("push must not run")
        patches = self.patches(api)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8]:
            result = PUBLISH.run_operation(PUBLISH.OPERATION, "life-1", self.environment)
        self.assertEqual(result["failure_code"], "scope_rejected")
        self.assertIs(result["scope_valid"], False)
        self.assertEqual(result["revocation"], "ok")

    def test_wrong_origin_gate_and_wrong_operation_do_not_authenticate(self):
        with mock.patch.object(PUBLISH.LIFECYCLE, "Lifecycle", FakeLifecycle), mock.patch.object(PUBLISH, "configured_origin", return_value="https://example.invalid/repo.git"), mock.patch.object(PUBLISH, "make_jwt") as signer:
            result = PUBLISH.run_operation(PUBLISH.OPERATION, "life-1", self.environment)
        signer.assert_not_called()
        self.assertEqual(result["failure_code"], "origin_rejected")
        with mock.patch.object(PUBLISH, "configured_origin") as origin:
            gated = PUBLISH.run_operation("not-authorized", "life-1", self.environment)
            unknown = PUBLISH.run_operation("ensure-pr", "life-1", self.environment)
        origin.assert_not_called()
        self.assertEqual(gated["failure_code"], "operation_rejected")
        self.assertEqual(unknown["failure_code"], "operation_rejected")

    def test_unexpected_pushurl_is_rejected_before_authentication_or_push(self):
        with (
            mock.patch.object(PUBLISH, "configured_origin", return_value=PUBLISH.ORIGIN),
            mock.patch.object(PUBLISH, "validate_push_destination", side_effect=PUBLISH.SafeFailure("push_destination_rejected")),
            mock.patch.object(PUBLISH.LIFECYCLE, "Lifecycle", FakeLifecycle),
            mock.patch.object(PUBLISH, "make_jwt") as signer,
        ):
            result = PUBLISH.run_operation(PUBLISH.OPERATION, "life-1", self.environment)
        signer.assert_not_called()
        self.assertEqual(result["failure_code"], "push_destination_rejected")
        self.assertFalse(FakeLifecycle.commands)

    def test_exact_expected_push_target_is_accepted(self):
        def git(command, **_):
            if command == [PUBLISH.GIT_BINARY, "config", "--local", "--get-all", "remote.origin.pushurl"]:
                return PUBLISH.subprocess.CompletedProcess(command, 1, "", "")
            if command == [PUBLISH.GIT_BINARY, "remote", "get-url", "--all", "--push", "origin"]:
                return PUBLISH.subprocess.CompletedProcess(command, 0, f"{PUBLISH.ORIGIN}\n", "")
            self.fail(f"unexpected command: {command}")
        with mock.patch.object(PUBLISH.subprocess, "run", side_effect=git):
            PUBLISH.validate_push_destination()

    def test_unexpected_configured_pushurl_is_rejected(self):
        command = [PUBLISH.GIT_BINARY, "config", "--local", "--get-all", "remote.origin.pushurl"]
        with mock.patch.object(PUBLISH.subprocess, "run", return_value=PUBLISH.subprocess.CompletedProcess(command, 0, "https://example.invalid/repo.git\n", "")):
            with self.assertRaisesRegex(PUBLISH.SafeFailure, "push_destination_rejected"):
                PUBLISH.validate_push_destination()

    def test_controlled_runner_uses_fixed_git_without_path_and_disables_helpers_and_hooks(self):
        command = ["git", "push", "origin", f"HEAD:refs/heads/{BRANCH}"]
        completed = PUBLISH.subprocess.CompletedProcess(command, 0, "", "")
        staging = Path("/fixture/staging")
        runner = PUBLISH.controlled_runner("/fixture/temp", "/fixture/askpass", "TOKEN_FIXTURE", BRANCH, staging)
        with mock.patch.dict(PUBLISH.os.environ, {"PATH": "/fixture/malicious-bin"}, clear=True), mock.patch.object(
            PUBLISH.subprocess, "run", return_value=completed
        ) as execute:
            self.assertEqual(runner(command, staging), "")
        invoked = execute.call_args.args[0]
        environment = execute.call_args.kwargs["env"]
        self.assertEqual(
            invoked,
            [PUBLISH.GIT_BINARY, "-c", "credential.helper=", "-c", "credential.useHttpPath=true", "-c", "credential.interactive=false", "-c", "core.hooksPath=/dev/null", *command[1:]],
        )
        self.assertNotIn("PATH", environment)
        self.assertEqual(environment["GIT_ASKPASS"], "/fixture/askpass")
        self.assertEqual(environment["GIT_CONFIG_GLOBAL"], PUBLISH.os.devnull)

    def test_jwt_signing_uses_fixed_openssl_binary(self):
        completed = PUBLISH.subprocess.CompletedProcess([PUBLISH.OPENSSL_BINARY], 0, b"signature", b"")
        with mock.patch.object(PUBLISH, "validate_privileged_executable") as validate, mock.patch.object(
            PUBLISH.subprocess, "run", return_value=completed
        ) as execute:
            PUBLISH.make_jwt("123", "/fixture/key", now=1_700_000_000)
        validate.assert_called_once_with(PUBLISH.OPENSSL_BINARY)
        self.assertEqual(execute.call_args.args[0], [PUBLISH.OPENSSL_BINARY, "dgst", "-sha256", "-sign", "/fixture/key"])

    def test_invalid_privileged_executable_fails_before_signing_or_token_mint(self):
        invalid_stats = (
            os.stat_result((stat.S_IFLNK | 0o777, 0, 0, 0, 0, 0, 0, 0, 0, 0)),
            os.stat_result((stat.S_IFREG | 0o755, 0, 0, 0, 1000, 0, 0, 0, 0, 0)),
            os.stat_result((stat.S_IFREG | 0o775, 0, 0, 0, 0, 0, 0, 0, 0, 0)),
            os.stat_result((stat.S_IFREG | 0o644, 0, 0, 0, 0, 0, 0, 0, 0, 0)),
        )
        for invalid_stat in invalid_stats:
            with self.subTest(mode=invalid_stat.st_mode, uid=invalid_stat.st_uid), mock.patch.object(
                PUBLISH.os, "lstat", return_value=invalid_stat
            ), mock.patch.object(PUBLISH.LIFECYCLE, "Lifecycle", FakeLifecycle), mock.patch.object(PUBLISH, "make_jwt") as signer, mock.patch.object(PUBLISH, "request_json") as request:
                result = PUBLISH.run_operation(PUBLISH.OPERATION, "life-1", self.environment)
            signer.assert_not_called()
            request.assert_not_called()
            self.assertIn(result["failure_code"], {"privileged_executable_invalid", "unexpected_failure"})

        with mock.patch.object(PUBLISH.os, "lstat", side_effect=OSError("missing")), mock.patch.object(PUBLISH.LIFECYCLE, "Lifecycle", FakeLifecycle), mock.patch.object(
            PUBLISH, "make_jwt"
        ) as signer, mock.patch.object(PUBLISH, "request_json") as request:
            result = PUBLISH.run_operation(PUBLISH.OPERATION, "life-1", self.environment)
        signer.assert_not_called()
        request.assert_not_called()
        self.assertEqual(result["failure_code"], "privileged_executable_invalid")

    def test_invalid_openssl_fails_before_signing(self):
        invalid_openssl = os.stat_result((stat.S_IFREG | 0o775, 0, 0, 0, 0, 0, 0, 0, 0, 0))
        with mock.patch.object(PUBLISH.os, "lstat", return_value=invalid_openssl), mock.patch.object(
            PUBLISH.subprocess, "run"
        ) as execute:
            with self.assertRaisesRegex(PUBLISH.SafeFailure, "privileged_executable_invalid"):
                PUBLISH.make_jwt("123", "/fixture/key")
        execute.assert_not_called()

    def test_invalid_openssl_fails_before_token_mint(self):
        valid_git = os.stat_result((stat.S_IFREG | 0o755, 0, 0, 0, 0, 0, 0, 0, 0, 0))
        invalid_openssl = os.stat_result((stat.S_IFREG | 0o775, 0, 0, 0, 0, 0, 0, 0, 0, 0))

        def lstat(path):
            return valid_git if path == PUBLISH.GIT_BINARY else invalid_openssl

        with mock.patch.object(PUBLISH.os, "lstat", side_effect=lstat), mock.patch.object(PUBLISH.LIFECYCLE, "Lifecycle", FakeLifecycle), mock.patch.object(
            PUBLISH, "make_jwt"
        ) as signer, mock.patch.object(PUBLISH, "request_json") as request:
            result = PUBLISH.run_operation(PUBLISH.OPERATION, "life-1", self.environment)
        signer.assert_not_called()
        request.assert_not_called()
        self.assertEqual(result["failure_code"], "privileged_executable_invalid")

    def test_source_worktree_git_runner_never_receives_installation_token(self):
        command = ["git", "rev-parse", "HEAD"]
        completed = PUBLISH.subprocess.CompletedProcess(command, 0, SHA, "")
        runner = PUBLISH.source_runner("/fixture/temp", BRANCH)
        with mock.patch.object(PUBLISH.subprocess, "run", return_value=completed) as execute:
            self.assertEqual(runner(command, Path("/fixture/source")), SHA)
        environment = execute.call_args.kwargs["env"]
        self.assertEqual(execute.call_args.args[0][0], PUBLISH.GIT_BINARY)
        self.assertNotIn("MEGABRAIN_GITHUB_APP_TOKEN", environment)
        self.assertNotIn("GIT_ASKPASS", environment)

    def test_source_pre_push_hook_cannot_execute_during_authenticated_push(self):
        command = ["git", "push", "origin", f"HEAD:refs/heads/{BRANCH}"]
        source = Path("/fixture/source-with-pre-push-hook")
        staging = Path("/fixture/staging")
        runner = PUBLISH.controlled_runner("/fixture/temp", "/fixture/askpass", "TOKEN_FIXTURE", BRANCH, staging)
        with mock.patch.object(PUBLISH.subprocess, "run") as execute:
            with self.assertRaisesRegex(PUBLISH.LIFECYCLE.StopNeedsHuman, "git_command_rejected"):
                runner(command, source)
        execute.assert_not_called()

    def test_staging_rejects_a_commit_other_than_the_approved_head(self):
        commands = []

        def git(command, **_):
            commands.append(command)
            stdout = "b" * 40 if command[-2:] == ["rev-parse", "HEAD"] else ""
            return PUBLISH.subprocess.CompletedProcess(command, 0, stdout, "")
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(PUBLISH.subprocess, "run", side_effect=git):
            with self.assertRaisesRegex(PUBLISH.LIFECYCLE.StopNeedsHuman, "staged_head_mismatch"):
                PUBLISH.create_isolated_staging_repository(
                    Path("/fixture/source"), Path(temporary) / "staging", BRANCH, SHA, temporary,
                )
        self.assertTrue(commands)
        self.assertTrue(all(command[0] == PUBLISH.GIT_BINARY for command in commands))

    def test_only_exact_non_force_head_refspec_is_permitted(self):
        allowed = ["git", "push", "origin", f"HEAD:refs/heads/{BRANCH}"]
        self.assertTrue(PUBLISH._allowed_git_command(allowed, BRANCH))
        for command in (
            ["git", "push", "origin", f"+HEAD:refs/heads/{BRANCH}"],
            ["git", "push", "origin", "--delete", f"refs/heads/{BRANCH}"],
            ["git", "push", "origin", "refs/tags/v1"],
            ["git", "push", "other", f"HEAD:refs/heads/{BRANCH}"],
            ["git", "push", "origin", "HEAD:refs/heads/dev"],
        ):
            self.assertFalse(PUBLISH._allowed_git_command(command, BRANCH))

    def test_runtime_config_change_before_mint_never_mints_or_publishes(self):
        calls = []
        config_a = SimpleNamespace(app_id="123", installation_id="456", key_path="/fixture/key-a")
        config_b = SimpleNamespace(app_id="999", installation_id="456", key_path="/fixture/key-b")

        def baseline_only(method, path, authorization, payload=None):
            calls.append((method, path, authorization, payload))
            if method == "GET" and path == "/app/installations/456":
                self.assertEqual(authorization, "Bearer JWT_FIXTURE")
                return 200, {"permissions": PUBLISH.EXPECTED_INSTALLATION_PERMISSIONS}
            self.fail("config change must prevent token mint and protected publish")

        patches = self.patches(baseline_only)
        with (
            patches[0], patches[1],
            mock.patch.object(PUBLISH.RUNTIME_CONFIG, "load_runtime_settings", side_effect=[config_a, config_b]),
            patches[3], patches[4], patches[5], patches[6], patches[7], patches[8],
            mock.patch.object(FakeLifecycle, "_publish_head_locked", autospec=True) as publish,
        ):
            result = PUBLISH.run_operation(PUBLISH.OPERATION, "life-1", self.environment)
        self.assertEqual(result["failure_code"], "runtime_config_changed_before_mint")
        self.assertEqual([(method, path) for method, path, _, _ in calls], [("GET", "/app/installations/456")])
        self.assertEqual(result["revocation"], "not_attempted")
        self.assertTrue(result["temporary_cleanup"])
        self.assertFalse(FakeLifecycle.commands)
        self.assertFalse(FakeLifecycle.deferred_initial_commits)
        publish.assert_not_called()

    def test_revocation_and_cleanup_fail_closed(self):
        def revocation_fails(method, path, authorization, payload=None):
            if method == "DELETE":
                return 500, {}
            return self.api_success(method, path, authorization, payload)
        patches = self.patches(revocation_fails)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8]:
            revoked = PUBLISH.run_operation(PUBLISH.OPERATION, "life-1", self.environment)
        self.assertEqual(revoked["failure_code"], "revocation_failed")
        self.assertEqual(revoked["revocation"], "failed")

        class BrokenTemporaryDirectory:
            name = "/fixture/temp"
            def cleanup(self):
                raise OSError("fixture")
        patches = self.patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], mock.patch.object(PUBLISH.tempfile, "TemporaryDirectory", return_value=BrokenTemporaryDirectory()):
            cleaned = PUBLISH.run_operation(PUBLISH.OPERATION, "life-1", self.environment)
        self.assertEqual(cleaned["failure_code"], "cleanup_failed")
        self.assertEqual(cleaned["revocation"], "ok")
        self.assertIs(cleaned["temporary_cleanup"], False)

    def test_empty_204_revocation_body_is_accepted(self):
        original_request_json = PUBLISH.request_json

        class EmptyResponse:
            status = 204

            def read(self):
                return b""

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

        def api(method, path, authorization, payload=None):
            if method == "DELETE":
                return original_request_json(method, path, authorization, payload)
            return self.api_success(method, path, authorization, payload)

        patches = self.patches(api)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], mock.patch.object(PUBLISH.urllib.request, "urlopen", return_value=EmptyResponse()):
            result = PUBLISH.run_operation(PUBLISH.OPERATION, "life-1", self.environment)
        self.assertEqual(result["status"], "ok")
        self.assertIsNone(result["failure_code"])
        self.assertEqual(result["revocation"], "ok")


if __name__ == "__main__":
    unittest.main()
