from __future__ import annotations

import signal
from pathlib import Path

from app.coordinator_service import CoordinatorService
from app.service_config import parse_service_config
import app.service_main as service_main


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


class EmptyWorkSource:
    def next_work(self):
        return None


class PassthroughCapabilityProvider:
    def bind(self, work_source):
        return work_source


class StopRecorder:
    def __init__(self) -> None:
        self.calls = 0

    def request_stop(self) -> None:
        self.calls += 1


def _config_file(tmp_path: Path, content: str = VALID_CONFIG) -> Path:
    path = tmp_path / "hermes-coordinator.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def test_check_config_does_not_construct_or_touch_runtime(tmp_path: Path, monkeypatch) -> None:
    config_path = _config_file(tmp_path)

    def unexpected_factory(*args, **kwargs):
        raise AssertionError("runtime factory must not run during --check-config")

    monkeypatch.setattr(service_main, "build_coordinator_service", unexpected_factory)

    assert service_main.main(["--config", str(config_path), "--check-config"]) == 0


def test_sigterm_requests_bounded_service_stop(monkeypatch) -> None:
    handlers = {}
    recorder = StopRecorder()
    monkeypatch.setattr(signal, "signal", lambda number, handler: handlers.setdefault(number, handler))

    service_main.install_stop_signal_handlers(recorder)
    handlers[signal.SIGTERM](signal.SIGTERM, None)

    assert recorder.calls == 1


def test_sigint_requests_bounded_service_stop(monkeypatch) -> None:
    handlers = {}
    recorder = StopRecorder()
    monkeypatch.setattr(signal, "signal", lambda number, handler: handlers.setdefault(number, handler))

    service_main.install_stop_signal_handlers(recorder)
    handlers[signal.SIGINT](signal.SIGINT, None)

    assert recorder.calls == 1


def test_normal_runtime_start_fails_closed_without_production_capabilities(tmp_path: Path, monkeypatch, capsys) -> None:
    config_path = _config_file(tmp_path)

    def unexpected_factory(*args, **kwargs):
        raise AssertionError("capability bootstrap gate must run before factory")

    monkeypatch.setattr(service_main, "build_coordinator_service", unexpected_factory)

    assert service_main.main(["--config", str(config_path)]) == service_main.CAPABILITY_BOOTSTRAP_EXIT_CODE
    assert capsys.readouterr().err == service_main.CAPABILITY_BOOTSTRAP_STATUS + "\n"


def test_entrypoint_error_does_not_leak_config_or_capability_data(tmp_path: Path, capsys) -> None:
    capability = "capability-value-must-not-leak"
    config_path = _config_file(tmp_path, VALID_CONFIG + f"capability_proof: {capability}\n")

    assert service_main.main(["--config", str(config_path), "--check-config"]) == service_main.CONFIG_ERROR_EXIT_CODE

    captured = capsys.readouterr()
    assert captured.err == service_main.CONFIG_ERROR_STATUS + "\n"
    assert capability not in captured.err
    assert str(config_path) not in captured.err


def test_runtime_factory_wires_existing_runtime_without_starting_it(tmp_path: Path) -> None:
    config = parse_service_config(_config_file(tmp_path))

    service = service_main.build_coordinator_service(
        config,
        work_source=EmptyWorkSource(),
        capability_provider=PassthroughCapabilityProvider(),
    )

    assert isinstance(service, CoordinatorService)
    assert service.idle_interval_seconds == 1.0
    assert service.provider_observer.probe.hermes_executable == config.hermes_executable
    assert service.turn_runner.hermes_runner.hermes_executable == config.hermes_executable
    assert service.turn_runner.hermes_runner.runtime_dir == config.runtime_directory
    assert service.turn_runner.hermes_runner.hermes_home == config.hermes_home


def test_systemd_unit_source_contains_identity_runtime_and_direct_execstart() -> None:
    unit_path = Path(__file__).resolve().parents[3] / "deploy/systemd/megabrain-hermes-coordinator.service"
    source = unit_path.read_text(encoding="utf-8")

    assert "User=megabrain-hermes" in source
    assert "Group=megabrain-hermes" in source
    assert "SupplementaryGroups=megabrain-control-plane-clients" in source
    assert "RuntimeDirectory=megabrain-hermes-coordinator" in source
    assert "StateDirectory=megabrain-hermes-coordinator" in source
    assert "UMask=0077" in source
    assert "ExecStart=/opt/megabrain/bin/megabrain-hermes-coordinator --config /etc/megabrain/hermes-coordinator.yaml" in source
    assert "/bin/sh -c" not in source
    assert "bash -c" not in source
    assert "shell=True" not in source


def test_systemd_unit_is_repo_source_only_and_not_an_activation_script() -> None:
    unit_path = Path(__file__).resolve().parents[3] / "deploy/systemd/megabrain-hermes-coordinator.service"
    source = unit_path.read_text(encoding="utf-8")

    assert unit_path.is_file()
    assert "systemctl" not in source
    assert "daemon-reload" not in source
    assert "enable " not in source
    assert "start " not in source
