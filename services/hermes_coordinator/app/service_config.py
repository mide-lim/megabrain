"""Strict, secret-free configuration for the coordinator service package."""
from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .provider_classifier import CHANNEL_PROVIDERS

CONFIG_VERSION = 1
MAX_CONFIG_BYTES = 32 * 1024
_REQUIRED_KEYS = frozenset(
    {
        "version",
        "control_plane_socket",
        "channel_id",
        "idle_interval_seconds",
        "hermes_executable",
        "runtime_directory",
        "state_directory",
        "hermes_home",
    }
)
_SECRET_MARKERS = ("capability", "bootstrap", "token", "authorization", "api_key", "oauth", "password", "secret")
_CONTROL_PLANE_REGISTRY_DIRECTORY = Path("/var/lib/megabrain-control-plane")


class ConfigError(ValueError):
    """A stable, non-sensitive configuration validation error."""


@dataclass(frozen=True)
class ServiceConfig:
    version: int
    control_plane_socket: Path
    channel_id: str
    idle_interval_seconds: float
    hermes_executable: str
    runtime_directory: Path
    state_directory: Path
    hermes_home: Path
    _source_path: Path = field(repr=False, compare=False)


def parse_service_config(path: str | Path) -> ServiceConfig:
    source_path = Path(path)
    raw = _read_bounded_regular_file(source_path)
    values = _parse_flat_yaml(raw)
    _reject_unexpected_keys(values)
    _require_required_keys(values)
    config = ServiceConfig(
        version=_version(values["version"]),
        control_plane_socket=_absolute_path(values["control_plane_socket"], "control plane socket"),
        channel_id=_channel(values["channel_id"]),
        idle_interval_seconds=_idle_interval(values["idle_interval_seconds"]),
        hermes_executable=_executable(values["hermes_executable"]),
        runtime_directory=_absolute_path(values["runtime_directory"], "runtime directory"),
        state_directory=_absolute_path(values["state_directory"], "state directory"),
        hermes_home=_absolute_path(values["hermes_home"], "Hermes home"),
        _source_path=source_path,
    )
    _validate_layout(config)
    _validate_existing_directories(config)
    return config


def _read_bounded_regular_file(path: Path) -> bytes:
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        raise ConfigError("configuration file is unavailable") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ConfigError("configuration file must be a regular file")
    if metadata.st_size > MAX_CONFIG_BYTES:
        raise ConfigError("configuration exceeds size limit")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ConfigError("configuration file is unavailable") from exc
    if len(raw) > MAX_CONFIG_BYTES:
        raise ConfigError("configuration exceeds size limit")
    return raw


def _parse_flat_yaml(raw: bytes) -> dict[str, Any]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ConfigError("configuration must be UTF-8") from exc
    values: dict[str, Any] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        if line.startswith((" ", "\t")) or line.lstrip().startswith("#"):
            raise ConfigError("configuration must be a flat mapping")
        if line.count(":") != 1:
            raise ConfigError("configuration contains an invalid mapping entry")
        key, raw_value = line.split(":", 1)
        if not key or key.strip() != key or not key.replace("_", "").isalnum():
            raise ConfigError("configuration contains an invalid key")
        if key in values:
            raise ConfigError("duplicate configuration key")
        value = raw_value.strip()
        if not value:
            raise ConfigError("configuration values must not be empty")
        values[key] = _scalar(value)
    return values


def _scalar(value: str) -> Any:
    if value.startswith('"'):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ConfigError("configuration contains an invalid string") from exc
        if not isinstance(parsed, str):
            raise ConfigError("configuration contains an invalid string")
        return parsed
    if value in {"true", "false"}:
        return value == "true"
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


def _reject_unexpected_keys(values: dict[str, Any]) -> None:
    for key in values:
        if any(marker in key.lower() for marker in _SECRET_MARKERS):
            raise ConfigError("secret-like configuration is prohibited")
        if key not in _REQUIRED_KEYS:
            raise ConfigError("unknown configuration key")


def _require_required_keys(values: dict[str, Any]) -> None:
    if _REQUIRED_KEYS - values.keys():
        raise ConfigError("missing required configuration fields")


def _version(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value != CONFIG_VERSION:
        raise ConfigError("unsupported configuration version")
    return value


def _channel(value: Any) -> str:
    if not isinstance(value, str) or value not in CHANNEL_PROVIDERS:
        raise ConfigError("unsupported channel")
    return value


def _idle_interval(value: Any) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not 1 <= float(value) <= 5:
        raise ConfigError("idle interval must be a number between one and five seconds")
    return float(value)


def _executable(value: Any) -> str:
    path = _absolute_path(value, "Hermes executable")
    return str(path)


def _absolute_path(value: Any, name: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{name} must be an absolute path")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise ConfigError(f"{name} must be an absolute path")
    return path


def _validate_layout(config: ServiceConfig) -> None:
    protected_paths = (config.runtime_directory, config.state_directory, config.hermes_home)
    if any(_is_under(path, Path("/tmp")) or _is_under(path, Path("/var/tmp")) for path in protected_paths):
        raise ConfigError("temporary shared path is not permitted")
    if any(_is_under(path, _CONTROL_PLANE_REGISTRY_DIRECTORY) for path in protected_paths):
        raise ConfigError("configured path must not use the Control Plane registry")
    if config.runtime_directory == config.state_directory:
        raise ConfigError("runtime and state directories must be distinct")
    if not _is_under(config.hermes_home, config.state_directory) or config.hermes_home == config.state_directory:
        raise ConfigError("Hermes home must be contained by the state directory")
    if config.control_plane_socket.suffix != ".sock":
        raise ConfigError("control plane socket must be a socket path")


def _validate_existing_directories(config: ServiceConfig) -> None:
    for path in (config.runtime_directory, config.state_directory, config.hermes_home):
        try:
            metadata = os.lstat(path)
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise ConfigError("configured directory cannot be inspected") from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise ConfigError("configured runtime path must be a directory")


def _is_under(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True
