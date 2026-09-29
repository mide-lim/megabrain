"""One bounded coordinator turn: Control Plane admission then Hermes one-shot."""
from __future__ import annotations

from dataclasses import replace
from typing import Any

from .admission import CoordinatorAdmissionService
from .control_plane_client import ControlPlaneClient
from .errors import ExecutionStatus
from .hermes_oneshot import HermesOneShotRunner
from .models import ExecutionResult


class CoordinatorTurnRunner:
    """Runs at most one coordinator turn and never retries Control Plane admission."""

    def __init__(self, client: ControlPlaneClient, hermes_runner: HermesOneShotRunner) -> None:
        self.admission_service = CoordinatorAdmissionService(client)
        self.hermes_runner = hermes_runner

    def run(
        self,
        *,
        task_id: str,
        correlation_id: str,
        channel_id: str,
        observed_context_tokens: int,
        max_iterations: int,
        timeout_seconds: int,
        usage_file_path: str,
        recommended_api_call_budget: int | None,
        capability: dict[str, Any],
        task_packet: str,
        admission_idempotency_key: str | None = None,
    ) -> ExecutionResult:
        admission = self.admission_service.prepare(
            task_id=task_id,
            correlation_id=correlation_id,
            channel_id=channel_id,
            observed_context_tokens=observed_context_tokens,
            max_iterations=max_iterations,
            timeout_seconds=timeout_seconds,
            usage_file_path=usage_file_path,
            recommended_api_call_budget=recommended_api_call_budget,
            capability=capability,
            admission_idempotency_key=admission_idempotency_key,
        )
        if admission.decision != "ADMIT":
            try:
                return ExecutionResult(status=ExecutionStatus(admission.decision))
            except (TypeError, ValueError):
                return ExecutionResult(status=ExecutionStatus.ADMISSION_DENIED)
        result = self.hermes_runner.run(admission, task_packet)
        if result.status is ExecutionStatus.SPAWN_FAILED and admission.decision == "ADMIT":
            return replace(result, status=ExecutionStatus.SPAWN_FAILED_AFTER_ADMISSION)
        return result
