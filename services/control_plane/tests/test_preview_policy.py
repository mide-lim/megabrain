import pytest

from app.errors import ControlPlaneError
from app.policy import preview_allowed
from app.service import ControlPlaneService
from helpers import CORR, MANAGER, grant, task_body


def test_preview_policy_denies_public_and_registry_collision_is_not_adopted(tmp_path):
    valid = {"bind_address": "127.0.0.1", "port": 38000, "launcher_capability_class": "SOCKET_ACTIVATION"}
    assert preview_allowed(valid)
    assert not preview_allowed({**valid, "bind_address": "0.0.0.0"})
    service = ControlPlaneService(tmp_path / "db.sqlite")
    body = task_body(operations=[grant(operation="preview.launch", target_scope="task-worktree")]); body["resource_budget"]["previews"] = 2
    task_id = service.create_task(MANAGER, "create-preview-task", CORR, body)["task_id"]
    service.transition_task(MANAGER, "ready-preview-task", CORR, task_id, 0, "READY")
    request = {"resource_type": "PREVIEW", "requested_operation": {"operation": "preview.launch", "target_scope": "task-worktree"}, "expected_identity": {"listener": "pending"}, "metadata": valid, "budget_reservation": {}, "ttl_seconds": 60}
    first = service.allocate_resource(MANAGER, "first-preview", CORR, task_id, request)
    with pytest.raises(ControlPlaneError, match="RESOURCE_LIMIT_REACHED|AUDIT_WRITE_FAILED"):
        service.allocate_resource(MANAGER, "collision", CORR, task_id, request)
    assert service.get_task_resources(task_id)[0]["resource_id"] == first["resource_id"]
    service.close()
