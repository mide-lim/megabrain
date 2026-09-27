#!/usr/bin/env python3
"""Future root-only installer for the dedicated F6 I1-B verifier capability.

This installer is source only. It is not invoked by repository tests and must
not be run on a host without a separate human installation authorization.
"""

from __future__ import annotations

import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from typing import Iterable


CANONICAL_ORIGIN = "https://github.com/mide-lim/megabrain.git"
CANONICAL_DEV_SHA = "29f314c06351d2f420aa1df54eea90d3d1b7396b"
CANONICAL_DEV_TREE = "49ee708df6ecc790c0e77e011a5d0d6a10f7f994"
VERIFIER_PATH = "infra/postgres/security/f6/008_i1_b_web_applicable_enrichment_read_verify.sql"
VERIFIER_BLOB = "b6651e8e9136bcd11faa4912e39df1c8c0099a22"

RUNTIME_LAUNCHER_PATH = Path("/usr/local/sbin/megabrain-hermes-i1-b-authority-verify")
RUNTIME_VERIFIER_PATH = Path(
    "/usr/local/lib/megabrain-hermes-ro/i1-b/"
    "008_i1_b_web_applicable_enrichment_read_verify.sql"
)
RUNTIME_SUDOERS_PATH = Path("/etc/sudoers.d/megabrain-hermes-i1-b-authority-verify")
RUNTIME_AUDIT_LOG_PATH = Path("/var/log/megabrain-hermes-ro/i1-b-authority-verify.log")

SOURCE_DIRECTORY = Path(__file__).resolve().parent
SOURCE_LAUNCHER = SOURCE_DIRECTORY / "i1_b_authority_verify.py"
SOURCE_SUDOERS = SOURCE_DIRECTORY / "sudoers.d/megabrain-hermes-i1-b-authority-verify"


class InstallError(RuntimeError):
    pass


def validate_install_preflight(euid: int, dev_sha: str, dev_tree: str, verifier_blob: str) -> None:
    if euid != 0:
        raise PermissionError("installer requires root")
    if dev_sha != CANONICAL_DEV_SHA:
        raise ValueError("canonical dev SHA mismatch")
    if dev_tree != CANONICAL_DEV_TREE:
        raise ValueError("canonical dev tree mismatch")
    if verifier_blob != VERIFIER_BLOB:
        raise ValueError("canonical verifier blob mismatch")


def destination_is_safe(path: Path) -> bool:
    try:
        metadata = os.lstat(path)
    except FileNotFoundError:
        return True
    return False


def rollback_paths() -> tuple[Path, Path, Path, Path]:
    return (
        RUNTIME_LAUNCHER_PATH,
        RUNTIME_VERIFIER_PATH,
        RUNTIME_SUDOERS_PATH,
        RUNTIME_AUDIT_LOG_PATH,
    )


def _require_root_owned_source(path: Path) -> None:
    metadata = path.stat()
    if metadata.st_uid != 0 or metadata.st_gid != 0:
        raise InstallError("installer source directory must be root-owned")
    if stat.S_IMODE(metadata.st_mode) & 0o022:
        raise InstallError("installer source directory must not be writable by group or other")
    for source in (SOURCE_LAUNCHER, SOURCE_SUDOERS):
        source_metadata = source.stat()
        if not stat.S_ISREG(source_metadata.st_mode) or source_metadata.st_uid != 0 or source_metadata.st_gid != 0:
            raise InstallError("installer source file is not a root-owned regular file")
        if stat.S_IMODE(source_metadata.st_mode) & 0o022:
            raise InstallError("installer source file is writable outside root")


def _run(command: list[str], *, cwd: Path | None = None, input_bytes: bytes | None = None) -> bytes:
    completed = subprocess.run(
        command,
        cwd=cwd,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
        env={"HOME": "/root", "LANG": "C", "LC_ALL": "C", "PATH": "/usr/sbin:/usr/bin:/sbin:/bin"},
        timeout=60,
    )
    if completed.returncode != 0:
        raise InstallError("fixed installer command failed")
    return completed.stdout


def _verified_verifier_bytes(staging_root: Path) -> bytes:
    clone = staging_root / "canonical"
    _run(["/usr/bin/git", "clone", "--no-checkout", "--", CANONICAL_ORIGIN, str(clone)])
    _run(["/usr/bin/git", "fetch", "--no-tags", "origin", CANONICAL_DEV_SHA], cwd=clone)
    origin = _run(["/usr/bin/git", "remote", "get-url", "origin"], cwd=clone).decode("ascii").strip()
    if origin != CANONICAL_ORIGIN:
        raise InstallError("canonical origin mismatch")
    tree = _run(["/usr/bin/git", "rev-parse", f"{CANONICAL_DEV_SHA}^{{tree}}"], cwd=clone).decode("ascii").strip()
    blob = _run(["/usr/bin/git", "rev-parse", f"{CANONICAL_DEV_SHA}:{VERIFIER_PATH}"], cwd=clone).decode("ascii").strip()
    validate_install_preflight(0, CANONICAL_DEV_SHA, tree, blob)
    return _run(["/usr/bin/git", "cat-file", "blob", VERIFIER_BLOB], cwd=clone)


