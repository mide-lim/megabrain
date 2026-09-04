#!/usr/bin/env python3
"""Install the canonical B4.2 lifecycle capability as a derived artifact."""
from __future__ import annotations

import argparse
import os
import shutil
import tempfile
from pathlib import Path

SOURCE_DIRECTORY = Path(__file__).resolve().parents[1]
DEFAULT_DESTINATION = Path.home() / ".hermes/skills/megabrain/megabrain-autonomous-pr-lifecycle"
ARTIFACTS = {
    Path("SKILL.md"): 0o644,
    Path("scripts/autonomous_pr_lifecycle.py"): 0o700,
}
VERSIONED_SOURCE_FILES = set(ARTIFACTS) | {Path("scripts/install_skill.py"), Path("tests/test_lifecycle.py")}


def source_directory() -> Path:
    files = {path.relative_to(SOURCE_DIRECTORY) for path in SOURCE_DIRECTORY.rglob("*") if path.is_file() and "__pycache__" not in path.parts}
    if files != VERSIONED_SOURCE_FILES:
        raise RuntimeError("canonical_source_invalid")
    return SOURCE_DIRECTORY


def install(destination: Path | None = None, *, test_only: bool = False) -> None:
    source = source_directory()
    destination = (DEFAULT_DESTINATION if destination is None else destination.expanduser())
    if destination != DEFAULT_DESTINATION and not test_only:
        raise RuntimeError("destination_rejected")
    ancestor = destination.parent
    while ancestor != ancestor.parent:
        if ancestor.exists() and ancestor.is_symlink():
            raise RuntimeError("destination_rejected")
        ancestor = ancestor.parent
    if destination.is_symlink():
        raise RuntimeError("destination_rejected")
    destination.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".megabrain-b4-2-", dir=destination.parent))
    try:
        for relative, mode in ARTIFACTS.items():
            target = staging / relative
            target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            shutil.copyfile(source / relative, target)
            os.chmod(target, mode)
        if destination.exists():
            if not destination.is_dir():
                destination.unlink()
            else:
                shutil.rmtree(destination)
        os.replace(staging, destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="Install canonical B4.2 capability source as a derived artifact.")
    parser.parse_args()
    try:
        install()
    except (OSError, RuntimeError):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
