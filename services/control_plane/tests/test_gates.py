import pytest

from app.errors import ControlPlaneError
from app.service import ControlPlaneService
from helpers import CORR, CORR2, HERMES, HUMAN, MANAGER, requested_operation, task_body, worker_request


def test_gate_approval_binds_exact_scope_expires_and_is_single_use(tmp_path):
    service = ControlPlaneService(tmp_path / "db.sqlite")
    task_id = service.create_task(HERMES, "create", CORR, task_body())["task_id"]
    operation = requested_operation(operation="release.review", target_scope="pr:42")
    gate = service.create_gate(HERMES, "gate", CORR2, task_id, {"requested_operation": operation, "required_authority": {"kind": "OWNER"}})
    service.resolve_gate(HUMAN, "approve", CORR, gate["gate_id"], 0, True, "approval:42", "2099-01-01T00:00:00.000Z")
    with pytest.raises(ControlPlaneError, match="INVALID_STATE_TRANSITION"):
        service.consume_gate(HERMES, "wrong-scope", CORR2, gate["gate_id"], 1, requested_operation(operation="release.review", target_scope="pr:43"))
    assert service.consume_gate(HERMES, "consume", CORR, gate["gate_id"], 1, operation)["status"] == "CONSUMED"
    with pytest.raises(ControlPlaneError, match="GATE_ALREADY_CONSUMED"):
        service.consume_gate(HERMES, "reuse", CORR2, gate["gate_id"], 2, operation)
    expired = service.create_gate(HERMES, "expired-gate", CORR, task_id, {"requested_operation": operation, "required_authority": {"kind": "OWNER"}})
    service.resolve_gate(HUMAN, "expired-approve", CORR2, expired["gate_id"], 0, True, "approval:expired", "2097-01-01T00:00:00.000Z")
    with pytest.raises(ControlPlaneError, match="GATE_EXPIRED"):
        service.consume_gate(HERMES, "expired-consume", CORR, expired["gate_id"], 1, operation, now="2097-01-01T00:00:00.000Z")
    service.close()


def test_gate_cannot_bind_resource_owned_by_another_task(tmp_path):
    service = ControlPlaneService(tmp_path / "db.sqlite")
    first = service.create_task(HERMES, "task-one", CORR, task_body())
    service.transition_task(HERMES, "task-one-ready", CORR2, first["task_id"], 0, "READY")
    resource = service.allocate_resource(MANAGER, "task-one-worker", CORR, first["task_id"], worker_request())
    second = service.create_task(HERMES, "task-two", CORR2, task_body())
    operation = requested_operation(operation="release.review", target_scope="pr:77")
    with pytest.raises(ControlPlaneError, match="UNAUTHORIZED"):
        service.create_gate(HERMES, "cross-task-gate", CORR, second["task_id"], {"resource_id": resource["resource_id"], "requested_operation": operation, "required_authority": {"kind": "OWNER"}})
    service.close()
