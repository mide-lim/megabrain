"""Hermetic tests for the fixed B4.2 P1 authenticated read adapter."""
from __future__ import annotations

import hashlib
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
MODULE_PATH = SKILL / "scripts" / "authenticated_read_validation.py"
INSTALLER_PATH = SKILL / "scripts" / "install_skill.py"


def load(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


READ = load("b42_authenticated_read_validation", MODULE_PATH)


class AuthenticatedReadValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.environment = {
            "MEGABRAIN_GITHUB_APP_ID": "123",
            "MEGABRAIN_GITHUB_APP_INSTALLATION_ID": "456",
            "MEGABRAIN_GITHUB_APP_KEY_PATH": "/not/a/real/key",
        }

    def api_success(self, method, path, authorization, payload=None):
        if method == "GET" and path == "/app/installations/456":
            self.assertEqual(authorization, "Bearer JWT_FIXTURE")
            self.assertIsNone(payload)
            return 200, {"permissions": READ.EXPECTED_INSTALLATION_PERMISSIONS}
        if method == "POST" and path == "/app/installations/456/access_tokens":
            self.assertEqual(authorization, "Bearer JWT_FIXTURE")
            self.assertEqual(payload, {"repositories": ["megabrain"], "permissions": {"contents": "read"}})
            return 201, {"token": "TOKEN_FIXTURE", "permissions": {"contents": "read", "metadata": "read"}}
        if method == "GET" and path == "/installation/repositories":
            self.assertEqual(authorization, "token TOKEN_FIXTURE")
            return 200, {"total_count": 1, "repositories": [{"full_name": READ.REPOSITORY}]}
        if method == "GET" and path == READ.REF_API_PATH:
            self.assertEqual(authorization, "token TOKEN_FIXTURE")
            return 200, {"ref": READ.REF, "object": {"type": "commit", "sha": "a" * 40}}
        if method == "DELETE" and path == "/installation/token":
            self.assertEqual(authorization, "token TOKEN_FIXTURE")
            self.assertIsNone(payload)
            return 204, {}
        self.fail(f"unexpected request: {method} {path}")

    def successful_patches(self, api=None):
        return (
            mock.patch.object(READ, "configured_origin", return_value=READ.ORIGIN),
            mock.patch.object(READ, "validate_key_path"),
            mock.patch.object(READ, "make_jwt", return_value="JWT_FIXTURE"),
            mock.patch.object(READ, "request_json", side_effect=api or self.api_success),
        )

    def test_success_is_fixed_read_only_sanitized_and_cleaned(self) -> None:
        patches = self.successful_patches()
        with patches[0], patches[1], patches[2], patches[3]:
            result = READ.run_operation(READ.OPERATION, True, self.environment)
        self.assertEqual(result["status"], "ok")
        self.assertIsNone(result["failure_code"])
        self.assertTrue(result["origin_valid"])
        self.assertTrue(result["installation_permissions_valid"])
        self.assertTrue(result["token_permissions_valid"])
        self.assertTrue(result["scope_valid"])
        self.assertTrue(result["ref_valid"])
        self.assertEqual(result["sha"], "a" * 40)
        self.assertEqual(result["revocation"], "ok")
        self.assertTrue(result["temporary_cleanup"])
        encoded = json.dumps(result, sort_keys=True)
        self.assertNotIn("TOKEN_FIXTURE", encoded)
        self.assertNotIn("JWT_FIXTURE", encoded)
        self.assertNotIn(self.environment["MEGABRAIN_GITHUB_APP_KEY_PATH"], encoded)

    def test_contents_read_without_metadata_is_accepted(self) -> None:
        def api(method, path, authorization, payload=None):
            if method == "POST" and path == "/app/installations/456/access_tokens":
                return 201, {"token": "TOKEN_FIXTURE", "permissions": {"contents": "read"}}
            return self.api_success(method, path, authorization, payload)

        patches = self.successful_patches(api)
        with patches[0], patches[1], patches[2], patches[3]:
            result = READ.run_operation(READ.OPERATION, True, self.environment)
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["token_permissions_valid"])

    def test_gate_and_unknown_operation_do_not_touch_runtime_dependencies(self) -> None:
        with mock.patch.object(READ, "configured_origin") as origin:
            blocked = READ.run_operation(READ.OPERATION, False, self.environment)
            unknown = READ.run_operation("anything-else", True, self.environment)
        origin.assert_not_called()
        self.assertEqual(blocked["failure_code"], "operational_gate_required")
        self.assertEqual(unknown["failure_code"], "operation_rejected")

    def test_extra_or_write_token_permission_is_rejected_and_revoked(self) -> None:
        def api(method, path, authorization, payload=None):
            if method == "GET" and path == "/app/installations/456":
                return 200, {"permissions": READ.EXPECTED_INSTALLATION_PERMISSIONS}
            if method == "POST":
                return 201, {"token": "TOKEN_FIXTURE", "permissions": {"contents": "write", "metadata": "read"}}
            if method == "DELETE":
                return 204, {}
            self.fail("scope or ref must not be requested")

        patches = self.successful_patches(api)
        with patches[0], patches[1], patches[2], patches[3]:
            result = READ.run_operation(READ.OPERATION, True, self.environment)
        self.assertEqual(result["failure_code"], "token_permissions_rejected")
        self.assertIs(result["token_permissions_valid"], False)
        self.assertEqual(result["revocation"], "ok")
        self.assertIsNone(result["temporary_cleanup"])

    def test_wrong_scope_is_rejected_and_revoked(self) -> None:
        def api(method, path, authorization, payload=None):
            if method == "GET" and path == "/app/installations/456":
                return 200, {"permissions": READ.EXPECTED_INSTALLATION_PERMISSIONS}
            if method == "POST":
                return 201, {"token": "TOKEN_FIXTURE", "permissions": {"contents": "read"}}
            if method == "GET" and path == "/installation/repositories":
                return 200, {"total_count": 1, "repositories": [{"full_name": "other/repo"}]}
            if method == "DELETE":
                return 204, {}
            self.fail("ref must not be requested")

        patches = self.successful_patches(api)
        with patches[0], patches[1], patches[2], patches[3]:
            result = READ.run_operation(READ.OPERATION, True, self.environment)
        self.assertEqual(result["failure_code"], "scope_rejected")
        self.assertIs(result["scope_valid"], False)
        self.assertEqual(result["revocation"], "ok")

    def test_administration_in_baseline_is_rejected_before_token_mint(self) -> None:
        def api(method, path, authorization, payload=None):
            if method == "GET" and path == "/app/installations/456":
                permissions = dict(READ.EXPECTED_INSTALLATION_PERMISSIONS, administration="read")
                return 200, {"permissions": permissions}
            self.fail("token must not be minted")

        patches = self.successful_patches(api)
        with patches[0], patches[1], patches[2], patches[3]:
            result = READ.run_operation(READ.OPERATION, True, self.environment)
        self.assertEqual(result["failure_code"], "installation_permissions_rejected")
        self.assertIs(result["installation_permissions_valid"], False)
        self.assertEqual(result["revocation"], "not_attempted")

    def test_wrong_ref_is_rejected_and_revoked(self) -> None:
        def api(method, path, authorization, payload=None):
            if method == "GET" and path == "/app/installations/456":
                return 200, {"permissions": READ.EXPECTED_INSTALLATION_PERMISSIONS}
            if method == "POST":
                return 201, {"token": "TOKEN_FIXTURE", "permissions": {"contents": "read"}}
            if method == "GET" and path == "/installation/repositories":
                return 200, {"total_count": 1, "repositories": [{"full_name": READ.REPOSITORY}]}
            if method == "GET" and path == READ.REF_API_PATH:
                return 200, {"ref": "refs/heads/main", "object": {"type": "commit", "sha": "a" * 40}}
            if method == "DELETE":
                return 204, {}
            self.fail("unexpected request")

        patches = self.successful_patches(api)
        with patches[0], patches[1], patches[2], patches[3]:
            result = READ.run_operation(READ.OPERATION, True, self.environment)
        self.assertEqual(result["failure_code"], "ref_rejected")
        self.assertIs(result["ref_valid"], False)
        self.assertEqual(result["revocation"], "ok")
        self.assertTrue(result["temporary_cleanup"])

    def test_wrong_sha_is_rejected_and_revoked(self) -> None:
        def api(method, path, authorization, payload=None):
            if method == "GET" and path == "/app/installations/456":
                return 200, {"permissions": READ.EXPECTED_INSTALLATION_PERMISSIONS}
            if method == "POST":
                return 201, {"token": "TOKEN_FIXTURE", "permissions": {"contents": "read"}}
            if method == "GET" and path == "/installation/repositories":
                return 200, {"total_count": 1, "repositories": [{"full_name": READ.REPOSITORY}]}
            if method == "GET" and path == READ.REF_API_PATH:
                return 200, {"ref": READ.REF, "object": {"type": "commit", "sha": "A" * 40}}
            if method == "DELETE":
                return 204, {}
            self.fail("unexpected request")

        patches = self.successful_patches(api)
        with patches[0], patches[1], patches[2], patches[3]:
            result = READ.run_operation(READ.OPERATION, True, self.environment)
        self.assertEqual(result["failure_code"], "ref_rejected")
        self.assertIs(result["ref_valid"], False)
        self.assertEqual(result["revocation"], "ok")
        self.assertTrue(result["temporary_cleanup"])

    def test_revocation_and_cleanup_fail_closed(self) -> None:
        def revoke_fails(method, path, authorization, payload=None):
            if method == "DELETE":
                return 500, {}
            return self.api_success(method, path, authorization, payload)

        patches = self.successful_patches(revoke_fails)
        with patches[0], patches[1], patches[2], patches[3]:
            revoked = READ.run_operation(READ.OPERATION, True, self.environment)
        self.assertEqual(revoked["failure_code"], "revocation_failed")
        self.assertEqual(revoked["revocation"], "failed")
        self.assertTrue(revoked["temporary_cleanup"])

        class BrokenTemporaryDirectory:
            name = "/not/a/real/temp"

            def cleanup(self):
                raise OSError("cleanup fixture")

        patches = self.successful_patches()
        with patches[0], patches[1], patches[2], patches[3], mock.patch.object(READ.tempfile, "TemporaryDirectory", return_value=BrokenTemporaryDirectory()):
            cleaned = READ.run_operation(READ.OPERATION, True, self.environment)
        self.assertEqual(cleaned["failure_code"], "cleanup_failed")
        self.assertEqual(cleaned["revocation"], "ok")
        self.assertIs(cleaned["temporary_cleanup"], False)


class InstallationTests(unittest.TestCase):
    def test_clean_install_reinstall_hashes_and_modes(self) -> None:
        installer = load("b42_read_installer", INSTALLER_PATH)
        with tempfile.TemporaryDirectory() as temporary_root:
            destination = Path(temporary_root) / "profile" / "megabrain-autonomous-pr-lifecycle"
            installer.install(destination, test_only=True)
            (destination / "stale").write_text("stale", encoding="utf-8")
            installer.install(destination, test_only=True)
            self.assertEqual(
                {path.relative_to(destination) for path in destination.rglob("*") if path.is_file()},
                set(installer.ARTIFACTS),
            )
            for relative, mode in installer.ARTIFACTS.items():
                self.assertEqual(
                    hashlib.sha256((SKILL / relative).read_bytes()).digest(),
                    hashlib.sha256((destination / relative).read_bytes()).digest(),
                )
                self.assertEqual(stat.S_IMODE((destination / relative).stat().st_mode), mode)
            self.assertFalse(any(path.name == ".env" or path.suffix in {".pem", ".key"} for path in destination.rglob("*") if path.is_file()))


if __name__ == "__main__":
    unittest.main()
