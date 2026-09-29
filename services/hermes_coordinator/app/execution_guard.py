from __future__ import annotations

from .config import MAX_ITERATIONS, MAX_TIMEOUT_SECONDS, MIN_ITERATIONS, MIN_TIMEOUT_SECONDS
from .errors import ExecutionStatus
from .models import ExecutionAdmission, GuardDecision


class ExecutionGuard:
    """Pure fail-closed admission and context decision boundary."""

    def evaluate(self, admission: ExecutionAdmission | None) -> GuardDecision:
        if not isinstance(admission, ExecutionAdmission) or admission.decision != "ADMIT":
            return GuardDecision(False, ExecutionStatus.ADMISSION_DENIED)
        if not self._valid_config(admission):
            return GuardDecision(False, ExecutionStatus.INVALID_EXECUTION_CONFIG)
        if admission.context_tokens >= admission.context_hard_limit:
            return GuardDecision(False, ExecutionStatus.STOP_AND_CHECKPOINT)
        if admission.context_tokens >= admission.context_soft_limit:
            return GuardDecision(False, ExecutionStatus.CHECKPOINT_REQUIRED)
        return GuardDecision(True, ExecutionStatus.COMPLETED)

    @staticmethod
    def _is_int(value: object) -> bool:
        return isinstance(value, int) and not isinstance(value, bool)

    def _valid_config(self, admission: ExecutionAdmission) -> bool:
        values = (
            admission.max_iterations,
            admission.timeout_seconds,
            admission.context_tokens,
            admission.context_soft_limit,
            admission.context_hard_limit,
        )
        if not all(self._is_int(value) for value in values):
            return False
        if not MIN_ITERATIONS <= admission.max_iterations <= MAX_ITERATIONS:
            return False
        if not MIN_TIMEOUT_SECONDS <= admission.timeout_seconds <= MAX_TIMEOUT_SECONDS:
            return False
        if admission.context_tokens < 0 or admission.context_soft_limit < 0:
            return False
        if admission.context_hard_limit <= admission.context_soft_limit:
            return False
        budget = admission.recommended_api_call_budget
        return budget is None or (self._is_int(budget) and budget >= 0)
