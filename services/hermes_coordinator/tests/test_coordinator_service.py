from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.control_plane_client import ControlPlaneClient
from app.coordinator_service import (
    CoordinatorActivity,
    CoordinatorLifecycle,
    CoordinatorService,
    CoordinatorWorkItem,
)
from app.coordinator_turn import CoordinatorTurnRunner
from app.errors import ExecutionStatus
from app.hermes_oneshot import HermesOneShotRunner
from app.provider_classifier import ProviderObservation, ProviderState, ReasonCode
from app.provider_control_plane import ProviderObservationClient
from app.provider_observer import HermesUsageProbe, ProviderObserver
from control_plane_fixture import CORRELATION_ID, ControlPlaneFixture
from helpers import runner


FAKE_USAGE = """#!/usr/bin/env python3
import json
import os
import sys

if sys.argv[1:] != ['usage', '--provider', 'openai-codex', '--json']:
    sys.exit(91)
used = 100 if os.environ['FAKE_USAGE_MODE'] == 'quota' else 20
print(json.dumps({
    'provider': 'openai-codex', 'source': 'codex account usage',
    'title': 'Account limits', 'plan': 'Pro',
    'fetched_at': '2026-09-30T12:00:00+00:00',
    'windows': [{'label': '5h', 'used_percent': used, 'resets_at': '2026-09-30T18:00:00+00:00', 'detail': 'Account limit'}],
    'details': [], 'unavailable_reason': None,
}))
"""


class FakeWorkSource:
    def __init__(self, items: list[CoordinatorWorkItem | None]) -> None:
        self.items = list(items)
        self.calls = 0

    def next_work(self) -> CoordinatorWorkItem | None:
        self.calls += 1
        return self.items.pop(0) if self.items else None


class StaticObserver:
    def __init__(self, states: list[ProviderState]) -> None:
        self.states = list(states)
        self.calls = 0

    def observe(self, channel_id: str) -> ProviderObservation:
        self.calls += 1
        state = self.states.pop(0)
        return ProviderObservation(
            channel_id=channel_id,
            provider="openai-codex",
            state=state,
            observed_at="2026-09-30T12:01:00.000Z",
            provider_fetched_at="2026-09-30T12:00:00.000Z",
            reset_at="2026-09-30T18:00:00.000Z" if state is ProviderState.QUOTA_EXHAUSTED else None,
            source="codex account usage",
            reason_code=ReasonCode.USAGE_WINDOW_EXHAUSTED if state is ProviderState.QUOTA_EXHAUSTED else ReasonCode.USAGE_AVAILABLE,
            windows_summary=(),
            probe_exit_code=0,
            timed_out=False,
        )


class StoppedEvent:
    def is_set(self) -> bool:
        return True

    def wait(self, timeout: float) -> bool:
        return True


def _usage_observer(tmp_path: Path, mode: str) -> ProviderObserver:
    tmp_path.mkdir(mode=0o700, parents=True, exist_ok=True)
    executable = tmp_path / "fake-hermes-usage"
    executable.write_text(FAKE_USAGE, encoding="utf-8")
    executable.chmod(0o700)
    return ProviderObserver(
        probe=HermesUsageProbe(
            hermes_executable=str(executable),
            timeout_seconds=1,
            termination_grace_seconds=0.1,
            environment={"FAKE_USAGE_MODE": mode},
        ),
        clock=lambda: datetime(2026, 9, 30, 12, 1, tzinfo=timezone.utc),
    )


def _observer_capability(fixture: ControlPlaneFixture) -> dict:
    return fixture.issuer.issue(
        "observer-record",
        "OBSERVABILITY_ADAPTER",
        "observer",
        ["RecordProviderObservation"],
        "2099-01-01T00:00:00.000Z",
    )


def _work(fixture: ControlPlaneFixture, task_packet: str = "bounded work") -> CoordinatorWorkItem:
    return CoordinatorWorkItem(
        task_id=fixture.task_id,
        correlation_id=CORRELATION_ID,
        channel_id="openai_codex",
        task_packet=task_packet,
        observed_context_tokens=1,
        max_iterations=7,
        timeout_seconds=2,
        usage_file_path="usage/turn.json",
        recommended_api_call_budget=None,
        coordinator_capability=fixture.capability(["GetExecutionBudget", "EvaluateProviderPreflight", "AdmitModelCall"]),
        observer_capability=_observer_capability(fixture),
    )


def _service(
    source: FakeWorkSource,
    observer: object,
    fixture: ControlPlaneFixture,
    hermes_runner: HermesOneShotRunner,
) -> CoordinatorService:
    return CoordinatorService(
        work_source=source,
        provider_observer=observer,
        provider_observation_client=ProviderObservationClient(fixture.socket_path),
        turn_runner=CoordinatorTurnRunner(ControlPlaneClient(fixture.socket_path), hermes_runner),
        clock=lambda: datetime(2026, 9, 30, 12, 2, tzinfo=timezone.utc),
        idle_interval_seconds=1,
    )


