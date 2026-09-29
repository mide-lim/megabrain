"""Coordinator admission translation from fixed Control Plane operations."""
from __future__ import annotations

import uuid
from typing import Any

from .control_plane_client import (
    ControlPlaneClient,
    ControlPlaneProtocolError,
    ControlPlaneRemoteError,
    ControlPlaneUnavailableError,
)
from .errors import ExecutionStatus
from .models import ExecutionAdmission


class CoordinatorAdmissionService:
    """Performs one fresh, fail-closed coordinator model-call admission."""

    def __init__(self, client: ControlPlaneClient) -> None:
        self.client = client

    def prepare(
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
        admission_idempotency_key: str | None = None,
    ) -> ExecutionAdmission:
        base = {
            "task_id": task_id,
            "correlation_id": correlation_id,
            "max_iterations": max_iterations,
            "timeout_seconds": timeout_seconds,
            "context_tokens": observed_context_tokens,
            "usage_file_path": usage_file_path,
            # Logical Control Plane admissions do not prove a provider API-call
            # count; callers pass None unless they have a stricter trusted bound.
            "recommended_api_call_budget": recommended_api_call_budget,
        }
        try:
            budget = self.client.get_execution_budget(task_id, correlation_id, capability)
            soft_limit, hard_limit = self._limits(budget)
            preflight = self.client.evaluate_provider_preflight(task_id, correlation_id, channel_id, capability)
            preflight_decision = preflight.get("decision")
            blocked = self._preflight_block(preflight_decision)
            if blocked is not None:
                return ExecutionAdmission(decision=blocked.value, context_soft_limit=soft_limit, context_hard_limit=hard_limit, **base)
            if preflight_decision != "ADMIT":
                return ExecutionAdmission(
                    decision=ExecutionStatus.CONTROL_PLANE_PROTOCOL_ERROR.value,
                    context_soft_limit=soft_limit,
                    context_hard_limit=hard_limit,
                    **base,
                )
            key = admission_idempotency_key or f"coordinator-model-call-{uuid.uuid4()}"
            admitted = self.client.admit_model_call(task_id, correlation_id, observed_context_tokens, capability, idempotency_key=key)
            decision = admitted.get("decision")
            if decision == "ADMIT":
                translated = "ADMIT"
            elif decision == "BLOCK_BUDGET":
                translated = ExecutionStatus.MODEL_CALL_BUDGET_BLOCKED.value
            elif decision == "STOP_AND_CHECKPOINT":
                translated = ExecutionStatus.STOP_AND_CHECKPOINT.value
            else:
                translated = ExecutionStatus.CONTROL_PLANE_PROTOCOL_ERROR.value
            return ExecutionAdmission(decision=translated, context_soft_limit=soft_limit, context_hard_limit=hard_limit, **base)
        except ControlPlaneUnavailableError:
            return self._failed(base, ExecutionStatus.CONTROL_PLANE_UNAVAILABLE)
        except ControlPlaneRemoteError as exc:
            status = ExecutionStatus.CONTROL_PLANE_UNAUTHORIZED if exc.code in {"UNAUTHORIZED", "UNKNOWN_IDENTITY"} else ExecutionStatus.CONTROL_PLANE_PROTOCOL_ERROR
            return self._failed(base, status)
        except (ControlPlaneProtocolError, ValueError, TypeError):
            return self._failed(base, ExecutionStatus.CONTROL_PLANE_PROTOCOL_ERROR)

    @staticmethod
    def _limits(budget: dict[str, Any]) -> tuple[int, int]:
        soft = budget.get("context_soft_limit_tokens")
        hard = budget.get("context_hard_limit_tokens")
        if (
            not isinstance(soft, int)
            or isinstance(soft, bool)
            or not isinstance(hard, int)
            or isinstance(hard, bool)
            or soft < 0
            or hard <= soft
        ):
            raise ControlPlaneProtocolError("invalid authoritative context limits")
        return soft, hard

    @staticmethod
    def _preflight_block(decision: object) -> ExecutionStatus | None:
        mapping = {
            "BLOCK_PROVIDER_AUTH": ExecutionStatus.PROVIDER_AUTH_BLOCKED,
            "PAUSE_PROVIDER_QUOTA": ExecutionStatus.PROVIDER_QUOTA_PAUSED,
            "BLOCK_PROVIDER_UNKNOWN": ExecutionStatus.PROVIDER_UNKNOWN,
            "BLOCK_BUDGET": ExecutionStatus.MODEL_CALL_BUDGET_BLOCKED,
        }
        return mapping.get(decision)

    @staticmethod
    def _failed(base: dict[str, Any], status: ExecutionStatus) -> ExecutionAdmission:
        return ExecutionAdmission(
            decision=status.value,
            context_soft_limit=None,
            context_hard_limit=None,
            **base,
        )
