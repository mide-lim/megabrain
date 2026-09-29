"""Hermetic AP0 request fixtures shared by acceptance tests."""
from __future__ import annotations

from app.policy import POLICY_VERSION

CORR = "corr_018f3d4a-7b8c-7c9d-8e1f-0123456789ab"
CORR2 = "corr_018f3d4a-7b8c-7c9d-8e1f-0123456789ac"
HERMES = {"role": "HERMES_COORDINATOR", "identity_id": "hermes"}
MANAGER = {"role": "WORKER_MANAGER", "identity_id": "manager"}
HUMAN = {"role": "HUMAN_GATE_ADAPTER", "identity_id": "human"}
OBSERVER = {"role": "OBSERVABILITY_ADAPTER", "identity_id": "observer"}


def identity(kind, value):
    return {"identity_type": kind, "identity_id": value}


def task_body(*, operations=None, workers=1):
    return {
        "created_by": identity("AGENT", "hermes"),
        "requested_by": identity("HUMAN", "owner"),
        "allowed_operations": operations if operations is not None else [grant()],
        "resource_budget": {"workers": workers, "processes": 3, "previews": 1, "worktrees": 1, "temporary_bytes": 1024, "artifact_bytes": 1024, "runtime_seconds": 60},
        "prerequisite_status": {},
        "risk_class": "GREEN",
    }


def grant(*, operation="worker.run", target_scope="task-worktree", gate_requirement="NONE"):
    return {"operation": operation, "target_scope": target_scope, "gate_requirement": gate_requirement, "policy_version": POLICY_VERSION}


def requested_operation(*, operation="worker.run", target_scope="task-worktree"):
    return {"operation": operation, "target_scope": target_scope}


def worker_request():
    identity_value = {"pid": 101, "start_time": "100", "boot_id": "boot-a"}
    return {"resource_type": "WORKER", "requested_operation": requested_operation(), "expected_identity": identity_value, "budget_reservation": {}, "metadata": {"command_profile": "test"}, "heartbeat_required": True}


def checkpoint(active_resource_ids=None):
    return {"active_resource_ids": active_resource_ids or [], "pending_validation": [], "evidence_refs": [], "next_permitted_action": requested_operation()}


def ready_task(service, caller=HERMES, *, operations=None):
    created = service.create_task(caller, "create-task", CORR, task_body(operations=operations))
    service.transition_task(caller, "ready-task", CORR2, created["task_id"], 0, "READY")
    return created["task_id"]
