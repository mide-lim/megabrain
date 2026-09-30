#!/usr/bin/env python3
"""Root-only installer for the reviewed existing-branch adapter source."""
from __future__ import annotations

import json
import os
import pwd
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

SOURCE_DIRECTORY = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = SOURCE_DIRECTORY.parents[1]
DESTINATION = Path("/home/megabrain-hermes/.hermes/skills/megabrain/megabrain-existing-branch-fast-forward")
SOURCE_IDENTITY_PATH = Path(
    "/etc/megabrain/hermes-skill-source-identities/megabrain-existing-branch-fast-forward.json"
)
GIT_BINARY = "/usr/bin/git"
REPOSITORY = "mide-lim/megabrain"
ORIGIN = "https://github.com/mide-lim/megabrain.git"
ARTIFACTS = {
    Path("SKILL.md"): 0o640,
    Path("scripts/authenticated_existing_branch_fast_forward.py"): 0o750,
}
VERSIONED_SOURCE_FILES = frozenset(set(ARTIFACTS) | {
    Path("scripts/install_skill.py"),
    Path("tests/test_authenticated_existing_branch_fast_forward.py"),
})
SOURCE_IDENTITY_FIELDS = frozenset({"version", "repository", "commit", "tree", "blobs"})


class InstallRejected(RuntimeError):
    pass


def parse_strict_json(text: str) -> dict[str, Any]:
    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_key")
            result[key] = value
        return result
    try:
        value = json.loads(text, object_pairs_hook=no_duplicates)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise InstallRejected("source_identity_schema_rejected") from exc
    if not isinstance(value, dict):
        raise InstallRejected("source_identity_schema_rejected")
    return value


def _validate_root_owned_path(path: Path, *, final_file: bool) -> None:
    if not path.is_absolute() or path.parts[0] != "/":
        raise InstallRejected("source_identity_trust_rejected")
    current = Path("/")
    for index, part in enumerate(path.parts):
        if index == 0:
            candidate = current
        else:
            current = current / part
            candidate = current
        final = candidate == path
        try:
            info = os.lstat(candidate)
        except OSError as exc:
            raise InstallRejected("source_identity_missing") from exc
        valid_type = stat.S_ISREG(info.st_mode) if final and final_file else stat.S_ISDIR(info.st_mode)
        if (stat.S_ISLNK(info.st_mode) or not valid_type or info.st_uid != 0
                or stat.S_IMODE(info.st_mode) & 0o022
                or final and final_file and stat.S_IMODE(info.st_mode) != 0o600):
            raise InstallRejected("source_identity_trust_rejected")


def _source_identity() -> dict[str, Any]:
    _validate_root_owned_path(SOURCE_IDENTITY_PATH, final_file=True)
    try:
        value = parse_strict_json(SOURCE_IDENTITY_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise InstallRejected("source_identity_missing") from exc
    if set(value) != SOURCE_IDENTITY_FIELDS or type(value.get("version")) is not int or value["version"] != 1:
        raise InstallRejected("source_identity_schema_rejected")
    if value.get("repository") != REPOSITORY or not isinstance(value.get("commit"), str) or not isinstance(value.get("tree"), str):
        raise InstallRejected("source_identity_schema_rejected")
    blobs = value.get("blobs")
    expected_blob_keys = {path.as_posix() for path in VERSIONED_SOURCE_FILES}
    if not isinstance(blobs, dict) or set(blobs) != expected_blob_keys or not all(isinstance(item, str) for item in blobs.values()):
        raise InstallRejected("source_identity_schema_rejected")
    return value


def _validate_git_binary() -> None:
    try:
        info = os.lstat(GIT_BINARY)
    except OSError as exc:
        raise InstallRejected("git_binary_rejected") from exc
    if (stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_uid != 0
            or stat.S_IMODE(info.st_mode) & 0o022 or not info.st_mode & stat.S_IXUSR):
        raise InstallRejected("git_binary_rejected")


def _git(arguments: list[str]) -> str:
    _validate_git_binary()
    try:
        completed = subprocess.run(
            [GIT_BINARY, *arguments], cwd=REPOSITORY_ROOT, check=False, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, timeout=15,
            env={"HOME": "/nonexistent", "PATH": "/usr/bin:/bin", "GIT_TERMINAL_PROMPT": "0",
                 "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_NO_REPLACE_OBJECTS": "1"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise InstallRejected("source_identity_git_rejected") from exc
    if completed.returncode != 0:
        raise InstallRejected("source_identity_git_rejected")
    return completed.stdout.strip()


def source_directory() -> Path:
    files = {
        item.relative_to(SOURCE_DIRECTORY)
        for item in SOURCE_DIRECTORY.rglob("*")
        if item.is_file() and "__pycache__" not in item.parts
    }
    if files != VERSIONED_SOURCE_FILES:
        raise InstallRejected("canonical_source_invalid")
    if any(item.is_symlink() for item in SOURCE_DIRECTORY.rglob("*")):
        raise InstallRejected("canonical_source_invalid")
    return SOURCE_DIRECTORY


def validate_reviewed_source() -> None:
    source_directory()
    identity = _source_identity()
    if _git(["remote", "get-url", "origin"]) != ORIGIN:
        raise InstallRejected("source_identity_origin_rejected")
    if _git(["status", "--porcelain=v1", "--untracked-files=all"]):
        raise InstallRejected("source_identity_dirty")
    if _git(["rev-parse", "HEAD"]) != identity["commit"] or _git(["rev-parse", "HEAD^{tree}"]) != identity["tree"]:
        raise InstallRejected("source_identity_rejected")
    for relative, expected_blob in identity["blobs"].items():
        pathspec = f"HEAD:skills/megabrain-existing-branch-fast-forward/{relative}"
        if _git(["rev-parse", pathspec]) != expected_blob:
            raise InstallRejected("source_identity_rejected")


def _validate_destination_parent(destination: Path) -> None:
    if destination != DESTINATION or destination.is_symlink() or destination.exists():
        raise InstallRejected("destination_rejected")
    current = Path("/")
    for part in destination.parent.parts[1:]:
        current = current / part
        try:
            info = os.lstat(current)
        except OSError as exc:
            raise InstallRejected("destination_rejected") from exc
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise InstallRejected("destination_rejected")


def install() -> None:
    if os.geteuid() != 0:
        raise InstallRejected("root_required")
    validate_reviewed_source()
    _validate_destination_parent(DESTINATION)
    group_id = pwd.getpwnam("megabrain-hermes").pw_gid
    created = False
    try:
        DESTINATION.mkdir(mode=0o750)
        created = True
        os.chown(DESTINATION, 0, group_id)
        os.chmod(DESTINATION, 0o750)
        for relative, mode in ARTIFACTS.items():
            target = DESTINATION / relative
            if target.parent != DESTINATION:
                target.parent.mkdir(mode=0o750, parents=True, exist_ok=False)
                os.chown(target.parent, 0, group_id)
                os.chmod(target.parent, 0o750)
            shutil.copyfile(SOURCE_DIRECTORY / relative, target)
            os.chown(target, 0, group_id)
            os.chmod(target, mode)
    except Exception:
        if created:
            shutil.rmtree(DESTINATION, ignore_errors=True)
        raise


def main() -> int:
    if len(sys.argv) != 1:
        return 1
    try:
        install()
    except (InstallRejected, OSError, KeyError):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
