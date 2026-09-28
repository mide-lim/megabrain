#!/usr/bin/env python3
"""Future root-only installer for the dedicated F6 I1-B verifier capability.

This installer is source only. It is not invoked by repository tests and must
not be run on a host without a separate human installation authorization.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from typing import Callable, Iterable


CANONICAL_ORIGIN = "https://github.com/mide-lim/megabrain.git"
CANONICAL_DEV_SHA = "29f314c06351d2f420aa1df54eea90d3d1b7396b"
CANONICAL_DEV_TREE = "49ee708df6ecc790c0e77e011a5d0d6a10f7f994"
VERIFIER_PATH = "infra/postgres/security/f6/008_i1_b_web_applicable_enrichment_read_verify.sql"
VERIFIER_BLOB = "b6651e8e9136bcd11faa4912e39df1c8c0099a22"
LAUNCHER_BLOB = "72a1daed2123d4f35fd7a22fb7a7f1bd08501c6f"
SUDOERS_BLOB = "b3dd41f42445da1ff2f6f9598a223a42a0603faf"

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

SYSTEM_PARENT_DIRECTORIES = frozenset(
    {
        Path("/"),
        Path("/usr"),
        Path("/usr/local"),
        Path("/usr/local/sbin"),
        Path("/usr/local/lib"),
        Path("/etc"),
        Path("/etc/sudoers.d"),
        Path("/var"),
        Path("/var/log"),
    }
)
VERIFIER_SUPPORT_DIRECTORIES = (
    Path("/usr/local/lib/megabrain-hermes-ro"),
    Path("/usr/local/lib/megabrain-hermes-ro/i1-b"),
)
AUDIT_SUPPORT_DIRECTORIES = (Path("/var/log/megabrain-hermes-ro"),)
DEDICATED_SUPPORT_DIRECTORIES = frozenset(
    (*VERIFIER_SUPPORT_DIRECTORIES, *AUDIT_SUPPORT_DIRECTORIES)
)


class InstallError(RuntimeError):
    pass


@dataclass(frozen=True)
class RuntimeFileSpec:
    path: Path
    mode: int
    blob: str | None = None
    empty: bool = False


RUNTIME_LAUNCHER_SPEC = RuntimeFileSpec(RUNTIME_LAUNCHER_PATH, 0o700, LAUNCHER_BLOB)
RUNTIME_VERIFIER_SPEC = RuntimeFileSpec(RUNTIME_VERIFIER_PATH, 0o600, VERIFIER_BLOB)
RUNTIME_SUDOERS_SPEC = RuntimeFileSpec(RUNTIME_SUDOERS_PATH, 0o440, SUDOERS_BLOB)
RUNTIME_AUDIT_LOG_SPEC = RuntimeFileSpec(RUNTIME_AUDIT_LOG_PATH, 0o600, empty=True)


def runtime_file_specs() -> tuple[RuntimeFileSpec, RuntimeFileSpec, RuntimeFileSpec, RuntimeFileSpec]:
    return (
        RUNTIME_LAUNCHER_SPEC,
        RUNTIME_VERIFIER_SPEC,
        RUNTIME_SUDOERS_SPEC,
        RUNTIME_AUDIT_LOG_SPEC,
    )


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
        os.lstat(path)
    except FileNotFoundError:
        return True
    return False


def rollback_paths() -> tuple[Path, Path, Path, Path]:
    return tuple(spec.path for spec in runtime_file_specs())  # type: ignore[return-value]


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


def _parent_chain(destination: Path) -> tuple[Path, ...]:
    parts = destination.parent.parts
    return tuple(Path(*parts[:index]) for index in range(1, len(parts) + 1))


def _require_root_controlled_directory(metadata: os.stat_result, *, exact_mode: int | None = None) -> None:
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise InstallError("runtime parent is not a real directory")
    if metadata.st_uid != 0 or metadata.st_gid != 0:
        raise InstallError("runtime parent is not root-owned")
    mode = stat.S_IMODE(metadata.st_mode)
    if exact_mode is not None and mode != exact_mode:
        raise InstallError("created runtime parent mode mismatch")
    if mode & 0o022:
        raise InstallError("runtime parent is writable outside root")


def _ensure_runtime_parent(
    destination: Path,
    created_directories: list[Path],
    *,
    lstat: Callable[[Path], os.stat_result] = os.lstat,
    mkdir: Callable[[Path, int], None] = os.mkdir,
) -> None:
    if destination not in rollback_paths():
        raise InstallError("runtime destination is outside the dedicated allowlist")
    for parent in _parent_chain(destination):
        if parent in SYSTEM_PARENT_DIRECTORIES:
            try:
                metadata = lstat(parent)
            except FileNotFoundError as exc:
                raise InstallError("required system parent is missing") from exc
            _require_root_controlled_directory(metadata)
            continue
        if parent not in DEDICATED_SUPPORT_DIRECTORIES:
            raise InstallError("runtime parent is outside the dedicated allowlist")
        try:
            metadata = lstat(parent)
        except FileNotFoundError:
            mkdir(parent, 0o700)
            try:
                metadata = lstat(parent)
            except FileNotFoundError as exc:
                raise InstallError("created runtime parent is missing") from exc
            _require_root_controlled_directory(metadata, exact_mode=0o700)
            created_directories.append(parent)
        else:
            _require_root_controlled_directory(metadata)


def _validate_runtime_metadata(metadata: os.stat_result, spec: RuntimeFileSpec) -> None:
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise InstallError("runtime target is not a regular file")
    if metadata.st_uid != 0 or metadata.st_gid != 0:
        raise InstallError("runtime target is not root-owned")
    if stat.S_IMODE(metadata.st_mode) != spec.mode:
        raise InstallError("runtime target mode mismatch")


def _same_file(first: os.stat_result, second: os.stat_result) -> bool:
    return first.st_dev == second.st_dev and first.st_ino == second.st_ino


def _validate_runtime_file(
    spec: RuntimeFileSpec,
    *,
    lstat: Callable[[Path], os.stat_result] = os.lstat,
    opener: Callable[[Path, int], int] = os.open,
    fstat: Callable[[int], os.stat_result] = os.fstat,
    reader: Callable[[int, int], bytes] = os.read,
    closer: Callable[[int], None] = os.close,
) -> os.stat_result:
    before = lstat(spec.path)
    _validate_runtime_metadata(before, spec)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = opener(spec.path, flags)
    except OSError as exc:
        raise InstallError("unable to open runtime target safely") from exc
    try:
        opened = fstat(descriptor)
        _validate_runtime_metadata(opened, spec)
        if not _same_file(before, opened):
            raise InstallError("runtime target changed during validation")
        if spec.empty:
            if opened.st_size != 0 or reader(descriptor, 1):
                raise InstallError("audit log is not pristine and empty")
            return opened
        assert spec.blob is not None
        digest = hashlib.sha1()
        digest.update(f"blob {opened.st_size}\0".encode("ascii"))
        while chunk := reader(descriptor, 65536):
            digest.update(chunk)
        if digest.hexdigest() != spec.blob:
            raise InstallError("runtime target content identity mismatch")
        return opened
    finally:
        closer(descriptor)


def _safe_delete_runtime_file(
    spec: RuntimeFileSpec,
    *,
    lstat: Callable[[Path], os.stat_result] = os.lstat,
    opener: Callable[[Path, int], int] = os.open,
    fstat: Callable[[int], os.stat_result] = os.fstat,
    reader: Callable[[int, int], bytes] = os.read,
    closer: Callable[[int], None] = os.close,
    unlink: Callable[[Path], None] = os.unlink,
) -> None:
    validated = _validate_runtime_file(
        spec,
        lstat=lstat,
        opener=opener,
        fstat=fstat,
        reader=reader,
        closer=closer,
    )
    current = lstat(spec.path)
    _validate_runtime_metadata(current, spec)
    if not _same_file(validated, current):
        raise InstallError("runtime target changed before deletion")
    unlink(spec.path)


def _validate_runtime_files(
    specs: Iterable[RuntimeFileSpec],
    *,
    validate: Callable[[RuntimeFileSpec], os.stat_result] | None = None,
) -> tuple[tuple[RuntimeFileSpec, os.stat_result], ...]:
    """Validate every requested runtime target before any rollback deletion."""
    validator = _validate_runtime_file if validate is None else validate
    return tuple((spec, validator(spec)) for spec in specs)


def _delete_validated_runtime_files(
    validated: Iterable[tuple[RuntimeFileSpec, os.stat_result]],
    *,
    validate: Callable[[RuntimeFileSpec], os.stat_result] | None = None,
    lstat: Callable[[Path], os.stat_result] | None = None,
    unlink: Callable[[Path], None] | None = None,
) -> None:
    """Revalidate each preflighted target immediately before its unlink."""
    validator = _validate_runtime_file if validate is None else validate
    lstat_target = os.lstat if lstat is None else lstat
    unlink_target = os.unlink if unlink is None else unlink
    for spec, preflighted in validated:
        current = validator(spec)
        if not _same_file(preflighted, current):
            raise InstallError("runtime target changed after rollback preflight")
        immediately_before_unlink = lstat_target(spec.path)
        _validate_runtime_metadata(immediately_before_unlink, spec)
        if not _same_file(current, immediately_before_unlink):
            raise InstallError("runtime target changed before deletion")
        unlink_target(spec.path)


def _publish(stage: Path, spec: RuntimeFileSpec, created_directories: list[Path]) -> None:
    if not destination_is_safe(spec.path):
        raise InstallError("refusing replacement of an existing or symlink destination")
    _validate_runtime_file(replace(spec, path=stage))
    _ensure_runtime_parent(spec.path, created_directories)
    os.replace(stage, spec.path)


def _cleanup_published_runtime_files(
    published: Iterable[RuntimeFileSpec],
    *,
    validate: Callable[[RuntimeFileSpec], os.stat_result] | None = None,
    lstat: Callable[[Path], os.stat_result] | None = None,
    unlink: Callable[[Path], None] | None = None,
) -> None:
    try:
        validated = _validate_runtime_files(tuple(published), validate=validate)
        _delete_validated_runtime_files(
            reversed(validated),
            validate=validate,
            lstat=lstat,
            unlink=unlink,
        )
    except (FileNotFoundError, InstallError, OSError) as exc:
        raise InstallError("bounded install cleanup refused") from exc


def _cleanup_created_support_directories(
    created_directories: Iterable[Path],
    *,
    lstat: Callable[[Path], os.stat_result] = os.lstat,
    listdir: Callable[[Path], list[str]] = os.listdir,
    rmdir: Callable[[Path], None] = os.rmdir,
) -> None:
    for directory in reversed(tuple(created_directories)):
        if directory not in DEDICATED_SUPPORT_DIRECTORIES:
            continue
        try:
            metadata = lstat(directory)
            _require_root_controlled_directory(metadata, exact_mode=0o700)
            if listdir(directory):
                continue
            rmdir(directory)
        except (FileNotFoundError, InstallError, OSError):
            continue


def install() -> None:
    """Install only dedicated capability paths after a separate human gate."""
    validate_install_preflight(os.geteuid(), CANONICAL_DEV_SHA, CANONICAL_DEV_TREE, VERIFIER_BLOB)
    _require_root_owned_source(SOURCE_DIRECTORY)
    for spec in runtime_file_specs():
        if not destination_is_safe(spec.path):
            raise InstallError("dedicated runtime destination already exists or is unsafe")

    with tempfile.TemporaryDirectory(prefix="i1-b-authority-verify-", dir="/var/tmp") as temporary:
        staging_root = Path(temporary)
        os.chmod(staging_root, 0o700)
        verifier_bytes = _verified_verifier_bytes(staging_root)
        verifier_stage = staging_root / "runtime" / RUNTIME_VERIFIER_PATH.name
        launcher_stage = staging_root / "runtime" / RUNTIME_LAUNCHER_PATH.name
        sudoers_stage = staging_root / "runtime" / RUNTIME_SUDOERS_PATH.name
        audit_stage = staging_root / "runtime" / RUNTIME_AUDIT_LOG_PATH.name
        _write_stage(verifier_stage, verifier_bytes, RUNTIME_VERIFIER_SPEC.mode)
        _write_stage(launcher_stage, SOURCE_LAUNCHER.read_bytes(), RUNTIME_LAUNCHER_SPEC.mode)
        _write_stage(sudoers_stage, SOURCE_SUDOERS.read_bytes(), RUNTIME_SUDOERS_SPEC.mode)
        _write_stage(audit_stage, b"", RUNTIME_AUDIT_LOG_SPEC.mode)
        _validate_sudoers(sudoers_stage)
        staged = (
            (verifier_stage, RUNTIME_VERIFIER_SPEC),
            (launcher_stage, RUNTIME_LAUNCHER_SPEC),
            (sudoers_stage, RUNTIME_SUDOERS_SPEC),
            (audit_stage, RUNTIME_AUDIT_LOG_SPEC),
        )
        published: list[RuntimeFileSpec] = []
        created_directories: list[Path] = []
        try:
            for stage, spec in staged:
                _publish(stage, spec, created_directories)
                published.append(spec)
            _run(["/usr/sbin/visudo", "-cf", str(RUNTIME_SUDOERS_PATH)])
        except Exception as install_failure:
            try:
                _cleanup_published_runtime_files(published)
                _cleanup_created_support_directories(created_directories)
            except InstallError as cleanup_failure:
                raise InstallError("bounded install cleanup refused") from cleanup_failure
            raise install_failure


def rollback() -> None:
    """Remove only pristine dedicated capability files; leave support directories in place."""
    validate_install_preflight(os.geteuid(), CANONICAL_DEV_SHA, CANONICAL_DEV_TREE, VERIFIER_BLOB)
    try:
        validated = _validate_runtime_files(runtime_file_specs())
        _delete_validated_runtime_files(validated)
    except (FileNotFoundError, InstallError, OSError) as exc:
        raise InstallError("public rollback refused") from exc


def main(argv: Iterable[str] | None = None) -> int:
    supplied = list(sys.argv[1:] if argv is None else argv)
    if supplied:
        raise SystemExit("installer accepts no arguments")
    install()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
