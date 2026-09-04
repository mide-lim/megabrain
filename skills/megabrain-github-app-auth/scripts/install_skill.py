#!/usr/bin/env python3
"""Install the B4.1 skill from this repository's canonical source only."""

from __future__ import annotations

import argparse
import os
import shutil
import tempfile
from pathlib import Path

SOURCE_DIRECTORY = Path(__file__).resolve().parents[1]
DEFAULT_DESTINATION = Path.home() / ".hermes/skills/megabrain/megabrain-github-app-auth"
ARTIFACTS = {
    Path("SKILL.md"): 0o644,
    Path("scripts/github_app_auth.py"): 0o700,
}
VERSIONED_SOURCE_FILES = set(ARTIFACTS) | {
    Path("scripts/install_skill.py"),
    Path("tests/test_github_app_auth.py"),
}


def source_directory() -> Path:
    """Return canonical source after verifying the intentionally small artifact set."""
    actual_files = {
        path.relative_to(SOURCE_DIRECTORY)
        for path in SOURCE_DIRECTORY.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }
    if actual_files != VERSIONED_SOURCE_FILES:
        raise RuntimeError("canonical_source_invalid")
    return SOURCE_DIRECTORY


def install(destination: Path) -> None:
    """Reconstruct destination atomically from source without reading it first."""
    source = source_directory()
    destination = destination.expanduser()
    destination.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".megabrain-github-app-auth-", dir=destination.parent))
    try:
        for relative_path, mode in ARTIFACTS.items():
            source_path = source / relative_path
            target_path = staging / relative_path
            target_path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            shutil.copyfile(source_path, target_path)
            os.chmod(target_path, mode)
        if destination.exists() or destination.is_symlink():
            if destination.is_symlink() or not destination.is_dir():
                destination.unlink()
            else:
                shutil.rmtree(destination)
        os.replace(staging, destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="Install canonical B4.1 skill source as a derived artifact.")
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    arguments = parser.parse_args()
    try:
        install(arguments.destination)
    except (OSError, RuntimeError):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
