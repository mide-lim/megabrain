"""Role/scope validation plus a hermetic HMAC capability issuer for tests only."""
from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime

from .errors import fail
from .models import canonical_json, validate_timestamp

ROLE_OPS = {
    "HERMES_COORDINATOR": {"CreateTask", "GetTask", "TransitionTask", "PauseTask", "ResumeTask", "CreateCheckpoint", "CreateGate", "AppendEvent", "GetTaskResources", "GetPendingGates", "ReconcileObservation", "GetExecutionBudget", "AdmitModelCall", "ReserveDelegation", "ReleaseDelegation", "ReserveReviewBudget", "EvaluateProviderPreflight"},
    "WORKER_MANAGER": {"GetTask", "GetTaskResources", "AllocateResource", "BindResourceIdentity", "MarkResourceTerminal", "RecordHeartbeat", "TransitionTask", "CreateCheckpoint", "ConsumeGate", "AppendEvent", "GetExecutionBudget", "AdmitModelCall", "ReserveDelegation", "ReleaseDelegation", "EvaluateProviderPreflight", "ReserveTransientRetry"},
    "WORKER": {"RecordHeartbeat", "AppendEvent", "MarkResourceTerminal", "GetTask", "GetTaskResources"},
    "REVIEWER": {"GetTask", "GetTaskResources", "GetPendingGates", "AppendEvent", "ReconcileObservation", "GetExecutionBudget", "AdmitModelCall"},
    "JANITOR": {"ReconcileObservation", "AppendEvent"},
    "HUMAN_GATE_ADAPTER": {"GetPendingGates", "ResolveGate"},
    "OBSERVABILITY_ADAPTER": {"ReconcileObservation", "AppendEvent", "RecordProviderObservation"},
}
_REQUIRED_CAPABILITY_FIELDS = {"capability_id", "role", "identity_id", "allowed_operations", "expires_at", "task_id", "resource_id", "nonce", "capability_proof"}
_HERMETIC_IDENTITIES = {"HERMES_COORDINATOR": {"hermes"}, "WORKER_MANAGER": {"manager"}, "WORKER": {"worker"}, "REVIEWER": {"reviewer"}, "JANITOR": {"janitor"}, "HUMAN_GATE_ADAPTER": {"human"}, "OBSERVABILITY_ADAPTER": {"observer"}}


class HermeticCapabilityIssuer:
    """Test-only issuer; it is deliberately not a production issuance endpoint."""
    def __init__(self, secret: bytes = b"ap0-hermetic-test-issuer"):
        self.secret = secret

    def issue(self, capability_id: str, role: str, identity_id: str, operations: list[str], expires_at: str, task_id: str | None = None, resource_id: str | None = None, nonce: str = "n") -> dict:
        payload = {"capability_id": capability_id, "role": role, "identity_id": identity_id, "allowed_operations": operations, "expires_at": expires_at, "task_id": task_id, "resource_id": resource_id, "nonce": nonce}
        payload["capability_proof"] = hmac.new(self.secret, canonical_json(payload).encode(), hashlib.sha256).hexdigest()
        return payload

    def validate(self, capability: dict) -> dict:
        if not isinstance(capability, dict) or set(capability) != _REQUIRED_CAPABILITY_FIELDS:
            raise fail("UNAUTHORIZED", "invalid capability")
        proof = capability["capability_proof"]
        if not isinstance(proof, str) or len(proof) != 64:
            raise fail("UNAUTHORIZED", "invalid capability")
        payload = {key: value for key, value in capability.items() if key != "capability_proof"}
        expected = hmac.new(self.secret, canonical_json(payload).encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(proof, expected):
            raise fail("UNAUTHORIZED", "invalid capability")
        try:
            expires_at = validate_timestamp(payload["expires_at"])
        except (KeyError, ValueError) as exc:
            raise fail("UNAUTHORIZED", "invalid capability expiry") from exc
        if datetime.fromisoformat(expires_at.replace("Z", "+00:00")) <= datetime.now(UTC):
            raise fail("UNAUTHORIZED", "expired capability")
        if not isinstance(payload["capability_id"], str) or not payload["capability_id"] or not isinstance(payload["nonce"], str) or not payload["nonce"] or not isinstance(payload["allowed_operations"], list):
            raise fail("UNAUTHORIZED", "invalid capability")
        return payload


def authorize(caller: dict, capability: dict, operation: str, task_id: str | None = None, resource_id: str | None = None, issuer: HermeticCapabilityIssuer | None = None) -> None:
    if not isinstance(caller, dict):
        raise fail("UNKNOWN_IDENTITY", "unknown caller identity")
    role, identity = caller.get("role"), caller.get("identity_id")
    if role not in ROLE_OPS or not isinstance(identity, str) or not identity or identity not in _HERMETIC_IDENTITIES.get(role, set()):
        raise fail("UNKNOWN_IDENTITY", "unknown caller identity")
    if operation not in ROLE_OPS[role]:
        raise fail("UNAUTHORIZED", "role operation denied")
    cap = (issuer or HermeticCapabilityIssuer()).validate(capability)
    if cap["role"] != role or cap["identity_id"] != identity or operation not in cap["allowed_operations"]:
        raise fail("UNAUTHORIZED", "capability scope denied")
    if cap["task_id"] not in (None, task_id) or cap["resource_id"] not in (None, resource_id):
        raise fail("UNAUTHORIZED", "capability target denied")
    if role == "WORKER" and (not cap["task_id"] or not cap["resource_id"]):
        raise fail("UNAUTHORIZED", "worker capability must bind a task and resource")
