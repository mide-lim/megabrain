from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import shutil
import tempfile
import threading
from pathlib import Path

import pytest

from app.control_plane_client import ControlPlaneClient, ControlPlaneRemoteError
from app.coordinator_service import CoordinatorService, CoordinatorWorkItem
from app.coordinator_turn import CoordinatorTurnRunner
from app.errors import ExecutionStatus
from app.hermes_oneshot import HermesOneShotRunner
from app.production_capabilities import ProductionCapabilityProvider
from app.provider_classifier import ProviderObservation, ProviderState, ReasonCode
from app.provider_control_plane import ProviderObservationClient
from control_plane_fixture import CORRELATION_ID, _module, _task_body


RAW_BOOTSTRAP_SECRET = "sentinel-bootstrap-secret-" + "r" * 64
SIGNING_KEY = b"sentinel-capability-signing-key-" + b"s" * 48


class OneWork:
    def __init__(self, item: CoordinatorWorkItem) -> None:
        self.item = item

    def next_work(self) -> CoordinatorWorkItem | None:
        item, self.item = self.item, None
        return item


class StaticProviderObserver:
    def __init__(self, state: ProviderState) -> None:
        self.state = state

    def observe(self, channel_id: str) -> ProviderObservation:
        return ProviderObservation(
            channel_id=channel_id,
            provider="openai-codex",
            state=self.state,
            observed_at="2026-09-30T12:01:00.000Z",
            provider_fetched_at="2026-09-30T12:00:00.000Z",
            reset_at="2026-09-30T18:00:00.000Z" if self.state is ProviderState.QUOTA_EXHAUSTED else None,
            source="codex account usage",
            reason_code=ReasonCode.USAGE_WINDOW_EXHAUSTED if self.state is ProviderState.QUOTA_EXHAUSTED else ReasonCode.USAGE_AVAILABLE,
            windows_summary=(),
            probe_exit_code=0,
            timed_out=False,
        )


def _credentials(tmp_path: Path) -> tuple[Path, Path]:
    control_plane = tmp_path / "control-plane-credentials"
    coordinator = tmp_path / "coordinator-credentials"
    control_plane.mkdir(mode=0o700)
    coordinator.mkdir(mode=0o700)
    verifier = {
        "version": 1,
        "bootstrap_id": "coordinator-v1",
        "generation": 1,
        "verifier_sha256": hashlib.sha256(RAW_BOOTSTRAP_SECRET.encode("utf-8")).hexdigest(),
    }
    (control_plane / "control-plane-coordinator-bootstrap-verifier").write_text(json.dumps(verifier), encoding="utf-8")
    (control_plane / "control-plane-capability-signing-key").write_bytes(SIGNING_KEY)
    (coordinator / "control-plane-coordinator-bootstrap").write_text(
        json.dumps({"version": 1, "bootstrap_id": "coordinator-v1", "secret": RAW_BOOTSTRAP_SECRET}),
        encoding="utf-8",
    )
    return control_plane, coordinator


def _start_control_plane(tmp_path: Path):
    auth = _module("auth")
    main = _module("main")
    service_module = _module("service")
    control_plane_credentials, coordinator_credentials = _credentials(tmp_path)
    database = tmp_path / "control-plane.sqlite"
    service = service_module.ControlPlaneService(database)
    hermes = {"role": "HERMES_COORDINATOR", "identity_id": "hermes"}
    task_id = service.create_task(hermes, "production-create", CORRELATION_ID, _task_body())["task_id"]
    service.transition_task(hermes, "production-ready", CORRELATION_ID, task_id, 0, "READY")
    service.close()
    socket_dir = Path(tempfile.mkdtemp(prefix="mb-cap-", dir="/tmp"))
    socket_path = socket_dir / "control-plane.sock"
    authority = auth.ProductionCapabilityAuthority.from_credential_directory(
        control_plane_credentials,
        expected_peer_uid=os.getuid(),
    )
    stop, ready = threading.Event(), threading.Event()
    thread = threading.Thread(
        target=main.serve,
        args=(socket_path, database),
        kwargs={"issuer": authority, "stop_event": stop, "ready_event": ready},
        daemon=True,
    )
    thread.start()
    assert ready.wait(2)
    return socket_path, database, task_id, coordinator_credentials, stop, thread


def _work(task_id: str) -> CoordinatorWorkItem:
    return CoordinatorWorkItem(
        task_id=task_id,
        correlation_id=CORRELATION_ID,
        channel_id="openai_codex",
        task_packet="bounded production capability test",
        observed_context_tokens=1,
        max_iterations=1,
        timeout_seconds=2,
        usage_file_path="usage/turn.json",
        recommended_api_call_budget=None,
        coordinator_capability={},
        observer_capability={},
    )


