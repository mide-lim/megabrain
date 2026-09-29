"""Pure read-only reconciliation classifier."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ExpectedResource:
    task_id: str
    resource_id: str
    resource_type: str
    lease_state: str
    expected_identity: dict
    bound_identity: dict | None
    heartbeat_required: bool
    ttl: int | None
    policy_version: str


@dataclass(frozen=True)
class ObservedResource:
    adapter_type: str
    adapter_version: str
    observation: dict
    observed_at: str
    evidence_ref: str


@dataclass(frozen=True)
class ReconciliationResult:
    result: str
    expected_resource_id: str | None
    evidence_refs: tuple[str, ...]
    blocking_reason: dict | None = None
    next_permitted_action: dict | None = None


def reconcile(expected: ExpectedResource, observed: ObservedResource) -> ReconciliationResult:
    status = observed.observation.get("status", "INCONCLUSIVE")
    if status == "MATCHED": return ReconciliationResult("MATCHED", expected.resource_id, (observed.evidence_ref,))
    if status == "MISSING": return ReconciliationResult("MISSING_RUNTIME", expected.resource_id, (observed.evidence_ref,), {"code": "MISSING_RUNTIME"})
    if status == "UNKNOWN": return ReconciliationResult("UNKNOWN_RUNTIME", expected.resource_id, (observed.evidence_ref,), {"code": "UNKNOWN_RUNTIME"})
    if status == "IDENTITY_MISMATCH": return ReconciliationResult("IDENTITY_MISMATCH", expected.resource_id, (observed.evidence_ref,), {"code": "IDENTITY_MISMATCH"})
    if status == "ACCESS_DENIED": return ReconciliationResult("INCONCLUSIVE", expected.resource_id, (observed.evidence_ref,), {"code": "ADAPTER_UNAVAILABLE"})
    return ReconciliationResult("INCONCLUSIVE", expected.resource_id, (observed.evidence_ref,), {"code": "OBSERVATION_INCONCLUSIVE"})


def reconcile_unknown(observed: ObservedResource) -> ReconciliationResult:
    """Classify discovered evidence without fabricating a lease or Task."""
    return ReconciliationResult("UNOWNED_UNKNOWN", None, (observed.evidence_ref,), {"code": "UNOWNED_UNKNOWN"})
