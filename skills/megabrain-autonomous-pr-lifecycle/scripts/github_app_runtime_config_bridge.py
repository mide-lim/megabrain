#!/usr/bin/env python3
"""Narrow fixed-path bridge to the installed canonical B4.1 runtime loader."""
from __future__ import annotations

import importlib.util
import os
import pwd
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LOADER_PATH = Path(
    "/home/megabrain-hermes/.hermes/skills/megabrain/"
    "megabrain-github-app-auth/scripts/github_app_runtime_config.py"
)
EXPECTED_USER = "megabrain-hermes"
EXPECTED_MODE = 0o700


class RuntimeConfigBridgeError(Exception):
    """A sanitized, symbolic failure from the fixed B4.1 loader bridge."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class RuntimeSettings:
    """Validated stable metadata returned by canonical B4.1 validation only."""

    app_id: str
    installation_id: str
    key_path: str


def _expected_uid() -> int:
    try:
        return pwd.getpwnam(EXPECTED_USER).pw_uid
    except KeyError as exc:
        raise RuntimeConfigBridgeError("runtime_loader_identity_rejected") from exc


def _validate_loader_artifact() -> None:
    try:
        info = os.lstat(LOADER_PATH)
    except FileNotFoundError as exc:
        raise RuntimeConfigBridgeError("runtime_loader_missing") from exc
    except OSError as exc:
        raise RuntimeConfigBridgeError("runtime_loader_unavailable") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise RuntimeConfigBridgeError("runtime_loader_type_rejected")
    if info.st_uid != _expected_uid():
        raise RuntimeConfigBridgeError("runtime_loader_owner_rejected")
    if stat.S_IMODE(info.st_mode) != EXPECTED_MODE:
        raise RuntimeConfigBridgeError("runtime_loader_mode_rejected")


def _load_fixed_loader() -> Any:
    _validate_loader_artifact()
    try:
        specification = importlib.util.spec_from_file_location(
            "megabrain_b41_fixed_runtime_config", LOADER_PATH,
        )
        if specification is None or specification.loader is None:
            raise RuntimeError
        module = importlib.util.module_from_spec(specification)
        sys.modules[specification.name] = module
        specification.loader.exec_module(module)
        return module
    except RuntimeConfigBridgeError:
        raise
    except Exception as exc:
        raise RuntimeConfigBridgeError("runtime_loader_import_rejected") from exc


def load_runtime_settings() -> RuntimeSettings:
    """Load only frozen metadata via the installed B4.1 canonical loader."""
    loader = _load_fixed_loader()
    try:
        config = loader.load_runtime_config()
        app_id = config.app_id
        installation_id = config.installation_id
        key_path = config.key_path
    except Exception as exc:
        raise RuntimeConfigBridgeError("runtime_config_load_rejected") from exc
    if not all(isinstance(value, str) and value for value in (app_id, installation_id, key_path)):
        raise RuntimeConfigBridgeError("runtime_config_result_rejected")
    return RuntimeSettings(app_id=app_id, installation_id=installation_id, key_path=key_path)
