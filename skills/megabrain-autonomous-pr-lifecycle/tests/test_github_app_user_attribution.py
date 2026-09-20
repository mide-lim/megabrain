"""Hermetic tests for GitHub App user-to-server PR attribution."""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

import importlib.util
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
MODULE_PATH = SKILL / "scripts" / "github_app_user_attribution.py"


def load(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


ATTR = load("b42_github_app_user_attribution", MODULE_PATH)


def settings():
    return ATTR.UserAttributionSettings(
        client_id="Iv1.fixture123",
        expected_login=ATTR.EXPECTED_LOGIN,
        client_secret_path=str(ATTR.CLIENT_SECRET_PATH),
        refresh_token_path=str(ATTR.REFRESH_TOKEN_PATH),
    )


class UserAttributionTests(unittest.TestCase):
    def test_fixed_config_writer_accepts_multiline_config_only_for_fixed_config_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            config_path = directory / "user-attribution.conf"
            secret_path = directory / "client-secret.txt"
            uid, gid = os.geteuid(), os.getegid()
            with (
                mock.patch.object(ATTR, "CONFIG_DIRECTORY", directory),
                mock.patch.object(ATTR, "CONFIG_PATH", config_path),
                mock.patch.object(ATTR, "_identity", return_value=(uid, gid)),
                mock.patch.object(ATTR, "_validate_parent_chain"),
            ):
                ATTR._write_fixed_file(config_path, "first=value\nsecond=value")
                self.assertEqual(config_path.read_text(encoding="utf-8"), "first=value\nsecond=value\n")
                with self.assertRaisesRegex(ATTR.UserAttributionError, "user_attribution_write_rejected"):
                    ATTR._write_fixed_file(secret_path, "secret\nsecond-line")

    def test_scoped_permission_and_scope_validators_are_exact(self):
        self.assertTrue(ATTR._valid_scoped_permissions({"pull_requests": "write"}))
        self.assertTrue(ATTR._valid_scoped_permissions({"pull_requests": "write", "metadata": "read"}))
        self.assertFalse(ATTR._valid_scoped_permissions({"pull_requests": "read"}))
        self.assertFalse(ATTR._valid_scoped_permissions({"pull_requests": "write", "contents": "read"}))
        good_scope = {
            "total_count": 1,
            "repositories": [{"full_name": ATTR.REPOSITORY}],
        }
        self.assertTrue(ATTR._valid_exact_repository_scope(good_scope))
        self.assertFalse(ATTR._valid_exact_repository_scope({
            "total_count": 2,
            "repositories": [{"full_name": ATTR.REPOSITORY}, {"full_name": "other/repo"}],
        }))

    def test_mint_refreshes_rotates_scopes_and_binds_actor(self):
        config = settings()
        scope = {"total_count": 1, "repositories": [{"full_name": ATTR.REPOSITORY}]}
        scoped_response = {
            "token": "ghu_scoped_fixture",
            "user": {"login": ATTR.EXPECTED_LOGIN},
            "installation": {"permissions": {"pull_requests": "write", "metadata": "read"}},
        }
        api_responses = [
            (200, {"login": ATTR.EXPECTED_LOGIN, "type": "User"}),
            (200, {"total_count": 1, "repositories": [{"full_name": ATTR.REPOSITORY}]}),
            (200, scoped_response),
            (200, {"login": ATTR.EXPECTED_LOGIN, "type": "User"}),
            (200, scope),
        ]
        oauth_response = {
            "access_token": "ghu_broad_fixture",
            "refresh_token": "ghr_new_fixture",
            "token_type": "bearer",
            "expires_in": 28800,
            "refresh_token_expires_in": 15897600,
        }
        with (
            mock.patch.object(ATTR, "load_user_attribution_settings", side_effect=[config, config]),
            mock.patch.object(ATTR, "_read_refresh_token", return_value="ghr_old_fixture"),
            mock.patch.object(ATTR, "_read_client_secret", return_value="secret_fixture"),
            mock.patch.object(ATTR, "_oauth_form", return_value=(200, oauth_response)) as oauth,
            mock.patch.object(ATTR, "_write_refresh_token") as rotate,
            mock.patch.object(ATTR, "_api_json", side_effect=api_responses),
        ):
            credential = ATTR.mint_scoped_pr_credential("456")
        self.assertEqual(credential.actor_login, ATTR.EXPECTED_LOGIN)
        self.assertEqual(credential.token, "ghu_scoped_fixture")
        self.assertEqual(credential.permissions["pull_requests"], "write")
        self.assertEqual(credential.scope, scope)
        rotate.assert_called_once_with(config, "ghr_new_fixture")
        self.assertEqual(oauth.call_args.args[0], ATTR.OAUTH_TOKEN_URL)

    def test_wrong_actor_fails_before_scoped_token_creation(self):
        config = settings()
        oauth_response = {
            "access_token": "ghu_broad_fixture",
            "refresh_token": "ghr_new_fixture",
            "token_type": "bearer",
            "expires_in": 28800,
            "refresh_token_expires_in": 15897600,
        }
        with (
            mock.patch.object(ATTR, "load_user_attribution_settings", return_value=config),
            mock.patch.object(ATTR, "_read_refresh_token", return_value="ghr_old_fixture"),
            mock.patch.object(ATTR, "_oauth_form", return_value=(200, oauth_response)),
            mock.patch.object(ATTR, "_write_refresh_token"),
            mock.patch.object(ATTR, "_api_json", return_value=(200, {"login": "other-user", "type": "User"})),
        ):
            with self.assertRaisesRegex(ATTR.UserAttributionError, "user_attribution_actor_rejected"):
                ATTR.mint_scoped_pr_credential("456")

    def test_failed_scoped_scope_revokes_candidate(self):
        config = settings()
        scoped_response = {
            "token": "ghu_scoped_fixture",
            "user": {"login": ATTR.EXPECTED_LOGIN},
            "installation": {"permissions": {"pull_requests": "write"}},
        }
        responses = [
            (200, scoped_response),
            (200, {"login": ATTR.EXPECTED_LOGIN, "type": "User"}),
            (200, {
                "total_count": 2,
                "repositories": [
                    {"full_name": ATTR.REPOSITORY},
                    {"full_name": "other/repo"},
                ],
            }),
        ]
        with (
            mock.patch.object(ATTR, "_api_json", side_effect=responses),
            mock.patch.object(ATTR, "revoke_token_with_secret", return_value=True) as revoke,
        ):
            with self.assertRaisesRegex(ATTR.UserAttributionError, "scoped_token_scope_rejected"):
                ATTR.create_scoped_pr_credential_from_access(
                    config, "ghu_broad_fixture", "secret_fixture", "456",
                )
        revoke.assert_called_once_with(config.client_id, "secret_fixture", "ghu_scoped_fixture")

    def test_revoke_fails_closed_when_runtime_settings_change(self):
        config = settings()
        changed = ATTR.UserAttributionSettings(
            client_id="Iv1.changed123",
            expected_login=ATTR.EXPECTED_LOGIN,
            client_secret_path=str(ATTR.CLIENT_SECRET_PATH),
            refresh_token_path=str(ATTR.REFRESH_TOKEN_PATH),
        )
        credential = ATTR.ScopedPrCredential(
            token="ghu_scoped_fixture",
            actor_login=ATTR.EXPECTED_LOGIN,
            permissions={"pull_requests": "write"},
            scope={"total_count": 1, "repositories": [{"full_name": ATTR.REPOSITORY}]},
            settings=config,
        )
        with mock.patch.object(ATTR, "load_user_attribution_settings", return_value=changed):
            self.assertFalse(ATTR.revoke_scoped_pr_credential(credential))


if __name__ == "__main__":
    unittest.main()
