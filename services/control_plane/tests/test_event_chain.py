from app.service import ControlPlaneService
from helpers import CORR, CORR2, HERMES, requested_operation, task_body


def test_read_models_pending_gate_filter_and_append_event_boundary(tmp_path):
    service = ControlPlaneService(tmp_path / "db.sqlite")
    task_id = service.create_task(HERMES, "create", CORR, task_body())["task_id"]
    gate = service.create_gate(HERMES, "gate", CORR2, task_id, {"requested_operation": requested_operation(operation="review", target_scope="pr"), "required_authority": {"kind": "OWNER"}})
    assert service.get_task(task_id)["state"] == "CREATED"
    assert service.get_task_resources(task_id) == []
    assert [item["gate_id"] for item in service.get_pending_gates(task_id)] == [gate["gate_id"]]
    event = service.append_event(HERMES, "append", CORR, task_id, None, "REVIEW_EVIDENCE", {"evidence_ref": "test:1"})
    assert event["event_id"].startswith("evt_")
    service.close()
