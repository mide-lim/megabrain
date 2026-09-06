"""Hermetic P5 local-only correction gate tests."""
from __future__ import annotations

import importlib.util
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SKILL = Path(__file__).resolve().parents[1]
MODULE_PATH = SKILL / "scripts" / "autonomous_pr_lifecycle.py"
SHA = "a" * 40
S2 = "b" * 40


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


L = load("b42_p5_lifecycle", MODULE_PATH)


def contract(allowed=("workflows/*.json",), maximum=1):
    return {
        "allowed_paths": list(allowed),
        "expected_ci_jobs": ["Repository validation", "Enricher tests", "Web tests"],
        "max_corrections": maximum,
        "branch": "agent/p5-test",
    }


def failure(head=SHA, jobs=None):
    return {"head_sha": head, "pr_number": 7, "workflow_run_id": 9, "jobs": jobs or {
        "Repository validation": "failure", "Enricher tests": "success", "Web tests": "success",
    }}


def state(**changes):
    value = {"fingerprint": "f" * 64, "published_once": True, "head_sha": SHA, "ci_sha": None,
             "ci_failure": failure(), "pending_correction_sha": None, "pending_publish_attempted": False,
             "corrections": 0, "pr_number": 7}
    value.update(changes)
    return value


class JsonProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "workflows").mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def test_profile_returns_bounded_json_parse_diagnostic(self):
        fixture = self.root / "workflows" / "P5_PROOF_FIXTURE.json"
        fixture.write_text('{"fixture":', encoding="utf-8")
        result = L.repository_validation_json_v1(self.root, ["workflows/*.json"])
        self.assertEqual(result["profile_id"], "repository-validation-json-v1")
        self.assertEqual(result["result"], "fail")
        self.assertEqual(result["invalid_files"], [{"path": "workflows/P5_PROOF_FIXTURE.json", "reason_code": "json_decode_error", "line": 1, "column": 12}])

    def test_profile_rejects_invalid_json_outside_allowed_paths(self):
        fixture = self.root / "workflows" / "P5_PROOF_FIXTURE.json"
        fixture.write_text('{', encoding="utf-8")
        result = L.repository_validation_json_v1(self.root, ["docs/*.md"])
        self.assertEqual(result["result"], "fail")
        self.assertFalse(L.profile_invalid_paths_allowed(result, self.root, ["docs/*.md"]))

    def test_profile_fails_closed_when_no_workflow_json_files_exist(self):
        result = L.repository_validation_json_v1(self.root, ["workflows/*.json"])
        self.assertEqual(result, {"profile_id": "repository-validation-json-v1", "result": "fail",
                                  "failure_code": "zero_workflow_json_files", "invalid_files": []})

    def test_legacy_state_defaults_are_read_only_values(self):
        legacy = {"head_sha": SHA}
        normalized = L.normalize_p5_state(legacy)
        self.assertIsNone(normalized["ci_failure"])
        self.assertIsNone(normalized["pending_correction_sha"])
        self.assertIs(normalized["pending_publish_attempted"], False)
        self.assertNotIn("ci_failure", legacy)


class CommitJsonProfileTests(unittest.TestCase):
    def test_local_git_read_disables_replace_objects(self):
        binary = mock.Mock(st_mode=stat.S_IFREG | 0o755, st_uid=0)
        completed = mock.Mock(returncode=0, stdout=b"content")
        with mock.patch.object(L.os, "lstat", return_value=binary), \
                mock.patch.object(L.subprocess, "run", return_value=completed) as run:
            self.assertEqual(L._local_git_read(Path("/unused"), ["cat-file", "-e", f"{SHA}^{{commit}}"]), b"content")
        self.assertEqual(run.call_args.kwargs["env"], {
            "PATH": "/usr/bin:/bin",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
        })

    def test_profile_reads_only_validated_exact_blob_objects(self):
        calls = []
        def read(root, arguments):
            calls.append(arguments)
            values = {
                ("cat-file", "-e", f"{SHA}^{{commit}}"): b"",
                ("ls-tree", "-z", SHA, "--", "workflows"): b"040000 tree " + b"c" * 40 + b"\tworkflows\0",
                ("ls-tree", "-z", f"{SHA}:workflows"): b"100644 blob " + b"d" * 40 + b"\tP5_PROOF_FIXTURE.json\0",
                ("cat-file", "blob", "d" * 40): b"{",
            }
            if tuple(arguments) == ("cat-file", "blob", f"{SHA}:workflows/P5_PROOF_FIXTURE.json"):
                raise AssertionError("committed-tree profile must not cat-file by commit:path")
            return values[tuple(arguments)]
        with mock.patch.object(L, "_local_git_read", side_effect=read):
            result = L.repository_validation_json_v1_for_commit(Path("/unused"), SHA, ["workflows/*.json"])
        self.assertEqual(result["result"], "fail")
        self.assertEqual(result["invalid_files"][0]["path"], "workflows/P5_PROOF_FIXTURE.json")
        self.assertEqual(calls, [
            ["cat-file", "-e", f"{SHA}^{{commit}}"], ["ls-tree", "-z", SHA, "--", "workflows"],
            ["ls-tree", "-z", f"{SHA}:workflows"],
            ["cat-file", "blob", "d" * 40],
        ])


class LocalGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "workflows").mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def lifecycle(self, data=None, current=None, head=SHA):
        life = object.__new__(L.Lifecycle)
        life.root = self.root
        data, current = data or contract(), current or state()
        life._guard = lambda: (data, dict(current))
        life._validate_checkout = lambda _: head
        life._correction_count = lambda _, value: value["corrections"]
        life._validate_committed_paths = lambda *_: None
        life._write_state = lambda value: setattr(life, "written", dict(value))
        return life

    def test_authorize_rejects_dirty_s1_worktree(self):
        (self.root / "workflows" / "P5_PROOF_FIXTURE.json").write_text('{', encoding="utf-8")
        life = self.lifecycle()
        life._require_clean_checkout = lambda: (_ for _ in ()).throw(L.StopNeedsHuman("worktree_not_clean"))
        with self.assertRaisesRegex(L.StopNeedsHuman, "worktree_not_clean"):
            life.authorize_correction()

    def test_authorize_reproduces_exact_malformed_json(self):
        (self.root / "workflows" / "P5_PROOF_FIXTURE.json").write_text('{', encoding="utf-8")
        life = self.lifecycle(); life._require_clean_checkout = lambda: None
        receipt = life.authorize_correction()
        self.assertEqual(receipt["result"], "fail")
        self.assertEqual(receipt["invalid_files"][0]["reason_code"], "json_decode_error")

    def test_authorize_rejects_non_reproducible_or_unsupported_failure(self):
        (self.root / "workflows" / "P5_PROOF_FIXTURE.json").write_text('{}', encoding="utf-8")
        life = self.lifecycle(); life._require_clean_checkout = lambda: None
        with self.assertRaisesRegex(L.StopNeedsHuman, "correction_not_reproduced"):
            life.authorize_correction()
        bad = state(ci_failure=failure(jobs={"Repository validation": "success", "Enricher tests": "failure", "Web tests": "success"}))
        life = self.lifecycle(current=bad); life._require_clean_checkout = lambda: None
        with self.assertRaisesRegex(L.StopNeedsHuman, "correction_not_authorized"):
            life.authorize_correction()

    def test_finalize_requires_fixed_message_one_commit_clean_and_writes_pending_sha(self):
        (self.root / "workflows" / "P5_PROOF_FIXTURE.json").write_text('{}', encoding="utf-8")
        current = state()
        life = self.lifecycle(current=current, head=S2)
        life._require_clean_checkout = lambda: None
        def git(*args):
            values = {("rev-parse", "HEAD^"): SHA, ("rev-list", "--count", f"{SHA}..{S2}"): "1",
                      ("log", "-1", "--format=%B", S2): L.CORRECTION_COMMIT_MESSAGE,
                      ("diff", "--check", SHA, S2): ""}
            return values[args]
        life._git = git
        invalid = {"profile_id": "repository-validation-json-v1", "result": "fail",
                   "invalid_files": [{"path": "workflows/P5_PROOF_FIXTURE.json", "reason_code": "json_decode_error", "line": 1, "column": 1}]}
        life._repository_validation_json_v1_for_commit = lambda sha, allowed: invalid if sha == SHA else {
            "profile_id": "repository-validation-json-v1", "result": "pass", "invalid_files": []}
        result = life.finalize_correction()
        self.assertEqual(result, {"state": "CORRECTION_FINALIZED", "head_sha": S2})
        self.assertEqual(life.written["pending_correction_sha"], S2)
        self.assertFalse(life.written["pending_publish_attempted"])

    def test_finalize_directly_reproduces_s1_without_authorize(self):
        """Finalization cannot accept an S2 solely because authorize was skipped."""
        def git(*args):
            values = {("rev-parse", "HEAD^"): SHA, ("rev-list", "--count", f"{SHA}..{S2}"): "1",
                      ("log", "-1", "--format=%B", S2): L.CORRECTION_COMMIT_MESSAGE,
                      ("diff", "--check", SHA, S2): ""}
            return values[args]

        valid = {"profile_id": "repository-validation-json-v1", "result": "pass", "invalid_files": []}
        life = self.lifecycle(head=S2); life._require_clean_checkout = lambda: None; life._git = git
        life._repository_validation_json_v1_for_commit = lambda sha, allowed: valid
        with self.assertRaisesRegex(L.StopNeedsHuman, "correction_not_reproduced"):
            life.finalize_correction()

        malformed = {"profile_id": "repository-validation-json-v1", "result": "fail",
                     "invalid_files": [{"path": "workflows/P5_PROOF_FIXTURE.json", "reason_code": "json_decode_error", "line": 1, "column": 1}]}
        life = self.lifecycle(head=S2); life._require_clean_checkout = lambda: None; life._git = git
        life._repository_validation_json_v1_for_commit = lambda sha, allowed: malformed if sha == SHA else valid
        self.assertEqual(life.finalize_correction(), {"state": "CORRECTION_FINALIZED", "head_sha": S2})

    def test_finalize_rejects_wrong_message_or_second_commit(self):
        (self.root / "workflows" / "P5_PROOF_FIXTURE.json").write_text('{}', encoding="utf-8")
        for count, message, code in (("2", L.CORRECTION_COMMIT_MESSAGE, "correction_commit_count_rejected"), ("1", "bad", "correction_commit_message_rejected")):
            life = self.lifecycle(head=S2); life._require_clean_checkout = lambda: None
            life._git = lambda *args, count=count, message=message: {("rev-parse", "HEAD^"): SHA, ("rev-list", "--count", f"{SHA}..{S2}"): count, ("log", "-1", "--format=%B", S2): message}[args]
            with self.assertRaisesRegex(L.StopNeedsHuman, code):
                life.finalize_correction()


if __name__ == "__main__":
    unittest.main()
