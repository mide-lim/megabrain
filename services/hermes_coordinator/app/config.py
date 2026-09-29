from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path

MIN_TIMEOUT_SECONDS = 1
DEFAULT_TIMEOUT_SECONDS = 300
MAX_TIMEOUT_SECONDS = 900
MIN_ITERATIONS = 1
MAX_ITERATIONS = 100
RUNTIME_DIR_MODE = 0o700
PRIVATE_FILE_MODE = 0o600


def ensure_private_runtime_directory(runtime_dir: Path) -> Path:
    runtime_dir = Path(runtime_dir)
    try:
        metadata = os.lstat(runtime_dir)
    except FileNotFoundError:
        runtime_dir.mkdir(mode=RUNTIME_DIR_MODE, parents=False)
        os.chmod(runtime_dir, RUNTIME_DIR_MODE)
        metadata = os.lstat(runtime_dir)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("runtime directory is not a real directory")
    if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) != RUNTIME_DIR_MODE:
        raise ValueError("runtime directory is not private")
    return runtime_dir.resolve(strict=True)


def write_runtime_profile(runtime_dir: Path, *, max_iterations: int) -> Path:
    if not isinstance(max_iterations, int) or isinstance(max_iterations, bool):
        raise ValueError("max_iterations must be an integer")
    if not MIN_ITERATIONS <= max_iterations <= MAX_ITERATIONS:
        raise ValueError("max_iterations is outside conservative bounds")
    runtime_dir = ensure_private_runtime_directory(runtime_dir)
    profile = (
        "agent:\n"
        f"  max_turns: {max_iterations}\n"
        "platform_toolsets:\n"
        "  cli: []\n"
        "auxiliary:\n"
        "  background_review:\n"
        "    enabled: false\n"
    ).encode("utf-8")
    path = runtime_dir / "config.yaml"
    try:
        existing = os.lstat(path)
    except FileNotFoundError:
        existing = None
    if existing is not None:
        if stat.S_ISLNK(existing.st_mode) or not stat.S_ISREG(existing.st_mode):
            raise ValueError("runtime config is unsafe")
        if existing.st_uid != os.geteuid() or stat.S_IMODE(existing.st_mode) != PRIVATE_FILE_MODE:
            raise ValueError("runtime config is not private")

    fd, temp_name = tempfile.mkstemp(prefix=".config.", dir=runtime_dir)
    temp_path = Path(temp_name)
    try:
        os.fchmod(fd, PRIVATE_FILE_MODE)
        os.write(fd, profile)
        os.fsync(fd)
        os.close(fd)
        fd = -1
        os.replace(temp_path, path)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass
    return path