def _write_stage(path: Path, contents: bytes, mode: int) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    with path.open("xb") as handle:
        handle.write(contents)
    os.chmod(path, mode)
    metadata = path.stat()
    if metadata.st_uid != 0 or metadata.st_gid != 0 or stat.S_IMODE(metadata.st_mode) != mode:
        raise InstallError("staged runtime file metadata mismatch")


def _validate_sudoers(staged_sudoers: Path) -> None:
    _run(["/usr/sbin/visudo", "-cf", str(staged_sudoers)])


def _ensure_safe_root_directory(path: Path) -> None:
    current = Path(path.root)
    for part in path.parts[1:]:
        current /= part
        try:
            metadata = os.lstat(current)
        except FileNotFoundError:
            current.mkdir(mode=0o700)
            metadata = os.lstat(current)
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise InstallError("runtime parent is not a real directory")
        if metadata.st_uid != 0 or metadata.st_gid != 0:
            raise InstallError("runtime parent is not root-owned")
        if stat.S_IMODE(metadata.st_mode) & 0o022:
            raise InstallError("runtime parent is writable outside root")


def _publish(stage: Path, destination: Path) -> None:
    if not destination_is_safe(destination):
        raise InstallError("refusing replacement of an existing or symlink destination")
    _ensure_safe_root_directory(destination.parent)
    os.replace(stage, destination)


def install() -> None:
    """Install only dedicated capability paths after a separate human gate."""
    validate_install_preflight(os.geteuid(), CANONICAL_DEV_SHA, CANONICAL_DEV_TREE, VERIFIER_BLOB)
    _require_root_owned_source(SOURCE_DIRECTORY)
    for destination in rollback_paths():
        if not destination_is_safe(destination):
            raise InstallError("dedicated runtime destination already exists or is unsafe")

    with tempfile.TemporaryDirectory(prefix="i1-b-authority-verify-", dir="/var/tmp") as temporary:
        staging_root = Path(temporary)
        os.chmod(staging_root, 0o700)
        verifier_bytes = _verified_verifier_bytes(staging_root)
        verifier_stage = staging_root / "runtime" / RUNTIME_VERIFIER_PATH.name
        launcher_stage = staging_root / "runtime" / RUNTIME_LAUNCHER_PATH.name
        sudoers_stage = staging_root / "runtime" / RUNTIME_SUDOERS_PATH.name
        audit_stage = staging_root / "runtime" / RUNTIME_AUDIT_LOG_PATH.name
        _write_stage(verifier_stage, verifier_bytes, 0o600)
        _write_stage(launcher_stage, SOURCE_LAUNCHER.read_bytes(), 0o700)
        _write_stage(sudoers_stage, SOURCE_SUDOERS.read_bytes(), 0o440)
        _write_stage(audit_stage, b"", 0o600)
        _validate_sudoers(sudoers_stage)
        published: list[Path] = []
        try:
            _publish(verifier_stage, RUNTIME_VERIFIER_PATH)
            published.append(RUNTIME_VERIFIER_PATH)
            _publish(launcher_stage, RUNTIME_LAUNCHER_PATH)
            published.append(RUNTIME_LAUNCHER_PATH)
            _publish(sudoers_stage, RUNTIME_SUDOERS_PATH)
            published.append(RUNTIME_SUDOERS_PATH)
            _publish(audit_stage, RUNTIME_AUDIT_LOG_PATH)
            published.append(RUNTIME_AUDIT_LOG_PATH)
            _run(["/usr/sbin/visudo", "-cf", str(RUNTIME_SUDOERS_PATH)])
        except Exception:
            for published_path in reversed(published):
                metadata = os.lstat(published_path)
                if stat.S_ISLNK(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_gid != 0:
                    raise InstallError("bounded rollback target became unsafe")
                published_path.unlink()
            raise


def rollback() -> None:
    """Remove only dedicated capability paths; never touch existing A1 paths."""
    validate_install_preflight(os.geteuid(), CANONICAL_DEV_SHA, CANONICAL_DEV_TREE, VERIFIER_BLOB)
    for path in rollback_paths():
        try:
            metadata = os.lstat(path)
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadata.st_mode):
            raise InstallError("refusing rollback of symlink")
        if metadata.st_uid != 0 or metadata.st_gid != 0:
            raise InstallError("refusing rollback of non-root-owned path")
        if path.is_dir():
            raise InstallError("rollback path is unexpectedly a directory")
        path.unlink()


def main(argv: Iterable[str] | None = None) -> int:
    supplied = list(sys.argv[1:] if argv is None else argv)
    if supplied:
        raise SystemExit("installer accepts no arguments")
    install()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
