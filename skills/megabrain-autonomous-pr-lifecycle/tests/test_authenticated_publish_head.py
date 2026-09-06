"""Hermetic tests for the fixed B4.2 P2 controlled publish adapter."""
from __future__ import annotations

from contextlib import contextmanager
import importlib.util
import json
import sys
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


class FakeLifecycle:
    branch = BRANCH
    published_sha = SHA
    commands: list[list[str]] = []

    def __init__(self, root, lifecycle_id):
        self.root = root
        self.lifecycle_id = lifecycle_id
        self.runner = None

    def _contract(self):
        return {"branch": self.branch}, "fingerprint"

    @contextmanager
    def _publish_reservation(self):
        yield

    def _publish_head_locked(self):
        assert self.runner is not None
        command = ["git", "push", "origin", f"HEAD:refs/heads/{self.branch}"]
        self.commands.append(command)
        self.runner(command, self.root)
        return {"state": "PUBLISHED", "head_sha": self.published_sha}


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

    def patches(self, api=None):
        def runner(temp, askpass, token, branch):
            self.assertEqual(branch, BRANCH)
            self.assertEqual(token, "TOKEN_FIXTURE")
            return lambda command, cwd: ""
        return (
            mock.patch.object(PUBLISH, "configured_origin", return_value=PUBLISH.ORIGIN),
            mock.patch.object(PUBLISH, "validate_push_destination"),
            mock.patch.object(PUBLISH, "validate_key_path"),
            mock.patch.object(PUBLISH, "make_jwt", return_value="JWT_FIXTURE"),
            mock.patch.object(PUBLISH, "request_json", side_effect=api or self.api_success),
            mock.patch.object(PUBLISH.LIFECYCLE, "Lifecycle", FakeLifecycle),
            mock.patch.object(PUBLISH, "create_askpass", return_value="/fixture/askpass"),
            mock.patch.object(PUBLISH, "controlled_runner", side_effect=runner),
        )

    def test_exact_contents_write_single_scope_exact_branch_and_sanitized_result(self):
        patches = self.patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
            result = PUBLISH.run_operation(PUBLISH.OPERATION, "life-1", True, self.environment)
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
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
            result = PUBLISH.run_operation(PUBLISH.OPERATION, "life-1", True, self.environment)
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
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
            result = PUBLISH.run_operation(PUBLISH.OPERATION, "life-1", True, self.environment)
        self.assertEqual(result["failure_code"], "scope_rejected")
        self.assertIs(result["scope_valid"], False)
        self.assertEqual(result["revocation"], "ok")

    def test_wrong_origin_gate_and_wrong_operation_do_not_authenticate(self):
        with mock.patch.object(PUBLISH, "configured_origin", return_value="https://example.invalid/repo.git"), mock.patch.object(PUBLISH, "make_jwt") as signer:
            result = PUBLISH.run_operation(PUBLISH.OPERATION, "life-1", True, self.environment)
        signer.assert_not_called()
        self.assertEqual(result["failure_code"], "origin_rejected")
        with mock.patch.object(PUBLISH, "configured_origin") as origin:
            gated = PUBLISH.run_operation(PUBLISH.OPERATION, "life-1", False, self.environment)
            unknown = PUBLISH.run_operation("ensure-pr", "life-1", True, self.environment)
        origin.assert_not_called()
        self.assertEqual(gated["failure_code"], "operational_gate_required")
        self.assertEqual(unknown["failure_code"], "operation_rejected")

    def test_unexpected_pushurl_is_rejected_before_authentication_or_push(self):
        with (
            mock.patch.object(PUBLISH, "configured_origin", return_value=PUBLISH.ORIGIN),
            mock.patch.object(PUBLISH, "validate_push_destination", side_effect=PUBLISH.SafeFailure("push_destination_rejected")),
            mock.patch.object(PUBLISH, "make_jwt") as signer,
        ):
            result = PUBLISH.run_operation(PUBLISH.OPERATION, "life-1", True, self.environment)
        signer.assert_not_called()
        self.assertEqual(result["failure_code"], "push_destination_rejected")
        self.assertFalse(FakeLifecycle.commands)

    def test_exact_expected_push_target_is_accepted(self):
        def git(command, **_):
            if command == ["git", "config", "--local", "--get-all", "remote.origin.pushurl"]:
                return PUBLISH.subprocess.CompletedProcess(command, 1, "", "")
            if command == ["git", "remote", "get-url", "--all", "--push", "origin"]:
                return PUBLISH.subprocess.CompletedProcess(command, 0, f"{PUBLISH.ORIGIN}\n", "")
            self.fail(f"unexpected command: {command}")
        with mock.patch.object(PUBLISH.subprocess, "run", side_effect=git):
            PUBLISH.validate_push_destination()

    def test_unexpected_configured_pushurl_is_rejected(self):
        command = ["git", "config", "--local", "--get-all", "remote.origin.pushurl"]
        with mock.patch.object(PUBLISH.subprocess, "run", return_value=PUBLISH.subprocess.CompletedProcess(command, 0, "https://example.invalid/repo.git\n", "")):
            with self.assertRaisesRegex(PUBLISH.SafeFailure, "push_destination_rejected"):
                PUBLISH.validate_push_destination()

    def test_controlled_runner_disables_repository_credential_helpers(self):
        command = ["git", "push", "origin", f"HEAD:refs/heads/{BRANCH}"]
        completed = PUBLISH.subprocess.CompletedProcess(command, 0, "", "")
        runner = PUBLISH.controlled_runner("/fixture/temp", "/fixture/askpass", "TOKEN_FIXTURE", BRANCH)
        with mock.patch.object(PUBLISH.subprocess, "run", return_value=completed) as execute:
            self.assertEqual(runner(command, Path("/fixture/repository")), "")
        invoked = execute.call_args.args[0]
        environment = execute.call_args.kwargs["env"]
        self.assertEqual(
            invoked,
            ["git", "-c", "credential.helper=", "-c", "credential.useHttpPath=true", "-c", "credential.interactive=false", *command[1:]],
        )
        self.assertEqual(environment["GIT_ASKPASS"], "/fixture/askpass")
        self.assertEqual(environment["GIT_CONFIG_GLOBAL"], PUBLISH.os.devnull)

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

    def test_revocation_and_cleanup_fail_closed(self):
        def revocation_fails(method, path, authorization, payload=None):
            if method == "DELETE":
                return 500, {}
            return self.api_success(method, path, authorization, payload)
        patches = self.patches(revocation_fails)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
            revoked = PUBLISH.run_operation(PUBLISH.OPERATION, "life-1", True, self.environment)
        self.assertEqual(revoked["failure_code"], "revocation_failed")
        self.assertEqual(revoked["revocation"], "failed")

        class BrokenTemporaryDirectory:
            name = "/fixture/temp"
            def cleanup(self):
                raise OSError("fixture")
        patches = self.patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], mock.patch.object(PUBLISH.tempfile, "TemporaryDirectory", return_value=BrokenTemporaryDirectory()):
            cleaned = PUBLISH.run_operation(PUBLISH.OPERATION, "life-1", True, self.environment)
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
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], mock.patch.object(PUBLISH.urllib.request, "urlopen", return_value=EmptyResponse()):
            result = PUBLISH.run_operation(PUBLISH.OPERATION, "life-1", True, self.environment)
        self.assertEqual(result["status"], "ok")
        self.assertIsNone(result["failure_code"])
        self.assertEqual(result["revocation"], "ok")


if __name__ == "__main__":
    unittest.main()