def _counting_fake_hermes(tmp_path: Path) -> tuple[HermesOneShotRunner, Path]:
    tmp_path.mkdir(mode=0o700, parents=True, exist_ok=True)
    executable = tmp_path / "fake-hermes"
    count = tmp_path / "spawns.txt"
    executable.write_text(
        """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

with Path(os.environ['FAKE_HERMES_COUNT']).open('a', encoding='utf-8') as handle:
    handle.write('1\\n')
if sys.argv[1:2] != ['--oneshot'] or len(sys.argv) != 5 or sys.argv[3] != '--usage-file':
    sys.exit(91)
Path(sys.argv[4]).write_text(json.dumps({
    'estimated_cost_usd': 0.01, 'cost_status': 'estimated', 'cost_source': 'fixture',
    'input_tokens': 2, 'output_tokens': 3, 'cache_read_tokens': 1, 'cache_write_tokens': 0,
    'reasoning_tokens': 0, 'total_tokens': 5, 'api_calls': 1, 'model': 'fake',
    'provider': 'test', 'session_id': 'sid', 'completed': True, 'partial': False,
    'interrupted': False, 'turn_exit_reason': 'stop', 'failed': False, 'service_tier': None,
    'auxiliary': {'api_calls': 0, 'input_tokens': 0, 'output_tokens': 0,
                  'cache_read_tokens': 0, 'cache_write_tokens': 0, 'reasoning_tokens': 0,
                  'estimated_cost_usd': 0, 'total_tokens': 0, 'by_task': {}},
    'total_including_auxiliary': {'estimated_cost_usd': 0.01, 'total_tokens': 5, 'api_calls': 1},
}), encoding='utf-8')
""",
        encoding="utf-8",
    )
    executable.chmod(0o700)
    return HermesOneShotRunner(tmp_path / "runtime", hermes_executable=str(executable), environment={"FAKE_HERMES_COUNT": str(count)}), count


def _assert_secret_free(database: Path) -> None:
    with sqlite3.connect(database) as connection:
        dump = "\n".join(row[0] for row in connection.iterdump())
        event_payloads = "\n".join(row[0] for row in connection.execute("SELECT payload FROM audit_events"))
        provider_metadata = "\n".join(row[0] for row in connection.execute("SELECT metadata FROM provider_channel_states"))
        checkpoint_data = repr(connection.execute("SELECT * FROM checkpoints").fetchall())
    for forbidden in (RAW_BOOTSTRAP_SECRET, SIGNING_KEY.decode("utf-8"), "capability_proof"):
        assert forbidden not in dump
        assert forbidden not in event_payloads
        assert forbidden not in provider_metadata
        assert forbidden not in checkpoint_data


@pytest.mark.parametrize(
    ("provider_state", "expected_status", "expected_spawns"),
    [
        (ProviderState.AVAILABLE, ExecutionStatus.COMPLETED, 1),
        (ProviderState.QUOTA_EXHAUSTED, ExecutionStatus.PROVIDER_QUOTA_PAUSED, 0),
    ],
)
def test_production_capability_exchange_over_real_uds_persists_observation_and_gates_hermes(
    tmp_path: Path,
    provider_state: ProviderState,
    expected_status: ExecutionStatus,
    expected_spawns: int,
) -> None:
    socket_path, database, task_id, coordinator_credentials, stop, thread = _start_control_plane(tmp_path)
    try:
        fake_hermes, spawn_count = _counting_fake_hermes(tmp_path / "fake-hermes")
        capability_provider = ProductionCapabilityProvider(
            ControlPlaneClient(socket_path),
            credential_directory=coordinator_credentials,
        )
        service = CoordinatorService(
            work_source=capability_provider.bind(OneWork(_work(task_id))),
            provider_observer=StaticProviderObserver(provider_state),
            provider_observation_client=ProviderObservationClient(socket_path),
            turn_runner=CoordinatorTurnRunner(ControlPlaneClient(socket_path), fake_hermes),
            idle_interval_seconds=1,
        )

        service.start()
        result = service.run_cycle()

        assert result.status == expected_status.value
        assert (len(spawn_count.read_text(encoding="utf-8").splitlines()) if spawn_count.exists() else 0) == expected_spawns
        with sqlite3.connect(database) as connection:
            assert connection.execute("SELECT state FROM provider_channel_states WHERE channel_id='openai_codex'").fetchone() == (provider_state.value,)
            assert connection.execute("SELECT model_calls_used FROM task_execution_budgets WHERE task_id=?", (task_id,)).fetchone() == (expected_spawns,)
        with pytest.raises(ControlPlaneRemoteError) as error:
            ControlPlaneClient(socket_path).exchange_coordinator_bootstrap(
                bootstrap_id="coordinator-v1",
                bootstrap_secret="wrong-bootstrap-secret",
                task_id=task_id,
                channel_id="openai_codex",
                correlation_id=CORRELATION_ID,
            )
        assert all(forbidden not in repr(error.value) for forbidden in (RAW_BOOTSTRAP_SECRET, SIGNING_KEY.decode("utf-8"), "capability_proof"))
        _assert_secret_free(database)
    finally:
        stop.set()
        thread.join(2)
        shutil.rmtree(socket_path.parent, ignore_errors=True)
