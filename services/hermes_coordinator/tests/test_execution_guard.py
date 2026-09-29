from __future__ import annotations

import pytest

from helpers import SERVICE_ROOT, admission, runner
from app.errors import ExecutionStatus
from app.execution_guard import ExecutionGuard


@pytest.mark.parametrize(
    "decision",
    [
        "BLOCK_BUDGET",
        "PAUSE_PROVIDER_QUOTA",
        "BLOCK_PROVIDER_AUTH",
        "BLOCK_PROVIDER_UNKNOWN",
        "STOP_AND_CHECKPOINT",
        "CHECKPOINT_REQUIRED",
        None,
    ],
)
def test_non_admit_never_invokes_hermes(tmp_path, decision) -> None:
    instance, marker, _ = runner(tmp_path)

    result = instance.run(admission(decision=decision), "packet")

    assert result.status is ExecutionStatus.ADMISSION_DENIED
    assert not marker.exists()


def test_missing_admission_never_invokes_hermes(tmp_path) -> None:
    instance, marker, _ = runner(tmp_path)

    result = instance.run(None, "packet")

    assert result.status is ExecutionStatus.ADMISSION_DENIED
    assert not marker.exists()


def test_soft_context_limit_requires_checkpoint_without_spawn(tmp_path) -> None:
    instance, marker, _ = runner(tmp_path)

    result = instance.run(admission(context_tokens=80), "packet")

    assert result.status is ExecutionStatus.CHECKPOINT_REQUIRED
    assert not marker.exists()


def test_hard_context_limit_stops_and_checkpoints_without_spawn(tmp_path) -> None:
    instance, marker, _ = runner(tmp_path)

    result = instance.run(admission(context_tokens=120), "packet")

    assert result.status is ExecutionStatus.STOP_AND_CHECKPOINT
    assert not marker.exists()


@pytest.mark.parametrize("field,value", [("max_iterations", 0), ("max_iterations", 101), ("timeout_seconds", 0), ("timeout_seconds", 901)])
def test_invalid_execution_config_fails_closed(tmp_path, field, value) -> None:
    instance, marker, _ = runner(tmp_path)

    result = instance.run(admission(**{field: value}), "packet")

    assert result.status is ExecutionStatus.INVALID_EXECUTION_CONFIG
    assert not marker.exists()


def test_admit_permits_fake_process_spawn(tmp_path) -> None:
    instance, marker, _ = runner(tmp_path)

    result = instance.run(admission(), "compact task packet")

    assert result.status is ExecutionStatus.COMPLETED
    assert marker.exists()
