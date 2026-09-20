#!/usr/bin/env python3
"""Fixed, inert runtime configuration for the MegaBrain GitHub App."""
from __future__ import annotations

import grp
import os
import pwd
import stat
from dataclasses import dataclass
from pathlib import Path

CONFIG_PATH = Path("/home/megabrain-hermes/.config/megabrain-hermes/github-app/runtime.conf")
APPROVED_KEY_PATH = Path("/home/megabrain-hermes/.config/megabrain-hermes/github-app/private-key.pem")
EXPECTED_USER = "megabrain-hermes"
EXPECTED_GROUP = "megabrain-hermes"
MAX_CONFIG_BYTES = 4096
ALLOWED_KEYS = frozenset({"github_app_id", "github_app_installation_id", "private_key_path"})


class RuntimeConfigError(Exception):
    """A non-sensitive fail-closed runtime configuration result."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class RuntimeConfig:
    app_id: str
    installation_id: str
    key_path: str


def _identity() -> tuple[int, int]:
    try:
        user = pwd.getpwnam(EXPECTED_USER)
        group = grp.getgrnam(EXPECTED_GROUP)
    except KeyError as exc:
        raise RuntimeConfigError("runtime_identity_rejected") from exc
    if user.pw_gid != group.gr_gid:
        raise RuntimeConfigError("runtime_identity_rejected")
    return user.pw_uid, group.gr_gid


def _same_identity(first: os.stat_result, second: os.stat_result) -> bool:
    return first.st_dev == second.st_dev and first.st_ino == second.st_ino


def _reject_unsafe_directory(path: Path, uid: int, gid: int, *, root_owned: bool) -> None:
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise RuntimeConfigError("runtime_config_parent_rejected") from exc
    expected_uid = 0 if root_owned else uid
    expected_gid = 0 if root_owned else gid
    if (
        stat.S_ISLNK(info.st_mode)
        or not stat.S_ISDIR(info.st_mode)
        or info.st_uid != expected_uid
        or info.st_gid != expected_gid
        or stat.S_IMODE(info.st_mode) & 0o022
    ):
        raise RuntimeConfigError("runtime_config_parent_rejected")


def _validate_parent_chain(path: Path, uid: int, gid: int) -> None:
    if path.parent not in {CONFIG_PATH.parent, APPROVED_KEY_PATH.parent}:
        raise RuntimeConfigError("runtime_config_parent_rejected")
    components = (
        (Path("/"), True),
        (Path("/home"), True),
        (Path("/home/megabrain-hermes"), False),
        (Path("/home/megabrain-hermes/.config"), False),
        (Path("/home/megabrain-hermes/.config/megabrain-hermes"), False),
        (Path("/home/megabrain-hermes/.config/megabrain-hermes/github-app"), False),
    )
    for component, root_owned in components:
        _reject_unsafe_directory(component, uid, gid, root_owned=root_owned)


def _valid_file_mode(mode: int) -> bool:
    return stat.S_IMODE(mode) in {0o400, 0o600}


def _read_config(uid: int, gid: int) -> bytes:
    _validate_parent_chain(CONFIG_PATH, uid, gid)
    try:
        before = os.lstat(CONFIG_PATH)
    except FileNotFoundError as exc:
        raise RuntimeConfigError("runtime_config_missing") from exc
    except OSError as exc:
        raise RuntimeConfigError("runtime_config_open_rejected") from exc
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise RuntimeConfigError("runtime_config_type_rejected")
    if before.st_uid != uid:
        raise RuntimeConfigError("runtime_config_owner_rejected")
    if before.st_gid != gid:
        raise RuntimeConfigError("runtime_config_group_rejected")
    if not _valid_file_mode(before.st_mode):
        raise RuntimeConfigError("runtime_config_mode_rejected")
    if before.st_size > MAX_CONFIG_BYTES:
        raise RuntimeConfigError("runtime_config_size_rejected")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(CONFIG_PATH, flags)
    except FileNotFoundError as exc:
        raise RuntimeConfigError("runtime_config_missing") from exc
    except OSError as exc:
        raise RuntimeConfigError("runtime_config_open_rejected") from exc
    try:
        opened = os.fstat(descriptor)
        if not _same_identity(before, opened):
            raise RuntimeConfigError("runtime_config_changed")
        if not stat.S_ISREG(opened.st_mode):
            raise RuntimeConfigError("runtime_config_type_rejected")
        if opened.st_uid != uid:
            raise RuntimeConfigError("runtime_config_owner_rejected")
        if opened.st_gid != gid:
            raise RuntimeConfigError("runtime_config_group_rejected")
        if not _valid_file_mode(opened.st_mode):
            raise RuntimeConfigError("runtime_config_mode_rejected")
        payload = os.read(descriptor, MAX_CONFIG_BYTES + 1)
        if len(payload) > MAX_CONFIG_BYTES:
            raise RuntimeConfigError("runtime_config_size_rejected")
    except RuntimeConfigError:
        raise
    except OSError as exc:
        raise RuntimeConfigError("runtime_config_open_rejected") from exc
    finally:
        os.close(descriptor)
    try:
        after = os.lstat(CONFIG_PATH)
    except OSError as exc:
        raise RuntimeConfigError("runtime_config_changed") from exc
    if not _same_identity(opened, after):
        raise RuntimeConfigError("runtime_config_changed")
    return payload


def _parse_config(payload: bytes) -> RuntimeConfig:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeConfigError("runtime_config_encoding_rejected") from exc
    if text.startswith("\ufeff"):
        raise RuntimeConfigError("runtime_config_bom_rejected")
    if not text.endswith("\n") or "\r" in text:
        raise RuntimeConfigError("runtime_config_syntax_rejected")
    lines = text[:-1].split("\n")
    if len(lines) != 3 or any(not line for line in lines):
        raise RuntimeConfigError("runtime_config_schema_rejected")
    values: dict[str, str] = {}
    prohibited = set("'\"`$\\#;()")
    for line in lines:
        if line.count("=") != 1:
            raise RuntimeConfigError("runtime_config_syntax_rejected")
        key, value = line.split("=", 1)
        if not key or not value:
            raise RuntimeConfigError("runtime_config_schema_rejected")
        if any(character.isspace() for character in key + value):
            raise RuntimeConfigError("runtime_config_whitespace_rejected")
        if any(character in prohibited for character in key + value):
            raise RuntimeConfigError("runtime_config_syntax_rejected")
        if key in values:
            raise RuntimeConfigError("runtime_config_duplicate_key")
        if key not in ALLOWED_KEYS:
            raise RuntimeConfigError("runtime_config_unknown_key")
        values[key] = value
    if set(values) != ALLOWED_KEYS:
        raise RuntimeConfigError("runtime_config_missing_key")
    if not values["github_app_id"].isdecimal() or not values["github_app_installation_id"].isdecimal():
        raise RuntimeConfigError("runtime_config_identifier_rejected")
    if values["private_key_path"] != str(APPROVED_KEY_PATH):
        raise RuntimeConfigError("runtime_config_key_path_rejected")
    return RuntimeConfig(values["github_app_id"], values["github_app_installation_id"], values["private_key_path"])


def _validate_key(uid: int, gid: int, key_path: str) -> None:
    if key_path != str(APPROVED_KEY_PATH):
        raise RuntimeConfigError("runtime_config_key_path_rejected")
    _validate_parent_chain(APPROVED_KEY_PATH, uid, gid)
    try:
        info = os.lstat(APPROVED_KEY_PATH)
    except OSError as exc:
        raise RuntimeConfigError("runtime_key_missing") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise RuntimeConfigError("runtime_key_type_rejected")
    if info.st_uid != uid:
        raise RuntimeConfigError("runtime_key_owner_rejected")
    if info.st_gid != gid:
        raise RuntimeConfigError("runtime_key_group_rejected")
    if not _valid_file_mode(info.st_mode):
        raise RuntimeConfigError("runtime_key_mode_rejected")


def load_runtime_config() -> RuntimeConfig:
    """Load validated fixed settings without environment fallback."""
    uid, gid = _identity()
    settings = _parse_config(_read_config(uid, gid))
    _validate_key(uid, gid, settings.key_path)
    return settings
