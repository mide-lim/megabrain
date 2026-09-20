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
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

SKILL_DIRECTORY = Path(__file__).resolve().parents[1]
SCRIPTS_DIRECTORY = SKILL_DIRECTORY / "scripts"
HELPER_PATH = SCRIPTS_DIRECTORY / "github_app_auth.py"
RUNTIME_PATH = SCRIPTS_DIRECTORY / "github_app_runtime_config.py"
BOOTSTRAP_PATH = SCRIPTS_DIRECTORY / "bootstrap_runtime_config.py"
INSTALLER_PATH = SCRIPTS_DIRECTORY / "install_skill.py"


def load_module(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


AUTH = load_module("canonical_github_app_auth", HELPER_PATH)
RUNTIME = load_module("canonical_github_app_runtime_config", RUNTIME_PATH)
BOOTSTRAP = load_module("canonical_bootstrap_runtime_config", BOOTSTRAP_PATH)


class GithubAppAuthTests(unittest.TestCase):
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
            return 200, {"permissions": AUTH.EXPECTED_INSTALLATION_PERMISSIONS}
        if method == "POST":
            self.assertEqual(path, "/app/installations/456/access_tokens")
            self.assertEqual(authorization, "Bearer JWT_FIXTURE")
            self.assertEqual(
                payload,
                {"repositories": ["megabrain"], "permissions": AUTH.PROBE_TOKEN_REQUEST_PERMISSIONS},
            )
            return 201, {"token": "TOKEN_FIXTURE", "permissions": AUTH.PROBE_TOKEN_PERMISSIONS_WITH_METADATA}
        if method == "GET" and path == "/installation/repositories":
            self.assertEqual(authorization, "token TOKEN_FIXTURE")
            return 200, {"total_count": 1, "repositories": [{"full_name": AUTH.EXPECTED_REPOSITORY}]}
        if method == "DELETE":
            self.assertEqual(authorization, "token TOKEN_FIXTURE")
            return 204, {}
        self.fail(f"unexpected request {method} {path}")

    def successful_patches(self, git_result=True, api=None):
        return (
            mock.patch.object(AUTH, "configured_origin", return_value=AUTH.EXPECTED_ORIGIN),
            mock.patch.object(AUTH, "load_runtime_config", return_value=RUNTIME.RuntimeConfig("123", "456", "/fixture/key")),
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
        self.assertTrue(result["installation_permissions_valid"])
        self.assertTrue(result["probe_token_permissions_valid"])
        self.assertTrue(all(level == "read" for level in AUTH.PROBE_TOKEN_PERMISSIONS_WITH_METADATA.values()))
        self.assertTrue(result["scope_valid"])
        self.assertTrue(result["git_probe"])
        self.assertEqual(result["revocation"], "ok")
        self.assertTrue(result["askpass_cleanup"])
        encoded = json.dumps(result, sort_keys=True)
        self.assertNotIn("TOKEN_FIXTURE", encoded)
        self.assertNotIn("JWT_FIXTURE", encoded)
        self.assertNotIn(self.environment["MEGABRAIN_GITHUB_APP_KEY_PATH"], encoded)

    def test_contents_read_is_sufficient_when_metadata_is_not_returned(self) -> None:
        def api(method, path, authorization, payload=None):
            if method == "GET" and path == "/app/installations/456":
                return 200, {"permissions": AUTH.EXPECTED_INSTALLATION_PERMISSIONS}
            if method == "POST":
                return 201, {"token": "TOKEN_FIXTURE", "permissions": {"contents": "read"}}
            if method == "GET" and path == "/installation/repositories":
                return 200, {"total_count": 1, "repositories": [{"full_name": AUTH.EXPECTED_REPOSITORY}]}
            if method == "DELETE":
                return 204, {}
            self.fail("unexpected request")

        patches = self.successful_patches(api=api)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            result = AUTH.run_operation(AUTH.OPERATION, True, self.environment)
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["probe_token_permissions_valid"])

    def test_origin_rejection_happens_before_signing(self) -> None:
        with mock.patch.object(AUTH, "configured_origin", return_value="https://example.invalid/repo.git"), mock.patch.object(
            AUTH, "make_jwt"
        ) as signer:
            result = AUTH.run_operation(AUTH.OPERATION, True, self.environment)
        signer.assert_not_called()
        self.assertEqual(result["failure_code"], "origin_rejected")
        self.assertEqual(result["revocation"], "not_attempted")

    def test_probe_token_write_rejection_revokes_minted_token(self) -> None:
        def api(method, path, authorization, payload=None):
            if method == "GET" and path == "/app/installations/456":
                return 200, {"permissions": AUTH.EXPECTED_INSTALLATION_PERMISSIONS}
            if method == "POST":
                permissions = dict(AUTH.PROBE_TOKEN_PERMISSIONS_WITH_METADATA, contents="write")
                return 201, {"token": "TOKEN_FIXTURE", "permissions": permissions}
            if method == "DELETE":
                return 204, {}
            self.fail("scope must not be requested")

        patches = self.successful_patches(api=api)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            result = AUTH.run_operation(AUTH.OPERATION, True, self.environment)
        self.assertEqual(result["failure_code"], "probe_token_permissions_rejected")
        self.assertTrue(result["installation_permissions_valid"])
        self.assertIs(result["probe_token_permissions_valid"], False)
        self.assertEqual(result["revocation"], "ok")
        self.assertIsNone(result["askpass_cleanup"])

    def test_administration_in_installation_baseline_is_rejected_before_token_minting(self) -> None:
        def api(method, path, authorization, payload=None):
            if method == "GET" and path == "/app/installations/456":
                permissions = dict(AUTH.EXPECTED_INSTALLATION_PERMISSIONS, administration="read")
                return 200, {"permissions": permissions}
            self.fail("token must not be minted")

        patches = self.successful_patches(api=api)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            result = AUTH.run_operation(AUTH.OPERATION, True, self.environment)
        self.assertEqual(result["failure_code"], "installation_permissions_rejected")
        self.assertIs(result["installation_permissions_valid"], False)
        self.assertIsNone(result["probe_token_permissions_valid"])
        self.assertEqual(result["revocation"], "not_attempted")

    def test_scope_rejection_revokes_minted_token(self) -> None:
        def api(method, path, authorization, payload=None):
            if method == "GET" and path == "/app/installations/456":
                return 200, {"permissions": AUTH.EXPECTED_INSTALLATION_PERMISSIONS}
            if method == "POST":
                return 201, {"token": "TOKEN_FIXTURE", "permissions": AUTH.PROBE_TOKEN_PERMISSIONS_WITH_METADATA}
            if method == "GET" and path == "/installation/repositories":
                return 200, {"total_count": 2, "repositories": []}
            if method == "DELETE":
                return 204, {}
            self.fail("unexpected request")

        patches = self.successful_patches(api=api)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            result = AUTH.run_operation(AUTH.OPERATION, True, self.environment)
        self.assertEqual(result["failure_code"], "scope_rejected")
        self.assertTrue(result["installation_permissions_valid"])
        self.assertTrue(result["probe_token_permissions_valid"])
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

    def test_runtime_config_rejection_requires_no_network_or_signing(self) -> None:
        with mock.patch.object(AUTH, "configured_origin", return_value=AUTH.EXPECTED_ORIGIN), mock.patch.object(
            AUTH, "load_runtime_config", side_effect=AUTH.SafeFailure("runtime_config_mode_rejected")
        ), mock.patch.object(AUTH, "make_jwt") as signer, mock.patch.object(AUTH, "request_json") as request:
            result = AUTH.run_operation(AUTH.OPERATION, True, self.environment)
        signer.assert_not_called()
        request.assert_not_called()
        self.assertEqual(result["failure_code"], "runtime_config_mode_rejected")

    def test_environment_values_are_ignored_by_runtime_loader_path(self) -> None:
        with mock.patch.object(AUTH, "configured_origin", return_value=AUTH.EXPECTED_ORIGIN), mock.patch.object(
            AUTH, "load_runtime_config", side_effect=AUTH.SafeFailure("runtime_config_missing")
        ) as loader, mock.patch.object(AUTH, "make_jwt") as signer, mock.patch.object(AUTH, "request_json") as request:
            result = AUTH.run_operation(AUTH.OPERATION, True, self.environment)
        loader.assert_called_once_with()
        signer.assert_not_called()
        request.assert_not_called()
        self.assertEqual(result["failure_code"], "runtime_config_missing")

    def test_gate_and_operation_rejection_do_not_touch_runtime_dependencies(self) -> None:
        with mock.patch.object(AUTH, "configured_origin") as origin, mock.patch.object(AUTH, "load_runtime_config") as loader:
            gate_result = AUTH.run_operation(AUTH.OPERATION, False, self.environment)
            operation_result = AUTH.run_operation("not-allowed", True, self.environment)
        origin.assert_not_called()
        loader.assert_not_called()
        self.assertEqual(gate_result["failure_code"], "operational_gate_required")
        self.assertEqual(operation_result["failure_code"], "operation_rejected")


class RuntimeConfigTests(unittest.TestCase):
    @contextmanager
    def fixture(self, config_text=None, *, config_mode=0o600, key_mode=0o600):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "runtime.conf"
            key = root / "private-key.pem"
            key.write_text("fixture-key", encoding="utf-8")
            os.chmod(key, key_mode)
            if config_text is not None:
                config.write_bytes(config_text if isinstance(config_text, bytes) else config_text.encode("utf-8"))
                os.chmod(config, config_mode)
            with mock.patch.object(RUNTIME, "CONFIG_PATH", config), mock.patch.object(
                RUNTIME, "APPROVED_KEY_PATH", key
            ), mock.patch.object(RUNTIME, "_validate_parent_chain"):
                yield config, key

    def valid_text(self, key: Path) -> str:
        return "github_app_id=123\ngithub_app_installation_id=456\nprivate_key_path=" + str(key) + "\n"

    def test_valid_config_returns_immutable_settings(self) -> None:
        with self.fixture() as (config, key):
            config.write_text(self.valid_text(key), encoding="utf-8")
            os.chmod(config, 0o600)
            settings = RUNTIME.load_runtime_config()
        self.assertEqual((settings.app_id, settings.installation_id, settings.key_path), ("123", "456", str(key)))
        with self.assertRaises(AttributeError):
            settings.app_id = "789"

    def test_missing_symlink_owner_group_and_mode_fail_closed(self) -> None:
        with self.fixture() as (config, key):
            with self.assertRaisesRegex(RUNTIME.RuntimeConfigError, "runtime_config_missing"):
                RUNTIME.load_runtime_config()
            config.symlink_to(key)
            with self.assertRaisesRegex(RUNTIME.RuntimeConfigError, "runtime_config_type_rejected"):
                RUNTIME.load_runtime_config()
            config.unlink()
            config.write_text(self.valid_text(key), encoding="utf-8")
            for mode in (0o640, 0o644, 0o700):
                os.chmod(config, mode)
                with self.assertRaisesRegex(RUNTIME.RuntimeConfigError, "runtime_config_mode_rejected"):
                    RUNTIME.load_runtime_config()

    def test_schema_and_encoding_rejections(self) -> None:
        cases = {
            "unknown": "unknown=value\ngithub_app_id=123\ngithub_app_installation_id=456\n",
            "duplicate": "github_app_id=123\ngithub_app_id=456\nprivate_key_path=/x\n",
            "missing": "github_app_id=123\nprivate_key_path=/x\n",
            "blank": "github_app_id=123\n\nprivate_key_path=/x\n",
            "quote": "github_app_id='123'\ngithub_app_installation_id=456\nprivate_key_path=/x\n",
            "shell": "github_app_id=$(123)\ngithub_app_installation_id=456\nprivate_key_path=/x\n",
            "expansion": "github_app_id=$VALUE\ngithub_app_installation_id=456\nprivate_key_path=/x\n",
            "whitespace": "github_app_id=123 \ngithub_app_installation_id=456\nprivate_key_path=/x\n",
            "identifier": "github_app_id=x\ngithub_app_installation_id=456\nprivate_key_path=/x\n",
        }
        for label, text in cases.items():
            with self.subTest(label=label), self.fixture(text) as (config, _key):
                with self.assertRaises(RUNTIME.RuntimeConfigError):
                    RUNTIME.load_runtime_config()
        for payload, code in ((b"\xff", "runtime_config_encoding_rejected"), (b"\xef\xbb\xbfgithub_app_id=123\n", "runtime_config_bom_rejected")):
            with self.subTest(code=code), self.fixture(payload) as (_config, _key):
                with self.assertRaisesRegex(RUNTIME.RuntimeConfigError, code):
                    RUNTIME.load_runtime_config()

    def test_key_path_and_key_trust_rejections(self) -> None:
        with self.fixture() as (config, key):
            config.write_text("github_app_id=123\ngithub_app_installation_id=456\nprivate_key_path=relative.pem\n", encoding="utf-8")
            os.chmod(config, 0o600)
            with self.assertRaisesRegex(RUNTIME.RuntimeConfigError, "runtime_config_key_path_rejected"):
                RUNTIME.load_runtime_config()
            config.write_text(self.valid_text(key), encoding="utf-8")
            key.unlink()
            with self.assertRaisesRegex(RUNTIME.RuntimeConfigError, "runtime_key_missing"):
                RUNTIME.load_runtime_config()
            key.write_text("fixture", encoding="utf-8")
            os.chmod(key, 0o644)
            with self.assertRaisesRegex(RUNTIME.RuntimeConfigError, "runtime_key_mode_rejected"):
                RUNTIME.load_runtime_config()
            key.unlink()
            key.symlink_to(config)
            with self.assertRaisesRegex(RUNTIME.RuntimeConfigError, "runtime_key_type_rejected"):
                RUNTIME.load_runtime_config()

    def test_changed_config_between_lstat_and_fstat_is_rejected(self) -> None:
        with self.fixture() as (config, key):
            config.write_text(self.valid_text(key), encoding="utf-8")
            os.chmod(config, 0o600)
            original_open = RUNTIME.os.open
            replacement = config.with_name("replacement.conf")
            replacement.write_text(self.valid_text(key), encoding="utf-8")
            os.chmod(replacement, 0o600)

            def swap_then_open(path, flags, *args, **kwargs):
                if Path(path) == config:
                    os.replace(replacement, config)
                return original_open(path, flags, *args, **kwargs)

            with mock.patch.object(RUNTIME.os, "open", side_effect=swap_then_open):
                with self.assertRaisesRegex(RUNTIME.RuntimeConfigError, "runtime_config_changed"):
                    RUNTIME.load_runtime_config()


class BootstrapTests(unittest.TestCase):
    def test_non_tty_rejection_has_no_file_or_network_side_effect(self) -> None:
        with mock.patch.object(BOOTSTRAP.os, "open") as open_file:
            result = BOOTSTRAP.run_bootstrap(stdin=mock.Mock(isatty=mock.Mock(return_value=False)), stdout=mock.Mock(isatty=mock.Mock(return_value=False)))
        open_file.assert_not_called()
        self.assertEqual(result, {"status": "failed", "failure_code": "bootstrap_tty_required", "config_written": False})

    def test_replacement_requires_separate_human_maintenance(self) -> None:
        tty = mock.Mock(isatty=mock.Mock(return_value=True))
        result = BOOTSTRAP.run_bootstrap(replace=True, stdin=tty, stdout=tty)
        self.assertEqual(result["failure_code"], "bootstrap_replacement_requires_human_maintenance")
        self.assertFalse(result["config_written"])

    def test_bootstrap_writes_only_hermetic_fixed_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "runtime.conf"
            key = root / "private-key.pem"
            key.write_text("fixture", encoding="utf-8")
            fake_runtime = mock.Mock()
            fake_runtime.CONFIG_PATH = config
            fake_runtime.APPROVED_KEY_PATH = key
            fake_runtime._identity.return_value = (os.getuid(), os.getgid())
            fake_runtime.load_runtime_config.return_value = object()
            tty = mock.Mock(isatty=mock.Mock(return_value=True))
            with mock.patch.object(BOOTSTRAP, "RUNTIME", fake_runtime), mock.patch.object(
                BOOTSTRAP.getpass, "getpass", side_effect=["123", "456"]
            ):
                result = BOOTSTRAP.run_bootstrap(stdin=tty, stdout=tty)
            self.assertEqual(result, {"status": "ok", "failure_code": None, "config_written": True})
            self.assertEqual(stat.S_IMODE(config.stat().st_mode), 0o600)
            self.assertEqual(config.read_text(encoding="utf-8"), "github_app_id=123\ngithub_app_installation_id=456\nprivate_key_path=" + str(key) + "\n")
            fake_runtime._validate_parent_chain.assert_called_once()
            fake_runtime._validate_key.assert_called_once()
            fake_runtime.load_runtime_config.assert_called_once_with()

    def test_bootstrap_module_has_no_network_git_or_signing_imports(self) -> None:
        content = BOOTSTRAP_PATH.read_text(encoding="utf-8")
        for forbidden in ("urllib", "subprocess", "openssl", "request_json", "make_jwt", "GIT_ASKPASS"):
            self.assertNotIn(forbidden, content)


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
            Path("scripts/github_app_runtime_config.py"),
            Path("scripts/bootstrap_runtime_config.py"),
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
            Path("scripts/github_app_runtime_config.py"): 0o700,
            Path("scripts/bootstrap_runtime_config.py"): 0o700,
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
