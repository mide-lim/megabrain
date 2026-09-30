"""Hermetic tests for the fixed existing-branch fast-forward adapter."""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SKILL = Path(__file__).resolve().parents[1]
MODULE_PATH = SKILL / "scripts" / "authenticated_existing_branch_fast_forward.py"


def load_module():
    specification = importlib.util.spec_from_file_location("existing_branch_fast_forward", MODULE_PATH)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


ADAPTER = load_module()
NOW = dt.datetime(2026, 9, 28, 12, 0, tzinfo=dt.timezone.utc)


class ExistingBranchFastForwardTests(unittest.TestCase):
    def authorization(self, **overrides):
        value = {
            "version": 1,
            "authorization_id": ADAPTER.AUTHORIZATION_ID,
            "repository": ADAPTER.REPOSITORY,
            "target_ref": ADAPTER.TARGET_REF,
            "expected_old_sha": ADAPTER.EXPECTED_OLD_SHA,
            "authorized_new_sha": ADAPTER.AUTHORIZED_NEW_SHA,
            "authorized_new_tree": ADAPTER.AUTHORIZED_NEW_TREE,
            "authorized_new_parent": ADAPTER.AUTHORIZED_NEW_PARENT,
            "expected_dev_sha": ADAPTER.EXPECTED_DEV_SHA,
            "issued_at": "2026-09-28T11:00:00Z",
            "expires_at": "2026-09-28T13:00:00Z",
        }
        value.update(overrides)
        return value

    def test_exact_tuple_accepted(self):
        ADAPTER.validate_authorization_value(self.authorization(), NOW)

    def test_wrong_repository_rejected(self):
        with self.assertRaisesRegex(ADAPTER.StopSourceDrift, "authorization_tuple_rejected"):
            ADAPTER.validate_authorization_value(self.authorization(repository="other/repository"), NOW)

    def test_wrong_dev_sha_rejected(self):
        with self.assertRaisesRegex(ADAPTER.StopSourceDrift, "authorization_tuple_rejected"):
            ADAPTER.validate_authorization_value(self.authorization(expected_dev_sha="a" * 40), NOW)

    def test_wrong_target_branch_ref_rejected(self):
        with self.assertRaisesRegex(ADAPTER.StopSourceDrift, "authorization_tuple_rejected"):
            ADAPTER.validate_authorization_value(self.authorization(target_ref="refs/heads/dev"), NOW)

    def test_wrong_old_sha_rejected(self):
        with self.assertRaisesRegex(ADAPTER.StopSourceDrift, "authorization_tuple_rejected"):
            ADAPTER.validate_authorization_value(self.authorization(expected_old_sha="a" * 40), NOW)

    def test_wrong_new_sha_rejected(self):
        with self.assertRaisesRegex(ADAPTER.StopSourceDrift, "authorization_tuple_rejected"):
            ADAPTER.validate_authorization_value(self.authorization(authorized_new_sha="a" * 40), NOW)

    def test_wrong_new_tree_rejected(self):
        with self.assertRaisesRegex(ADAPTER.StopSourceDrift, "authorization_tuple_rejected"):
            ADAPTER.validate_authorization_value(self.authorization(authorized_new_tree="a" * 40), NOW)

    def test_new_commit_with_wrong_parent_rejected(self):
        with self.assertRaisesRegex(ADAPTER.StopSourceDrift, "commit_parent_rejected"):
            ADAPTER.validate_commit_metadata(ADAPTER.AUTHORIZED_NEW_SHA, ADAPTER.AUTHORIZED_NEW_TREE, ["a" * 40])

    def test_new_commit_with_multiple_parents_rejected(self):
        with self.assertRaisesRegex(ADAPTER.StopSourceDrift, "commit_parent_rejected"):
            ADAPTER.validate_commit_metadata(ADAPTER.AUTHORIZED_NEW_SHA, ADAPTER.AUTHORIZED_NEW_TREE, [ADAPTER.EXPECTED_OLD_SHA, "a" * 40])

    def test_dirty_worktree_rejected(self):
        with self.assertRaisesRegex(ADAPTER.StopSourceDrift, "worktree_dirty"):
            ADAPTER.validate_clean_state("M skills/example", "")

    def test_dirty_index_rejected(self):
        with self.assertRaisesRegex(ADAPTER.StopSourceDrift, "index_dirty"):
            ADAPTER.validate_clean_state("", "M skills/example")

    def test_remote_old_sha_exact_permits_preparation(self):
        self.assertEqual(ADAPTER.classify_remote(ADAPTER.EXPECTED_OLD_SHA), "PREPARE")

    def test_remote_already_new_is_read_only(self):
        self.assertEqual(ADAPTER.classify_remote(ADAPTER.AUTHORIZED_NEW_SHA), "ALREADY_AT_AUTHORIZED_HEAD")

    def test_missing_remote_branch_rejected(self):
        with self.assertRaisesRegex(ADAPTER.StopRemoteDrift, "STOP_REMOTE_BRANCH_MISSING"):
            ADAPTER.classify_remote(None)

    def test_unrelated_remote_sha_rejected(self):
        with self.assertRaisesRegex(ADAPTER.StopRemoteDrift, "STOP_REMOTE_DRIFT"):
            ADAPTER.classify_remote("a" * 40)

    def test_exact_lease_argument_includes_explicit_ref_and_old_sha(self):
        command = ADAPTER.build_push_command()
        self.assertIn(f"--force-with-lease={ADAPTER.TARGET_REF}:{ADAPTER.EXPECTED_OLD_SHA}", command)

    def test_no_unconditional_force_exists(self):
        command = ADAPTER.build_push_command()
        self.assertNotIn("--force", command)

    def test_only_one_refspec_is_constructed(self):
        command = ADAPTER.build_push_command()
        self.assertEqual(command[-1:], [f"{ADAPTER.AUTHORIZED_NEW_SHA}:{ADAPTER.TARGET_REF}"])
        self.assertEqual(sum(":" in part and part.endswith(ADAPTER.TARGET_REF) for part in command), 1)

    def test_branch_deletion_refspec_is_impossible(self):
        self.assertNotIn(":", ADAPTER.build_push_command()[-1][0:0])
        self.assertFalse(ADAPTER.is_allowed_controlled_command(["git", "push", "origin", f":{ADAPTER.TARGET_REF}"]))

    def test_one_push_attempt_maximum(self):
        gate = ADAPTER.PushAttemptGate()
        gate.claim()
        with self.assertRaisesRegex(ADAPTER.StopPostWriteVerification, "push_attempt_exhausted"):
            gate.claim()

    def test_post_write_target_mismatch_fails_without_retry(self):
        gate = ADAPTER.PushAttemptGate()
        gate.claim()
        with self.assertRaisesRegex(ADAPTER.StopPostWriteVerification, "STOP_POST_WRITE_VERIFICATION"):
            ADAPTER.verify_post_write("a" * 40, ADAPTER.EXPECTED_DEV_SHA)
        self.assertEqual(gate.attempts, 1)

    def test_dev_drift_after_write_is_reported_without_second_write(self):
        gate = ADAPTER.PushAttemptGate()
        gate.claim()
        with self.assertRaisesRegex(ADAPTER.StopPostWriteVerification, "dev_drift_after_write"):
            ADAPTER.verify_post_write(ADAPTER.AUTHORIZED_NEW_SHA, "a" * 40)
        self.assertEqual(gate.attempts, 1)

    def test_authorization_expired_rejected(self):
        with self.assertRaisesRegex(ADAPTER.StopSourceDrift, "authorization_expired"):
            ADAPTER.validate_authorization_value(self.authorization(expires_at="2026-09-28T11:59:59Z"), NOW)

    def test_authorization_duplicate_key_rejected(self):
        duplicate = '{"version":1,"version":1}'
        with self.assertRaisesRegex(ADAPTER.StopSourceDrift, "authorization_schema_rejected"):
            ADAPTER.parse_strict_json(duplicate)

    def test_authorization_wrong_ownership_or_mode_rejected(self):
        bad_owner = os.stat_result((stat.S_IFREG | 0o600, 0, 0, 0, 1000, 0, 0, 0, 0, 0))
        bad_mode = os.stat_result((stat.S_IFREG | 0o640, 0, 0, 0, 0, 0, 0, 0, 0, 0))
        with mock.patch.object(ADAPTER.os, "lstat", return_value=bad_owner):
            with self.assertRaisesRegex(ADAPTER.StopSourceDrift, "authorization_trust_rejected"):
                ADAPTER.validate_trusted_path(Path("/etc/megabrain/test.json"), file_expected=True)
        with mock.patch.object(ADAPTER.os, "lstat", return_value=bad_mode):
            with self.assertRaisesRegex(ADAPTER.StopSourceDrift, "authorization_trust_rejected"):
                ADAPTER.validate_trusted_path(Path("/etc/megabrain/test.json"), file_expected=True)

    def test_credential_not_minted_when_remote_is_already_new(self):
        mint = mock.Mock()
        result = ADAPTER.decide_before_mint(ADAPTER.AUTHORIZED_NEW_SHA, mint)
        self.assertEqual(result, "ALREADY_AT_AUTHORIZED_HEAD")
        mint.assert_not_called()

    def test_credential_not_minted_when_preflight_fails(self):
        mint = mock.Mock()
        with self.assertRaisesRegex(ADAPTER.StopSourceDrift, "worktree_dirty"):
            ADAPTER.preflight_and_maybe_mint("M file", "", ADAPTER.EXPECTED_OLD_SHA, mint)
        mint.assert_not_called()

    def test_token_and_jwt_are_not_emitted(self):
        rendered = json.dumps(ADAPTER.sanitized_result("failed", "fixture_failure"), sort_keys=True)
        self.assertNotIn("TOKEN_FIXTURE", rendered)
        self.assertNotIn("JWT_FIXTURE", rendered)

    def test_protected_autonomous_lifecycle_files_remain_untouched(self):
        protected = "skills/megabrain-autonomous-pr-lifecycle/"
        changed = [path.as_posix() for path in SKILL.rglob("*") if path.is_file()]
        self.assertFalse(any(path.startswith(protected) for path in changed))

    def test_static_security_constraints(self):
        source = MODULE_PATH.read_text(encoding="utf-8")
        forbidden = ("shell=True", "eval(", "exec(", "os.system", "os.environ.get")
        self.assertFalse(any(marker in source for marker in forbidden))
        self.assertNotIn("add_argument", source)


if __name__ == "__main__":
    unittest.main()
