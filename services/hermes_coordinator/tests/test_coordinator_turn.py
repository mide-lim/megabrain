from __future__ import annotations

import json
from pathlib import Path

import pytest

from helpers import SERVICE_ROOT, runner
from control_plane_fixture import CORRELATION_ID, ControlPlaneFixture
from app.control_plane_client import ControlPlaneClient
from app.coordinator_turn import CoordinatorTurnRunner
from app.errors import ExecutionStatus
from app.hermes_oneshot import HermesOneShotRunner


OPERATIONS = ["GetExecutionBudget", "EvaluateProviderPreflight", "AdmitModelCall"]


def turn_runner(fixture: ControlPlaneFixture, hermes_runner: HermesOneShotRunner) -> CoordinatorTurnRunner:
    return CoordinatorTurnRunner(ControlPlaneClient(fixture.socket_path), hermes_runner)


def turn(instance: CoordinatorTurnRunner, fixture: ControlPlaneFixture):
    return instance.run(
        task_id=fixture.task_id,
        correlation_id=CORRELATION_ID,
        channel_id="test-channel",
        observed_context_tokens=1,
        max_iterations=7,
        timeout_seconds=2,
        usage_file_path="usage/turn.json",
        recommended_api_call_budget=None,
        capability=fixture.capability(OPERATIONS),
        task_packet="bounded task packet",
    )


def test_real_control_plane_admission_runs_fake_hermes_once_and_debits_once(tmp_path) -> None:
    fixture = ControlPlaneFixture(tmp_path, "AVAILABLE")
    try:
        fake, marker, _ = runner(tmp_path / "fake")
        result = turn(turn_runner(fixture, fake), fixture)

        assert result.status is ExecutionStatus.COMPLETED
        assert result.usage is not None and result.usage.total_tokens == 5
        assert marker.exists()
        assert json.loads(marker.read_text(encoding="utf-8"))[1] == "--oneshot"
        assert fixture.budget()["model_calls_used"] == 1
    finally:
        fixture.close()


@pytest.mark.parametrize("provider_state", ["QUOTA_EXHAUSTED", "AUTH_EXPIRED", "UNKNOWN"])
def test_provider_block_never_spawns_fake_hermes(tmp_path, provider_state) -> None:
    fixture = ControlPlaneFixture(tmp_path, provider_state)
    try:
        fake, marker, _ = runner(tmp_path / "fake")
        result = turn(turn_runner(fixture, fake), fixture)

        assert result.status in {
            ExecutionStatus.PROVIDER_QUOTA_PAUSED,
            ExecutionStatus.PROVIDER_AUTH_BLOCKED,
            ExecutionStatus.PROVIDER_UNKNOWN,
        }
        assert not marker.exists()
        assert fixture.budget()["model_calls_used"] == 0
    finally:
        fixture.close()


@pytest.mark.parametrize(
    ("context_tokens", "expected", "debits"),
    [
        (80000, ExecutionStatus.CHECKPOINT_REQUIRED, 1),
        (120000, ExecutionStatus.STOP_AND_CHECKPOINT, 0),
    ],
)
def test_context_thresholds_never_spawn_fake_hermes(tmp_path, context_tokens, expected, debits) -> None:
    fixture = ControlPlaneFixture(tmp_path, "AVAILABLE")
    try:
        fake, marker, _ = runner(tmp_path / "fake")
        result = turn_runner(fixture, fake).run(
            task_id=fixture.task_id,
            correlation_id=CORRELATION_ID,
            channel_id="test-channel",
            observed_context_tokens=context_tokens,
            max_iterations=7,
            timeout_seconds=2,
            usage_file_path="usage/turn.json",
            recommended_api_call_budget=None,
            capability=fixture.capability(OPERATIONS),
            task_packet="bounded task packet",
        )

        assert result.status is expected
        assert not marker.exists()
        assert fixture.budget()["model_calls_used"] == debits
    finally:
        fixture.close()


def test_budget_and_capability_rejection_never_spawn_fake_hermes(tmp_path) -> None:
    fixture = ControlPlaneFixture(tmp_path, "AVAILABLE")
    try:
        fixture.consume_calls(40)
        fake, marker, _ = runner(tmp_path / "budget")
        result = turn(turn_runner(fixture, fake), fixture)
        assert result.status is ExecutionStatus.MODEL_CALL_BUDGET_BLOCKED
        assert not marker.exists()
    finally:
        fixture.close()

    fixture = ControlPlaneFixture(tmp_path / "capability", "AVAILABLE")
    try:
        fake, marker, _ = runner(tmp_path / "capability-fake")
        result = turn_runner(fixture, fake).run(
            task_id=fixture.task_id,
            correlation_id=CORRELATION_ID,
            channel_id="test-channel",
            observed_context_tokens=1,
            max_iterations=7,
            timeout_seconds=2,
            usage_file_path="usage/turn.json",
            recommended_api_call_budget=None,
            capability=fixture.capability(["GetExecutionBudget"], expires_at="2026-09-28T00:00:00.000Z"),
            task_packet="bounded task packet",
        )
        assert result.status is ExecutionStatus.CONTROL_PLANE_UNAUTHORIZED
        assert not marker.exists()
    finally:
        fixture.close()


def test_spawn_failure_after_admission_is_reported_without_budget_refund(tmp_path) -> None:
    fixture = ControlPlaneFixture(tmp_path, "AVAILABLE")
    try:
        absent = HermesOneShotRunner(tmp_path / "runtime", hermes_executable=str(tmp_path / "missing-hermes"))
        result = turn(turn_runner(fixture, absent), fixture)

        assert result.status is ExecutionStatus.SPAWN_FAILED_AFTER_ADMISSION
        assert fixture.budget()["model_calls_used"] == 1
    finally:
        fixture.close()


def test_coordinator_application_has_no_direct_sqlite_or_live_socket_access() -> None:
    app_dir = Path(__file__).resolve().parents[1] / "app"
    text = "\n".join(path.read_text(encoding="utf-8") for path in app_dir.glob("*.py"))

    for forbidden in ("sqlite3", "registry.db", "shell=True", "docker.sock", "0.0.0.0", "/run/megabrain/control-plane.sock", "systemctl"):
        assert forbidden not in text
