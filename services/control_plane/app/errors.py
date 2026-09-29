"""Stable, safe AP0 error envelopes."""
from __future__ import annotations
from dataclasses import dataclass

@dataclass
class ControlPlaneError(Exception):
    code: str
    message: str = "request rejected"
    retryable: bool = False
    details: dict | None = None
    def envelope(self, correlation_id: str, protocol_version: str = "1.0") -> dict:
        return {"protocol_version": protocol_version, "correlation_id": correlation_id,
                "error": {"code": self.code, "message": self.message, "retryable": self.retryable,
                          "details": self.details or {}}}

ERROR_CODES = frozenset({"INVALID_REQUEST","UNSUPPORTED_SCHEMA","UNSUPPORTED_PROTOCOL","UNKNOWN_IDENTITY","UNAUTHORIZED","TASK_NOT_FOUND","RESOURCE_NOT_FOUND","INVALID_STATE_TRANSITION","TASK_BLOCKED","TASK_TERMINAL","GATE_REQUIRED","GATE_DENIED","GATE_EXPIRED","GATE_ALREADY_CONSUMED","BUDGET_EXCEEDED","RESOURCE_LIMIT_REACHED","IDENTITY_BIND_FAILED","IDENTITY_MISMATCH","IDEMPOTENCY_CONFLICT","REGISTRY_UNAVAILABLE","AUDIT_WRITE_FAILED","CHECKPOINT_FAILED","ADAPTER_UNAVAILABLE","OBSERVATION_INCONCLUSIVE","INTERNAL_ERROR"})

def fail(code: str, message: str = "request rejected", retryable: bool = False, **details: object) -> ControlPlaneError:
    if code not in ERROR_CODES: code = "INTERNAL_ERROR"
    return ControlPlaneError(code, message, retryable, dict(details))
