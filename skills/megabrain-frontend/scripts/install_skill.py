#!/usr/bin/env python3
"""Install the canonical MegaBrain frontend guidance as a derived local skill."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

SOURCE_DIRECTORY = Path(__file__).resolve().parents[1]
DESTINATION_RELATIVE = Path("skills/megabrain/megabrain-frontend")
ARTIFACTS = {
    Path("SKILL.md"): 0o644,
    Path("references/SOURCES.md"): 0o644,
    Path("references/frontend-design.md"): 0o644,
    Path("references/react-best-practices.md"): 0o644,
    Path("references/composition-patterns.md"): 0o644,
    Path("references/web-interface-guidelines.md"): 0o644,
    Path("references/licenses/anthropic-frontend-design-Apache-2.0.txt"): 0o644,
    Path("references/licenses/vercel-web-interface-guidelines-MIT.txt"): 0o644,
}
VERSIONED_SOURCE_FILES = set(ARTIFACTS) | {
    Path("scripts/install_skill.py"),
    Path("tests/test_install_skill.py"),
}


def hermes_home(environment: dict[str, str] | None = None) -> Path:
    """Resolve the active Hermes home without accepting a destination argument."""
    values = os.environ if environment is None else environment
    configured = values.get("HERMES_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".hermes"


def destination_for_home(home: Path) -> Path:
    """Return the sole derived destination for this skill."""
    return home / DESTINATION_RELATIVE


def _source_files(source: Path) -> set[Path]:
    files: set[Path] = set()
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        if "__pycache__" in relative.parts:
            continue
        if path.is_symlink():
            raise RuntimeError("source_symlink_rejected")
        if path.is_file():
            files.add(relative)
    return files


def source_directory() -> Path:
    """Validate the canonical repository source and return no derived input."""
    if not SOURCE_DIRECTORY.is_dir() or SOURCE_DIRECTORY.is_symlink():
        raise RuntimeError("canonical_source_invalid")
    if _source_files(SOURCE_DIRECTORY) != VERSIONED_SOURCE_FILES:
        raise RuntimeError("canonical_source_invalid")
    for relative in ARTIFACTS:
        source = SOURCE_DIRECTORY / relative
        if source.is_symlink() or not source.is_file():
            raise RuntimeError("canonical_source_invalid")
    return SOURCE_DIRECTORY


def _assert_safe_destination(destination: Path) -> None:
    if destination != destination_for_home(hermes_home()):
        raise RuntimeError("destination_rejected")
    for ancestor in (destination.parent, *destination.parent.parents):
        if ancestor.exists() and ancestor.is_symlink():
            raise RuntimeError("destination_rejected")
    if destination.is_symlink():
        raise RuntimeError("destination_rejected")


def _replace_atomically(staging: Path, destination: Path) -> None:
    """Replace the destination without using its content as canonical input."""
    if not destination.exists():
        os.replace(staging, destination)
        return

    backup = Path(tempfile.mkdtemp(prefix=".megabrain-frontend-old-", dir=destination.parent))
    backup.rmdir()
    os.replace(destination, backup)
    try:
        os.replace(staging, destination)
    except Exception:
        os.replace(backup, destination)
        raise
    shutil.rmtree(backup)


def install() -> Path:
    """Stage and install the exact approved artifact set with no network access."""
    source = source_directory()
    destination = destination_for_home(hermes_home())
    _assert_safe_destination(destination)
    destination.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".megabrain-frontend-stage-", dir=destination.parent))
    try:
        os.chmod(staging, 0o755)
        for relative, mode in ARTIFACTS.items():
            source_path = source / relative
            target_path = staging / relative
            target_path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            os.chmod(target_path.parent, 0o755)
            shutil.copyfile(source_path, target_path, follow_symlinks=False)
            os.chmod(target_path, mode)
        _replace_atomically(staging, destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return destination


def main() -> int:
    if len(sys.argv) != 1:
        return 2
    try:
        install()
    except (OSError, RuntimeError):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
