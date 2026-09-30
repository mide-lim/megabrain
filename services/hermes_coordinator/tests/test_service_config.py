from __future__ import annotations

from pathlib import Path

import pytest

from app.service_config import ConfigError, MAX_CONFIG_BYTES, parse_service_config


VALID_CONFIG = """\
version: 1
control_plane_socket: /run/megabrain/control-plane.sock
channel_id: openai_codex
idle_interval_seconds: 1
hermes_executable: /opt/megabrain/bin/hermes
runtime_directory: /run/megabrain-hermes-coordinator
state_directory: /var/lib/megabrain-hermes-coordinator
hermes_home: /var/lib/megabrain-hermes-coordinator/hermes-home
"""


def _config_file(tmp_path: Path, content: str = VALID_CONFIG) -> Path:
    path = tmp_path / "hermes-coordinator.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def test_valid_service_config_parses_without_creating_runtime_paths(tmp_path: Path) -> None:
    config = parse_service_config(_config_file(tmp_path))

    assert config.version == 1
    assert config.control_plane_socket == Path("/run/megabrain/control-plane.sock")
    assert config.channel_id == "openai_codex"
    assert config.idle_interval_seconds == 1.0
    assert config.hermes_executable == "/opt/megabrain/bin/hermes"
    assert config.runtime_directory == Path("/run/megabrain-hermes-coordinator")
    assert config.state_directory == Path("/var/lib/megabrain-hermes-coordinator")
    assert config.hermes_home == Path("/var/lib/megabrain-hermes-coordinator/hermes-home")
    assert not config.runtime_directory.exists()


def test_unknown_config_key_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="unknown configuration key"):
        parse_service_config(_config_file(tmp_path, VALID_CONFIG + "unexpected: value\n"))


def test_duplicate_config_key_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="duplicate configuration key"):
        parse_service_config(_config_file(tmp_path, VALID_CONFIG + "channel_id: openai_codex\n"))


def test_oversized_config_is_rejected(tmp_path: Path) -> None:
    oversized = VALID_CONFIG + "#" * (MAX_CONFIG_BYTES + 1)
    with pytest.raises(ConfigError, match="configuration exceeds size limit"):
        parse_service_config(_config_file(tmp_path, oversized))


def test_unsupported_version_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="unsupported configuration version"):
        parse_service_config(_config_file(tmp_path, VALID_CONFIG.replace("version: 1", "version: 2")))


@pytest.mark.parametrize(
    "field,value",
    [
        ("control_plane_socket", "relative.sock"),
        ("runtime_directory", "runtime"),
        ("state_directory", "state"),
        ("hermes_home", "home"),
        ("hermes_executable", "bin/hermes"),
    ],
)
def test_relative_production_paths_are_rejected(tmp_path: Path, field: str, value: str) -> None:
    content = VALID_CONFIG.replace(
        next(line for line in VALID_CONFIG.splitlines() if line.startswith(f"{field}:")),
        f"{field}: {value}",
    )
    with pytest.raises(ConfigError, match="absolute"):
        parse_service_config(_config_file(tmp_path, content))


@pytest.mark.parametrize(
    "field,value",
    [
        ("runtime_directory", "/tmp/megabrain-hermes-coordinator"),
        ("state_directory", "/tmp/megabrain-hermes-coordinator"),
    ],
)
def test_shared_tmp_runtime_or_state_is_rejected(tmp_path: Path, field: str, value: str) -> None:
    content = VALID_CONFIG.replace(
        next(line for line in VALID_CONFIG.splitlines() if line.startswith(f"{field}:")),
        f"{field}: {value}",
    )
    with pytest.raises(ConfigError, match="temporary shared path"):
        parse_service_config(_config_file(tmp_path, content))


def test_control_plane_registry_path_is_rejected(tmp_path: Path) -> None:
    content = VALID_CONFIG.replace(
        "state_directory: /var/lib/megabrain-hermes-coordinator",
        "state_directory: /var/lib/megabrain-control-plane",
    )
    with pytest.raises(ConfigError, match="Control Plane registry"):
        parse_service_config(_config_file(tmp_path, content))


def test_invalid_channel_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="unsupported channel"):
        parse_service_config(_config_file(tmp_path, VALID_CONFIG.replace("openai_codex", "unknown_channel")))


@pytest.mark.parametrize("idle", ["0", "6", "true", "\"1\""])
def test_idle_interval_outside_bounds_or_wrong_type_is_rejected(tmp_path: Path, idle: str) -> None:
    with pytest.raises(ConfigError, match="idle interval"):
        parse_service_config(_config_file(tmp_path, VALID_CONFIG.replace("idle_interval_seconds: 1", f"idle_interval_seconds: {idle}")))


@pytest.mark.parametrize("key", ["capability_proof", "bootstrap_secret", "provider_token", "Authorization", "api_key", "oauth_token", "password"])
def test_secret_like_config_keys_are_rejected(tmp_path: Path, key: str) -> None:
    with pytest.raises(ConfigError, match="secret-like configuration"):
        parse_service_config(_config_file(tmp_path, VALID_CONFIG + f"{key}: never-store-this\n"))


def test_missing_required_field_is_rejected(tmp_path: Path) -> None:
    content = "\n".join(line for line in VALID_CONFIG.splitlines() if not line.startswith("hermes_home:")) + "\n"
    with pytest.raises(ConfigError, match="missing required configuration fields"):
        parse_service_config(_config_file(tmp_path, content))
