from __future__ import annotations

import pytest

from helpers import SERVICE_ROOT
from control_plane_fixture import CORRELATION_ID, ControlPlaneFixture
from app.admission import CoordinatorAdmissionService
from app.control_plane_client import ControlPlaneClient
from app.errors import ExecutionStatus


OPERATIONS = ["GetExecutionBudget", "EvaluateProviderPreflight", "AdmitModelCall"]


def prepare(fixture: ControlPlaneFixture, *, context_tokens: int = 1, **kwargs):
    service = CoordinatorAdmissionService(ControlPlaneClient(fixture.socket_path))
    return service.prepare(
        task_id=fixture.task_id,
        correlation_id=CORRELATION_ID,
        channel_id="test-channel",
        observed_context_tokens=context_tokens,
        max_iterations=7,
        timeout_seconds=2,
        usage_file_path="usage/turn.json",
        recommended_api_call_budget=None,
        capability=fixture.capability(OPERATIONS),
        **kwargs,
    )


def test_available_provider_produces_authoritative_execution_admission(tmp_path) -> None:
    fixture = ControlPlaneFixture(tmp_path, "AVAILABLE")
    try:
        admission = prepare(fixture)

        assert admission.decision == "ADMIT"
        assert admission.task_id == fixture.task_id
        assert admission.correlation_id == CORRELATION_ID
        assert admission.context_soft_limit == 80000
        assert admission.context_hard_limit == 120000
        assert fixture.budget()["model_calls_used"] == 1
    finally:
        fixture.close()


@pytest.mark.parametrize(
    ("provider_state", "expected"),
    [
        ("QUOTA_EXHAUSTED", ExecutionStatus.PROVIDER_QUOTA_PAUSED.value),
        ("AUTH_EXPIRED", ExecutionStatus.PROVIDER_AUTH_BLOCKED.value),
        ("UNKNOWN", ExecutionStatus.PROVIDER_UNKNOWN.value),
    ],
)
def test_provider_preflight_blocks_without_model_debit(tmp_path, provider_state, expected) -> None:
    fixture = ControlPlaneFixture(tmp_path, provider_state)
    try:
        admission = prepare(fixture)

        assert admission.decision == expected
        assert fixture.budget()["model_calls_used"] == 0
    finally:
        fixture.close()


def test_global_budget_block_skips_model_call_admission(tmp_path) -> None:
    fixture = ControlPlaneFixture(tmp_path, "AVAILABLE")
    try:
        fixture.consume_calls(40)

        admission = prepare(fixture)

        assert admission.decision == ExecutionStatus.MODEL_CALL_BUDGET_BLOCKED.value
        assert fixture.budget()["model_calls_used"] == 40
    finally:
        fixture.close()


def test_context_thresholds_translate_to_non_spawn_admissions(tmp_path) -> None:
    fixture = ControlPlaneFixture(tmp_path, "AVAILABLE")
    try:
        soft = prepare(fixture, context_tokens=80000, admission_idempotency_key="soft-key")
        hard = prepare(fixture, context_tokens=120000, admission_idempotency_key="hard-key")

        assert soft.decision == "ADMIT"
        assert soft.context_tokens == soft.context_soft_limit
        assert hard.decision == ExecutionStatus.STOP_AND_CHECKPOINT.value
        assert fixture.budget()["model_calls_used"] == 1
    finally:
        fixture.close()


def test_unavailable_and_unauthorized_control_plane_fail_closed(tmp_path) -> None:
    fixture = ControlPlaneFixture(tmp_path, "AVAILABLE")
    try:
        fixture.stop_server()
        unavailable = prepare(fixture)
        assert unavailable.decision == ExecutionStatus.CONTROL_PLANE_UNAVAILABLE.value
    finally:
        fixture.close()

    fixture = ControlPlaneFixture(tmp_path / "unauthorized", "AVAILABLE")
    try:
        service = CoordinatorAdmissionService(ControlPlaneClient(fixture.socket_path))
        admission = service.prepare(
            task_id=fixture.task_id,
            correlation_id=CORRELATION_ID,
            channel_id="test-channel",
            observed_context_tokens=1,
            max_iterations=7,
            timeout_seconds=2,
            usage_file_path="usage/turn.json",
            recommended_api_call_budget=None,
            capability=fixture.capability(["GetExecutionBudget"], expires_at="2026-09-28T00:00:00.000Z"),
        )
        assert admission.decision == ExecutionStatus.CONTROL_PLANE_UNAUTHORIZED.value
    finally:
        fixture.close()
