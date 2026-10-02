import json
import pathlib
import subprocess
import sys
import tempfile
import unittest


SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "session_context.py"
REF = "https://github.com/mide-lim/megabrain/pull/90"


class SessionContextTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "-b", "agent/test-context")
        self.git("config", "user.name", "Context test")
        self.git("config", "user.email", "context-test@example.invalid")
        self.git("remote", "add", "origin", "https://github.com/mide-lim/megabrain.git")
        for name in ["AGENTS.md", "docs/CONTEXT.md", "docs/DECISIONS.md", "docs/packet.md", "evidence/context-handoffs/checkpoint.md"]:
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# Test context\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-m", "context fixture")
        self.base = self.git("rev-parse", "HEAD").stdout.strip()
        self.snapshot = self.root / "snapshot.json"

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args],
                              capture_output=True, text=True, check=True)

    def cli(self, name, *args):
        return subprocess.run([sys.executable, str(SCRIPT), name,
                               "--repo", str(self.repo), "--task-ref", REF, *args],
                              capture_output=True, text=True)

    def capture(self, *extra):
        return self.cli("capture", "--base", self.base, "--packet", "docs/packet.md",
                        "--checkpoint", "evidence/context-handoffs/checkpoint.md",
                        "--next-step", "Read contract and verify resources", "--output", str(self.snapshot), *extra)

    def verify(self):
        return self.cli("verify", "--snapshot", str(self.snapshot))

    def test_fresh_process_recovers_pinned_refs_and_next_step(self):
        self.assertEqual(self.capture().returncode, 0)
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stdout)
        saved = json.loads(result.stdout)
        self.assertEqual(saved["git"]["head"], self.base)
        self.assertEqual(saved["next_step"], "Read contract and verify resources")
        self.assertEqual(len(saved["read_before_execution"]), 5)

    def test_changed_head_blocks_and_preserves_git(self):
        self.assertEqual(self.capture().returncode, 0)
        (self.repo / "docs/packet.md").write_text("# Revised scope\n")
        self.git("add", ".")
        self.git("commit", "-m", "different candidate")
        before = self.git("rev-parse", "HEAD").stdout
        self.assertEqual(self.verify().returncode, 2)
        self.assertEqual(self.git("rev-parse", "HEAD").stdout, before)

    def test_same_head_on_different_branch_blocks(self):
        self.assertEqual(self.capture().returncode, 0)
        self.git("switch", "-c", "agent/other-task")
        self.assertEqual(self.verify().returncode, 2)
        self.assertEqual(self.git("branch", "--show-current").stdout.strip(), "agent/other-task")

    def test_tracked_and_untracked_wip_blocks_without_changing_files(self):
        self.assertEqual(self.capture().returncode, 0)
        for name in ["docs/packet.md", "new-work.md"]:
            with self.subTest(name=name):
                path = self.repo / name
                original = path.read_text() if path.exists() else None
                path.write_text("Unfinished work\n")
                self.assertEqual(self.verify().returncode, 2)
                self.assertEqual(path.read_text(), "Unfinished work\n")
                if original is None:
                    path.unlink()
                else:
                    path.write_text(original)

    def test_snapshot_not_overwritten(self):
        self.assertEqual(self.capture().returncode, 0)
        before = self.snapshot.read_bytes()
        self.assertEqual(self.capture().returncode, 2)
        self.assertEqual(self.snapshot.read_bytes(), before)

    def test_wrong_task_or_removed_reference_blocks(self):
        self.assertEqual(self.capture().returncode, 0)
        data = json.loads(self.snapshot.read_text())
        data["canonical_ref"] = "https://github.com/mide-lim/megabrain/pull/89"
        self.snapshot.write_text(json.dumps(data))
        self.assertEqual(self.verify().returncode, 2)
        data["canonical_ref"] = REF
        data["refs"].pop()
        self.snapshot.write_text(json.dumps(data))
        self.assertEqual(self.verify().returncode, 2)

    def test_parent_path_or_sensitive_file_rejected(self):
        for path in ["../private.md", "infra/.env", "/tmp/private.md"]:
            with self.subTest(path=path):
                self.assertEqual(self.capture("--packet", path).returncode, 2)
                self.assertFalse(self.snapshot.exists())

    def test_protected_branch_and_wrong_repository_rejected(self):
        self.git("switch", "-c", "dev")
        self.assertEqual(self.capture().returncode, 2)
        self.git("switch", "agent/test-context")
        self.git("remote", "set-url", "origin", "https://github.com/other/repo.git")
        self.assertEqual(self.capture().returncode, 2)

    def test_symlink_context_rejected(self):
        path = self.repo / "docs/packet.md"
        path.unlink()
        path.symlink_to("CONTEXT.md")
        self.git("add", ".")
        self.git("commit", "-m", "symlink fixture")
        self.assertEqual(self.capture().returncode, 2)

    def test_invalid_json_is_bounded_failure(self):
        self.snapshot.write_text("{bad json and sensitive data}")
        result = self.verify()
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("sensitive data", result.stdout + result.stderr)

    def test_changed_blob_blocks_and_snapshot_cannot_grant_authority(self):
        self.assertEqual(self.capture().returncode, 0)
        data = json.loads(self.snapshot.read_text())
        data["authority"] = "Invented production approval"
        self.snapshot.write_text(json.dumps(data))
        result = self.verify()
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("Invented production approval", result.stdout)
        data["refs"][0]["blob"] = "0" * 40
        self.snapshot.write_text(json.dumps(data))
        self.assertEqual(self.verify().returncode, 2)


if __name__ == "__main__":
    unittest.main()
