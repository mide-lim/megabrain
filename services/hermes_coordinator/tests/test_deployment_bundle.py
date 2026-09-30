from __future__ import annotations

import stat
from pathlib import Path

import pytest

from app.production_capabilities import IdleWorkSource
from app.service_config import parse_service_config
import app.service_main as service_main


ROOT = Path(__file__).resolve().parents[3]
DEPLOY = ROOT / "deploy"


@pytest.mark.parametrize(
    ("name", "application_root", "import_line"),
    [
        ("megabrain-control-plane", "/opt/megabrain/lib/control_plane", "from app.main import main"),
        ("megabrain-hermes-coordinator", "/opt/megabrain/lib/hermes_coordinator", "from app.service_main import main"),
    ],
)
def test_deployment_entrypoints_are_fixed_python_executables(name: str, application_root: str, import_line: str) -> None:
    path = DEPLOY / "bin" / name

    assert path.is_file()
    source = path.read_text(encoding="utf-8")
    assert path.stat().st_mode & stat.S_IXUSR
    assert source.startswith("#!/usr/bin/python3\n")
    assert application_root in source
    assert import_line in source
    for forbidden in ("/home", "worktree", "shell=True", "sh -c", "bash -c", "eval"):
        assert forbidden not in source


def test_production_coordinator_config_is_parseable_and_secret_free() -> None:
    path = DEPLOY / "config" / "hermes-coordinator.yaml"
    source = path.read_text(encoding="utf-8")
    config = parse_service_config(path)

    assert config.control_plane_socket == Path("/run/megabrain/control-plane.sock")
    assert config.hermes_executable == "/opt/megabrain/hermes/bin/hermes"
    assert config.idle_interval_seconds == 2.0
    for forbidden in ("capability", "bootstrap", "token", "authorization", "api_key", "oauth", "password", "secret"):
        assert forbidden not in source.lower()


@pytest.mark.parametrize(
    ("name", "entrypoint"),
    [
        ("megabrain-control-plane.service", "/opt/megabrain/bin/megabrain-control-plane"),
        ("megabrain-hermes-coordinator.service", "/opt/megabrain/bin/megabrain-hermes-coordinator"),
    ],
)
def test_systemd_units_use_fixed_direct_entrypoints(name: str, entrypoint: str) -> None:
    source = (DEPLOY / "systemd" / name).read_text(encoding="utf-8")

    assert f"ExecStart={entrypoint}" in source
    for forbidden in ("/home", "worktree", "shell=True", "sh -c", "bash -c"):
        assert forbidden not in source


def test_production_startup_binds_idle_work_source(monkeypatch, tmp_path: Path) -> None:
    config_path = tmp_path / "hermes-coordinator.yaml"
    config_path.write_text((DEPLOY / "config" / "hermes-coordinator.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    captured = {}

    monkeypatch.setattr(service_main, "ProductionCapabilityProvider", lambda _client: object())
    monkeypatch.setattr(service_main, "run_service", lambda _config, **kwargs: captured.update(kwargs))

    assert service_main.main(["--config", str(config_path)]) == 0
    assert isinstance(captured["work_source"], IdleWorkSource)
