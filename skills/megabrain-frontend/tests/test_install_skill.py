from __future__ import annotations

import hashlib
import importlib.util
import os
import socket
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SKILL_DIRECTORY = Path(__file__).resolve().parents[1]
INSTALLER_PATH = SKILL_DIRECTORY / "scripts" / "install_skill.py"


def load_installer():
    specification = importlib.util.spec_from_file_location("megabrain_frontend_installer", INSTALLER_PATH)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


INSTALLER = load_installer()


class FrontendSkillInstallerTests(unittest.TestCase):
    def source_files(self) -> set[Path]:
        return {
            path.relative_to(SKILL_DIRECTORY)
            for path in SKILL_DIRECTORY.rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        }

    def installed_files(self, destination: Path) -> set[Path]:
        return {path.relative_to(destination) for path in destination.rglob("*") if path.is_file()}

    def run_installer(self, home: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        environment = dict(os.environ, HERMES_HOME=str(home))
        return subprocess.run(
            [sys.executable, str(INSTALLER_PATH), *arguments],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )

    def assert_derived_artifacts(self, destination: Path) -> None:
        self.assertEqual(self.installed_files(destination), set(INSTALLER.ARTIFACTS))
        for relative, expected_mode in INSTALLER.ARTIFACTS.items():
            source = SKILL_DIRECTORY / relative
            derived = destination / relative
            self.assertEqual(source.read_bytes(), derived.read_bytes(), relative)
            self.assertEqual(stat.S_IMODE(derived.stat().st_mode), expected_mode, relative)
            self.assertFalse(derived.is_symlink(), relative)
        self.assertFalse(any(path.name == ".env" or path.suffix in {".pem", ".key"} for path in self.installed_files(destination)))
        self.assertFalse(any(path.is_symlink() for path in destination.rglob("*")))

    def test_exact_canonical_and_derived_artifact_sets(self) -> None:
        self.assertEqual(self.source_files(), INSTALLER.VERSIONED_SOURCE_FILES)
        self.assertEqual(
            set(INSTALLER.ARTIFACTS),
            {
                Path("SKILL.md"),
                Path("references/SOURCES.md"),
                Path("references/frontend-design.md"),
                Path("references/react-best-practices.md"),
                Path("references/composition-patterns.md"),
                Path("references/web-interface-guidelines.md"),
                Path("references/licenses/anthropic-frontend-design-Apache-2.0.txt"),
                Path("references/licenses/vercel-web-interface-guidelines-MIT.txt"),
            },
        )

    def test_clean_install_has_exact_destination_and_parity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_root:
            home = Path(temporary_root) / "hermes-home"
            expected_destination = home / "skills/megabrain/megabrain-frontend"
            result = self.run_installer(home)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(expected_destination.is_dir())
            self.assert_derived_artifacts(expected_destination)

    def test_reinstall_replaces_stale_content_without_using_it_as_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_root:
            home = Path(temporary_root) / "hermes-home"
            destination = home / "skills/megabrain/megabrain-frontend"
            first = self.run_installer(home)
            self.assertEqual(first.returncode, 0, first.stderr)
            stale = destination / "untrusted-stale.txt"
            stale.write_text("not canonical", encoding="utf-8")
            second = self.run_installer(home)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertFalse(stale.exists())
            self.assert_derived_artifacts(destination)

    def test_destination_is_fixed_and_rejects_cli_override_and_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_root:
            home = Path(temporary_root) / "hermes-home"
            self.assertEqual(
                INSTALLER.destination_for_home(home),
                home / "skills/megabrain/megabrain-frontend",
            )
            rejected_argument = self.run_installer(home, "--destination", str(Path(temporary_root) / "elsewhere"))
            self.assertNotEqual(rejected_argument.returncode, 0)
            destination = home / "skills/megabrain/megabrain-frontend"
            destination.parent.mkdir(parents=True)
            target = Path(temporary_root) / "untrusted-target"
            target.mkdir()
            destination.symlink_to(target, target_is_directory=True)
            rejected_symlink = self.run_installer(home)
            self.assertEqual(rejected_symlink.returncode, 1)
            self.assertTrue(destination.is_symlink())

    def test_installer_performs_no_network_request(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_root, mock.patch.dict(
            os.environ, {"HERMES_HOME": str(Path(temporary_root) / "hermes-home")}, clear=False
        ), mock.patch.object(socket, "socket", side_effect=AssertionError("network not allowed")):
            destination = INSTALLER.install()
            self.assert_derived_artifacts(destination)

    def test_installer_does_not_read_existing_installation_as_canonical_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_root, mock.patch.dict(
            os.environ, {"HERMES_HOME": str(Path(temporary_root) / "hermes-home")}, clear=False
        ):
            destination = INSTALLER.destination_for_home(INSTALLER.hermes_home())
            destination.mkdir(parents=True)
            stale = destination / "untrusted-stale.txt"
            stale.write_text("not canonical", encoding="utf-8")
            original_read_bytes = Path.read_bytes

            def reject_existing_install_read(path: Path) -> bytes:
                if path == stale:
                    raise AssertionError("existing installation was read")
                return original_read_bytes(path)

            with mock.patch.object(Path, "read_bytes", reject_existing_install_read):
                installed = INSTALLER.install()
            self.assertEqual(installed, destination)
            self.assertFalse(stale.exists())
            self.assert_derived_artifacts(destination)

    def test_source_and_destination_reject_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_root:
            temporary_source = Path(temporary_root) / "source"
            temporary_source.mkdir()
            (temporary_source / "link").symlink_to(SKILL_DIRECTORY / "SKILL.md")
            self.assertRaisesRegex(RuntimeError, "source_symlink_rejected", INSTALLER._source_files, temporary_source)

    def test_manifest_attribution_and_license_files_are_present(self) -> None:
        manifest = (SKILL_DIRECTORY / "references/SOURCES.md").read_text(encoding="utf-8")
        for commit in (
            "41bbe19d1a1a7eaab5e7bb9050a417e5c6cffc8f",
            "063bee94c3f4df8453406c830b0a7df0f2860278",
            "e3d624baaf29dc1fc645aff3e38f03e564d2d6b1",
        ):
            self.assertIn(commit, manifest)
        self.assertIn("UPDATES ARE MANUAL", manifest.upper())
        self.assertIn("Apache License", (SKILL_DIRECTORY / "references/licenses/anthropic-frontend-design-Apache-2.0.txt").read_text(encoding="utf-8"))
        self.assertIn("MIT License", (SKILL_DIRECTORY / "references/licenses/vercel-web-interface-guidelines-MIT.txt").read_text(encoding="utf-8"))
        self.assertIn("Anthropic", (SKILL_DIRECTORY / "references/frontend-design.md").read_text(encoding="utf-8"))
        self.assertIn("Vercel", (SKILL_DIRECTORY / "references/react-best-practices.md").read_text(encoding="utf-8"))
        self.assertIn("Vercel", (SKILL_DIRECTORY / "references/composition-patterns.md").read_text(encoding="utf-8"))
        self.assertIn("Vercel Labs", (SKILL_DIRECTORY / "references/web-interface-guidelines.md").read_text(encoding="utf-8"))

    def test_installer_has_no_network_or_process_interfaces(self) -> None:
        source = INSTALLER_PATH.read_text(encoding="utf-8")
        for prohibited in ("argparse", "socket", "urllib", "http.client", "requests", "subprocess", "os.system"):
            self.assertNotIn(prohibited, source)
        self.assertEqual(hashlib.sha256((SKILL_DIRECTORY / "SKILL.md").read_bytes()).digest_size, 32)


if __name__ == "__main__":
    unittest.main()
