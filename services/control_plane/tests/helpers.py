"""Hermetic AP0 request fixtures shared by acceptance tests."""
from __future__ import annotations

import hashlib

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


WORKER_BOOT_ID = "018f3d4a-7b8c-7c9d-8e1f-0123456789ab"
WORKER_LAUNCH_NONCE = "A" * 43


class HermeticWorkerIdentityVerifier:
    """Explicit test fake; it is injected and never used by production startup."""

    def verify(self, resource_id, expectation, observation):
        return (
            expectation["executable_class"] == "hermetic-worker-v1"
            and observation["executable"] == "/hermetic/bin/worker"
            and observation["cwd"] == expectation["worktree_ref"]
            and observation["parent_pid"] == 1
        )


def worker_expectation(nonce=WORKER_LAUNCH_NONCE):
    return {
        "kind": "WORKER_PROCESS_V1",
        "expected_boot_id": WORKER_BOOT_ID,
        "expected_uid": 1000,
        "executable_class": "hermetic-worker-v1",
        "worktree_ref": "/hermetic/worktrees/task",
        "nonce_sha256": hashlib.sha256(nonce.encode("ascii")).hexdigest(),
    }


def worker_observation():
    return {
        "pid": 101,
        "start_time": "7384921",
        "boot_id": WORKER_BOOT_ID,
        "uid": 1000,
        "parent_pid": 1,
        "process_group": 101,
        "cwd": "/hermetic/worktrees/task",
        "executable": "/hermetic/bin/worker",
        "cgroup": None,
    }


def worker_request():
    return {"resource_type": "WORKER", "requested_operation": requested_operation(), "expected_identity": worker_expectation(), "budget_reservation": {}, "metadata": {"command_profile": "test"}, "heartbeat_required": True}


def checkpoint(active_resource_ids=None):
    return {"active_resource_ids": active_resource_ids or [], "pending_validation": [], "evidence_refs": [], "next_permitted_action": requested_operation()}


def ready_task(service, caller=HERMES, *, operations=None):
    created = service.create_task(caller, "create-task", CORR, task_body(operations=operations))
    service.transition_task(caller, "ready-task", CORR2, created["task_id"], 0, "READY")
    return created["task_id"]
