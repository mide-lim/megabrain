import pytest

from app.errors import ControlPlaneError
from app.service import ControlPlaneService
from helpers import CORR, CORR2, HERMES, task_body


def test_task_state_is_revisioned_terminal_shape_is_required_and_scope_is_immutable(tmp_path):
    service = ControlPlaneService(tmp_path / "db.sqlite")
    created = service.create_task(HERMES, "create", CORR, task_body())
    task_id = created["task_id"]
    assert service.transition_task(HERMES, "ready", CORR2, task_id, 0, "READY")["revision"] == 1
    with pytest.raises(ControlPlaneError, match="INVALID_STATE_TRANSITION"):
        service.transition_task(HERMES, "stale", CORR, task_id, 0, "RUNNING")
    with pytest.raises(ControlPlaneError, match="INVALID_REQUEST"):
        service.transition_task(HERMES, "bad-terminal", CORR, task_id, 1, "TERMINAL", {"code": "DONE"})
    assert service.transition_task(HERMES, "terminal", CORR, task_id, 1, "TERMINAL", {"outcome": "SUCCEEDED", "summary_ref": "evidence:1"})["state"] == "TERMINAL"
    with pytest.raises(ControlPlaneError, match="TASK_TERMINAL_IMMUTABLE|INVALID_STATE_TRANSITION"):
        service.transition_task(HERMES, "after-terminal", CORR2, task_id, 2, "READY")
    service.close()
