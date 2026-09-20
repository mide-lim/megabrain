"""Hermetic R2B coverage for protected B4.1 runtime-config integration."""
from __future__ import annotations

import importlib.util
import os
import stat
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

SKILL = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL / "scripts"


def load(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


class ProtectedRuntimeConfigBridgeTests(unittest.TestCase):
    def test_bridge_rejects_loader_symlink_type_owner_and_mode_without_import(self):
        bridge = load("b42_runtime_bridge_under_test", SCRIPTS / "github_app_runtime_config_bridge.py")
        expected_uid = 1234
        cases = (
            (stat.S_IFLNK | 0o700, expected_uid, "runtime_loader_type_rejected"),
            (stat.S_IFDIR | 0o700, expected_uid, "runtime_loader_type_rejected"),
            (stat.S_IFREG | 0o700, expected_uid + 1, "runtime_loader_owner_rejected"),
            (stat.S_IFREG | 0o755, expected_uid, "runtime_loader_mode_rejected"),
        )
        for mode, uid, code in cases:
            with self.subTest(code=code), mock.patch.object(bridge.pwd, "getpwnam", return_value=SimpleNamespace(pw_uid=expected_uid)), mock.patch.object(
                bridge.os, "lstat", return_value=os.stat_result((mode, 0, 0, 0, uid, 0, 0, 0, 0, 0))
            ), mock.patch.object(bridge.importlib.util, "spec_from_file_location") as importer:
                with self.assertRaisesRegex(bridge.RuntimeConfigBridgeError, code):
                    bridge.load_runtime_settings()
                importer.assert_not_called()

    def test_bridge_maps_loader_failure_without_values(self):
        bridge = load("b42_runtime_bridge_sanitized", SCRIPTS / "github_app_runtime_config_bridge.py")
        expected_uid = 1234
        loader = SimpleNamespace(load_runtime_config=mock.Mock(side_effect=RuntimeError("secret /private/path")))
        specification = SimpleNamespace(name="bridge_fixture", loader=SimpleNamespace(exec_module=lambda module: module.__dict__.update(loader.__dict__)))
        with mock.patch.object(bridge.pwd, "getpwnam", return_value=SimpleNamespace(pw_uid=expected_uid)), mock.patch.object(
            bridge.os, "lstat", return_value=os.stat_result((stat.S_IFREG | 0o700, 0, 0, 0, expected_uid, 0, 0, 0, 0, 0))
        ), mock.patch.object(bridge.importlib.util, "spec_from_file_location", return_value=specification), mock.patch.object(
            bridge.importlib.util, "module_from_spec", return_value=SimpleNamespace()
        ):
            with self.assertRaisesRegex(bridge.RuntimeConfigBridgeError, "runtime_config_load_rejected") as raised:
                bridge.load_runtime_settings()
        self.assertNotIn("secret", str(raised.exception))


class RuntimeAuthoritySurfaceTests(unittest.TestCase):
    def test_p1_is_authorized_only_by_run_authorization_not_public_lifecycle(self):
        lifecycle = load("b42_lifecycle_r2b", SCRIPTS / "autonomous_pr_lifecycle.py")
        self.assertIn("validate-read-dev-ref", lifecycle.RUN_AUTHORIZATION_OPERATIONS)
        self.assertNotIn("validate-read-dev-ref", lifecycle.PUBLIC_OPERATIONS)
        self.assertNotIn("validate_read_dev_ref", lifecycle.Lifecycle.__dict__)

    def test_production_adapters_do_not_consume_legacy_environment_configuration(self):
        names = ("MEGABRAIN_GITHUB_APP_ID", "MEGABRAIN_GITHUB_APP_INSTALLATION_ID", "MEGABRAIN_GITHUB_APP_KEY_PATH")
        for filename in (
            "authenticated_read_validation.py", "authenticated_publish_head.py",
            "authenticated_ensure_pr.py", "authenticated_observe_ci.py",
        ):
            text = (SCRIPTS / filename).read_text(encoding="utf-8")
            with self.subTest(filename=filename):
                self.assertFalse(any(name in text for name in names))
                self.assertNotIn("_required_environment", text)

    def test_p2_p3_p4_guard_failures_precede_runtime_config_jwt_and_api(self):
        for filename, operation in (
            ("authenticated_publish_head.py", "publish-head"),
            ("authenticated_ensure_pr.py", "ensure-pr"),
            ("authenticated_observe_ci.py", "observe-ci"),
        ):
            module = load(f"b42_guard_{operation}", SCRIPTS / filename)

            class GuardFailureLifecycle:
                def __init__(self, *_):
                    pass

                @contextmanager
                def _publish_reservation(self):
                    yield

                def _guard(self, *_):
                    raise module.LIFECYCLE.StopNeedsHuman("run_authorization_operation_denied")

            with self.subTest(operation=operation), mock.patch.object(module.LIFECYCLE, "Lifecycle", GuardFailureLifecycle), mock.patch.object(
                module.RUNTIME_CONFIG, "load_runtime_settings"
            ) as config, mock.patch.object(module, "make_jwt") as jwt, mock.patch.object(module, "request_json") as api:
                result = module.run_operation(operation, "life-1", {
                    "MEGABRAIN_GITHUB_APP_ID": "wrong",
                    "MEGABRAIN_GITHUB_APP_INSTALLATION_ID": "wrong",
                    "MEGABRAIN_GITHUB_APP_KEY_PATH": "/wrong/path",
                })
            self.assertEqual(result["failure_code"], "run_authorization_operation_denied")
            config.assert_not_called(); jwt.assert_not_called(); api.assert_not_called()


class P1AuthorityOrderingTests(unittest.TestCase):
    def setUp(self):
        self.read = load("b42_read_r2b", SCRIPTS / "authenticated_read_validation.py")
        self.settings = SimpleNamespace(app_id="123", installation_id="456", key_path="/fixture/key")

    def test_guard_failure_stops_before_runtime_config_jwt_or_api(self):
        lifecycle = SimpleNamespace(_guard=mock.Mock(side_effect=self.read.LIFECYCLE.StopNeedsHuman("run_authorization_missing")))
        with mock.patch.object(self.read.LIFECYCLE, "Lifecycle", return_value=lifecycle), mock.patch.object(
            self.read.RUNTIME_CONFIG, "load_runtime_settings"
        ) as config, mock.patch.object(self.read, "make_jwt") as jwt, mock.patch.object(self.read, "request_json") as api:
            result = self.read.run_operation(self.read.OPERATION, "life-1")
        self.assertEqual(result["failure_code"], "run_authorization_missing")
        config.assert_not_called(); jwt.assert_not_called(); api.assert_not_called()

    def test_changed_runtime_settings_before_mint_fails_closed_without_token_mint(self):
        lifecycle = SimpleNamespace(_guard=mock.Mock(return_value=({}, {})))
        calls = []
        def api(method, path, authorization, payload=None):
            calls.append((method, path))
            if method == "GET": return 200, {"permissions": self.read.EXPECTED_INSTALLATION_PERMISSIONS}
            self.fail("token mint must not occur")
        with mock.patch.object(self.read.LIFECYCLE, "Lifecycle", return_value=lifecycle), mock.patch.object(
            self.read, "configured_origin", return_value=self.read.ORIGIN
        ), mock.patch.object(self.read.RUNTIME_CONFIG, "load_runtime_settings", side_effect=[self.settings, SimpleNamespace(app_id="999", installation_id="456", key_path="/fixture/key")]), mock.patch.object(
            self.read, "make_jwt", return_value="JWT_FIXTURE"
        ), mock.patch.object(self.read, "request_json", side_effect=api):
            result = self.read.run_operation(self.read.OPERATION, "life-1")
        self.assertEqual(result["failure_code"], "runtime_config_changed_before_mint")
        self.assertEqual(calls, [("GET", "/app/installations/456")])
        self.assertEqual(lifecycle._guard.call_count, 2)
        self.assertEqual(result["revocation"], "not_attempted")
        self.assertIsNone(result["temporary_cleanup"])
        self.assertIsNone(result["token_permissions_valid"])
        self.assertIsNone(result["scope_valid"])
        self.assertIsNone(result["ref_valid"])


if __name__ == "__main__":
    unittest.main()
