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

SKILL_DIRECTORY = Path(__file__).resolve().parents[1]
SCRIPTS_DIRECTORY = SKILL_DIRECTORY / "scripts"
HELPER_PATH = SCRIPTS_DIRECTORY / "github_app_auth.py"
INSTALLER_PATH = SCRIPTS_DIRECTORY / "install_skill.py"


def load_module(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


AUTH = load_module("canonical_github_app_auth", HELPER_PATH)


class GithubAppAuthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.environment = {
            "MEGABRAIN_GITHUB_APP_ID": "123",
            "MEGABRAIN_GITHUB_APP_INSTALLATION_ID": "456",
            "MEGABRAIN_GITHUB_APP_KEY_PATH": "/not/a/real/key",
        }

    def api_success(self, method, path, authorization, payload=None):
        if method == "POST":
            self.assertEqual(path, "/app/installations/456/access_tokens")
            self.assertEqual(payload, {"repositories": ["megabrain"], "permissions": AUTH.EXPECTED_PERMISSIONS})
            return 201, {"token": "TOKEN_FIXTURE", "permissions": AUTH.EXPECTED_PERMISSIONS}
        if method == "GET":
            return 200, {"total_count": 1, "repositories": [{"full_name": AUTH.EXPECTED_REPOSITORY}]}
        if method == "DELETE":
            return 204, {}
        self.fail(f"unexpected request {method}")

    def successful_patches(self, git_result=True, api=None):
        return (
            mock.patch.object(AUTH, "configured_origin", return_value=AUTH.EXPECTED_ORIGIN),
            mock.patch.object(AUTH, "validate_key_path"),
            mock.patch.object(AUTH, "make_jwt", return_value="JWT_FIXTURE"),
            mock.patch.object(AUTH, "request_json", side_effect=api or self.api_success),
            mock.patch.object(AUTH, "run_git_probe", return_value=git_result),
        )

    def test_success_is_sanitized_and_cleans_askpass(self) -> None:
        patches = self.successful_patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            result = AUTH.run_operation(AUTH.OPERATION, True, self.environment)
        self.assertEqual(result["status"], "ok")
        self.assertIsNone(result["failure_code"])
        self.assertTrue(result["origin_valid"])
        self.assertTrue(result["permissions_valid"])
        self.assertTrue(result["scope_valid"])
        self.assertTrue(result["git_probe"])
        self.assertEqual(result["revocation"], "ok")
        self.assertTrue(result["askpass_cleanup"])
        encoded = json.dumps(result, sort_keys=True)
        self.assertNotIn("TOKEN_FIXTURE", encoded)
        self.assertNotIn("JWT_FIXTURE", encoded)
        self.assertNotIn(self.environment["MEGABRAIN_GITHUB_APP_KEY_PATH"], encoded)

    def test_origin_rejection_happens_before_signing(self) -> None:
        with mock.patch.object(AUTH, "configured_origin", return_value="https://example.invalid/repo.git"), mock.patch.object(
            AUTH, "make_jwt"
        ) as signer:
            result = AUTH.run_operation(AUTH.OPERATION, True, self.environment)
        signer.assert_not_called()
        self.assertEqual(result["failure_code"], "origin_rejected")
        self.assertEqual(result["revocation"], "not_attempted")

    def test_permission_rejection_revokes_minted_token(self) -> None:
        def api(method, path, authorization, payload=None):
            if method == "POST":
                return 201, {"token": "TOKEN_FIXTURE", "permissions": {"contents": "read"}}
            if method == "DELETE":
                return 204, {}
            self.fail("scope must not be requested")

        patches = self.successful_patches(api=api)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            result = AUTH.run_operation(AUTH.OPERATION, True, self.environment)
        self.assertEqual(result["failure_code"], "permissions_rejected")
        self.assertIs(result["permissions_valid"], False)
        self.assertEqual(result["revocation"], "ok")
        self.assertIsNone(result["askpass_cleanup"])

    def test_administration_permission_is_rejected_and_revoked(self) -> None:
        def api(method, path, authorization, payload=None):
            if method == "POST":
                permissions = dict(AUTH.EXPECTED_PERMISSIONS, administration="read")
                return 201, {"token": "TOKEN_FIXTURE", "permissions": permissions}
            if method == "DELETE":
                return 204, {}
            self.fail("scope must not be requested")

        patches = self.successful_patches(api=api)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            result = AUTH.run_operation(AUTH.OPERATION, True, self.environment)
        self.assertEqual(result["failure_code"], "permissions_rejected")
        self.assertIs(result["permissions_valid"], False)
        self.assertEqual(result["revocation"], "ok")

    def test_scope_rejection_revokes_minted_token(self) -> None:
        def api(method, path, authorization, payload=None):
            if method == "POST":
                return 201, {"token": "TOKEN_FIXTURE", "permissions": AUTH.EXPECTED_PERMISSIONS}
            if method == "GET":
                return 200, {"total_count": 2, "repositories": []}
            if method == "DELETE":
                return 204, {}
            self.fail("unexpected request")

        patches = self.successful_patches(api=api)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            result = AUTH.run_operation(AUTH.OPERATION, True, self.environment)
        self.assertEqual(result["failure_code"], "scope_rejected")
        self.assertTrue(result["permissions_valid"])
        self.assertIs(result["scope_valid"], False)
        self.assertEqual(result["revocation"], "ok")

    def test_git_failure_revokes_and_removes_askpass(self) -> None:
        patches = self.successful_patches(git_result=False)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            result = AUTH.run_operation(AUTH.OPERATION, True, self.environment)
        self.assertEqual(result["failure_code"], "git_probe_failed")
        self.assertFalse(result["git_probe"])
        self.assertEqual(result["revocation"], "ok")
        self.assertTrue(result["askpass_cleanup"])

    def test_revocation_failure_fails_closed(self) -> None:
        def api(method, path, authorization, payload=None):
            if method == "DELETE":
                return 500, {}
            return self.api_success(method, path, authorization, payload)

        patches = self.successful_patches(api=api)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            result = AUTH.run_operation(AUTH.OPERATION, True, self.environment)
        self.assertEqual(result["failure_code"], "revocation_failed")
        self.assertEqual(result["revocation"], "failed")
        self.assertTrue(result["askpass_cleanup"])

    def test_key_mode_rejection_requires_no_network_or_signing(self) -> None:
        with tempfile.NamedTemporaryFile() as key_file:
            os.chmod(key_file.name, 0o644)
            environment = dict(self.environment, MEGABRAIN_GITHUB_APP_KEY_PATH=key_file.name)
            with mock.patch.object(AUTH, "configured_origin", return_value=AUTH.EXPECTED_ORIGIN), mock.patch.object(
                AUTH, "make_jwt"
            ) as signer, mock.patch.object(AUTH, "request_json") as request:
                result = AUTH.run_operation(AUTH.OPERATION, True, environment)
        signer.assert_not_called()
        request.assert_not_called()
        self.assertEqual(result["failure_code"], "key_invalid")

    def test_invalid_runtime_identifiers_require_no_signing_or_network(self) -> None:
        environment = dict(self.environment, MEGABRAIN_GITHUB_APP_ID="not-a-number")
        with mock.patch.object(AUTH, "configured_origin", return_value=AUTH.EXPECTED_ORIGIN), mock.patch.object(
            AUTH, "make_jwt"
        ) as signer, mock.patch.object(AUTH, "request_json") as request:
            result = AUTH.run_operation(AUTH.OPERATION, True, environment)
        signer.assert_not_called()
        request.assert_not_called()
        self.assertEqual(result["failure_code"], "environment_missing")

    def test_gate_and_operation_rejection_do_not_touch_runtime_dependencies(self) -> None:
        with mock.patch.object(AUTH, "configured_origin") as origin:
            gate_result = AUTH.run_operation(AUTH.OPERATION, False, self.environment)
            operation_result = AUTH.run_operation("not-allowed", True, self.environment)
        origin.assert_not_called()
        self.assertEqual(gate_result["failure_code"], "operational_gate_required")
        self.assertEqual(operation_result["failure_code"], "operation_rejected")


class CanonicalInstallationTests(unittest.TestCase):
    def test_canonical_source_has_no_secret_files_or_markers(self) -> None:
        source_files = {
            path.relative_to(SKILL_DIRECTORY)
            for path in SKILL_DIRECTORY.rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        }
        self.assertEqual(source_files, {
            Path("SKILL.md"),
            Path("scripts/github_app_auth.py"),
            Path("scripts/install_skill.py"),
            Path("tests/test_github_app_auth.py"),
        })
        markers = (
            "-----" + "BEGIN ",
            "gh" + "p_",
            "github" + "_pat_",
            "gh" + "s_",
            "eyJ" + "hbGciOiJSUzI1Ni",
        )
        for source_file in source_files:
            content = (SKILL_DIRECTORY / source_file).read_text(encoding="utf-8")
            for marker in markers:
                self.assertNotIn(marker, content, source_file)

    def test_clean_install_and_reinstall_reconstruct_only_artifacts(self) -> None:
        expected_artifacts = {
            Path("SKILL.md"): 0o644,
            Path("scripts/github_app_auth.py"): 0o700,
        }
        with tempfile.TemporaryDirectory() as temporary_root:
            destination = Path(temporary_root) / "fresh" / "megabrain-github-app-auth"
            command = [sys.executable, str(INSTALLER_PATH), "--destination", str(destination)]
            first = subprocess.run(command, check=False, capture_output=True, text=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            (destination / "stale.txt").write_text("not source", encoding="utf-8")
            second = subprocess.run(command, check=False, capture_output=True, text=True)
            self.assertEqual(second.returncode, 0, second.stderr)
            actual_files = {path.relative_to(destination) for path in destination.rglob("*") if path.is_file()}
            self.assertEqual(actual_files, set(expected_artifacts))
            self.assertFalse(any(path.name == ".env" or path.suffix in {".pem", ".key"} for path in actual_files))
            for relative_path, expected_mode in expected_artifacts.items():
                source = SKILL_DIRECTORY / relative_path
                derived = destination / relative_path
                self.assertEqual(hashlib.sha256(source.read_bytes()).digest(), hashlib.sha256(derived.read_bytes()).digest())
                self.assertEqual(stat.S_IMODE(derived.stat().st_mode), expected_mode)
            self.assertEqual(stat.S_IMODE(HELPER_PATH.stat().st_mode), 0o700)


if __name__ == "__main__":
    unittest.main()