def test_cycle_with_real_control_plane_and_fake_hermes_completes_once(tmp_path) -> None:
    fixture = ControlPlaneFixture(tmp_path)
    try:
        fake_hermes, marker, _ = runner(tmp_path / "oneshot")
        service = _service(FakeWorkSource([_work(fixture)]), _usage_observer(tmp_path / "usage", "available"), fixture, fake_hermes)

        service.start()
        result = service.run_cycle()
        health = service.health_snapshot()

        assert result.status == ExecutionStatus.COMPLETED.value
        assert json.loads(marker.read_text(encoding="utf-8"))[1] == "--oneshot"
        assert fixture.budget()["model_calls_used"] == 1
        assert health.state is CoordinatorLifecycle.READY
        assert health.activity is CoordinatorActivity.IDLE
        assert health.cycles_total == 1
        assert health.cycles_failed == 0
    finally:
        fixture.close()


def test_quota_observation_is_persisted_then_preflight_pauses_without_hermes_spawn(tmp_path) -> None:
    fixture = ControlPlaneFixture(tmp_path)
    try:
        fake_hermes, marker, _ = runner(tmp_path / "oneshot")
        service = _service(FakeWorkSource([_work(fixture)]), _usage_observer(tmp_path / "usage", "quota"), fixture, fake_hermes)

        service.start()
        result = service.run_cycle()

        assert result.status == ExecutionStatus.PROVIDER_QUOTA_PAUSED.value
        assert not marker.exists()
        assert fixture.budget()["model_calls_used"] == 0
        assert service.health_snapshot().state is CoordinatorLifecycle.READY
    finally:
        fixture.close()


def test_multiple_cycles_stay_alive_and_only_available_work_spawns_hermes(tmp_path) -> None:
    fixture = ControlPlaneFixture(tmp_path)
    try:
        fake_hermes, marker, _ = runner(tmp_path / "oneshot")
        work_a = _work(fixture, "task A")
        work_b = _work(fixture, "task B")
        source = FakeWorkSource([None, work_a, None, work_b, None])
        service = _service(source, StaticObserver([ProviderState.AVAILABLE, ProviderState.QUOTA_EXHAUSTED]), fixture, fake_hermes)

        service.start()
        results = [service.run_cycle() for _ in range(5)]
        health = service.health_snapshot()

        assert [result.status for result in results] == ["IDLE", "COMPLETED", "IDLE", "PROVIDER_QUOTA_PAUSED", "IDLE"]
        assert json.loads(marker.read_text(encoding="utf-8"))[2] == "task A"
        assert fixture.budget()["model_calls_used"] == 1
        assert health.state is CoordinatorLifecycle.READY
        assert health.cycles_total == 5
        assert health.cycles_failed == 0
        assert source.calls == 5
    finally:
        fixture.close()


def test_observation_record_unavailable_fails_closed_without_spawn_and_idle_recovers(tmp_path) -> None:
    fixture = ControlPlaneFixture(tmp_path)
    try:
        fake_hermes, marker, _ = runner(tmp_path / "oneshot")
        source = FakeWorkSource([_work(fixture), None])
        service = CoordinatorService(
            work_source=source,
            provider_observer=StaticObserver([ProviderState.AVAILABLE]),
            provider_observation_client=ProviderObservationClient(tmp_path / "missing.sock"),
            turn_runner=CoordinatorTurnRunner(ControlPlaneClient(fixture.socket_path), fake_hermes),
            clock=lambda: datetime(2026, 9, 30, 12, 2, tzinfo=timezone.utc),
            idle_interval_seconds=1,
        )

        service.start()
        failed = service.run_cycle()
        recovered = service.run_cycle()
        health = service.health_snapshot()

        assert failed.status == ExecutionStatus.CONTROL_PLANE_UNAVAILABLE.value
        assert not marker.exists()
        assert service.health_snapshot().cycles_failed == 1
        assert recovered.status == "IDLE"
        assert health.state is CoordinatorLifecycle.READY
        assert health.consecutive_failures == 0
    finally:
        fixture.close()


def test_stop_request_prevents_new_work_and_transitions_to_stopped(tmp_path) -> None:
    fixture = ControlPlaneFixture(tmp_path)
    try:
        fake_hermes, _, _ = runner(tmp_path / "oneshot")
        source = FakeWorkSource([_work(fixture)])
        service = _service(source, StaticObserver([ProviderState.AVAILABLE]), fixture, fake_hermes)

        service.start()
        service.request_stop()
        assert service.health_snapshot().state is CoordinatorLifecycle.STOPPING
        service.run_forever(StoppedEvent())

        health = service.health_snapshot()
        assert health.state is CoordinatorLifecycle.STOPPED
        assert source.calls == 0
        assert health.cycles_total == 0
    finally:
        fixture.close()


def test_work_item_is_frozen_and_never_reprs_capabilities_or_task_packet(tmp_path) -> None:
    fixture = ControlPlaneFixture(tmp_path)
    try:
        item = _work(fixture, "secret task packet")
        with pytest.raises(Exception):
            item.task_id = "changed"  # type: ignore[misc]
        representation = repr(item)
        assert "secret task packet" not in representation
        assert "observer-record" not in representation
        assert "fixture-capability" not in representation
    finally:
        fixture.close()
