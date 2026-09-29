import pytest

from app.errors import ControlPlaneError
from app.service import ControlPlaneService
from helpers import CORR, CORR2, MANAGER, OBSERVER, checkpoint, ready_task, worker_request


def test_host_reboot_identity_mismatch_blocks_resume_until_strong_match(tmp_path):
    service = ControlPlaneService(tmp_path / "db.sqlite"); task_id = ready_task(service, MANAGER)
    resource = service.allocate_resource(MANAGER, "allocate", CORR, task_id, worker_request()); service.bind_resource(MANAGER, "bind", CORR2, resource["resource_id"], 0, worker_request()["expected_identity"])
    service.transition_task(MANAGER, "running", CORR, task_id, 1, "RUNNING")
    paused = service.pause_task(MANAGER, "pause", CORR2, task_id, 2, {"code": "RECOVERY"}, checkpoint([resource["resource_id"]]))
    service.reconcile_observation(OBSERVER, "reboot-observation", CORR, resource["resource_id"], "process", "1", {"status": "IDENTITY_MISMATCH"}, "2026-09-29T00:00:00.000Z", "evidence:new-boot")
    with pytest.raises(ControlPlaneError, match="TASK_BLOCKED"):
        service.resume_task(MANAGER, "resume-rejected", CORR2, task_id, 3, paused["checkpoint_id"])
    service.reconcile_observation(OBSERVER, "matching-observation", CORR2, resource["resource_id"], "process", "1", {"status": "MATCHED"}, "2026-09-29T00:01:00.000Z", "evidence:strong-match")
    assert service.resume_task(MANAGER, "resume", CORR, task_id, 3, paused["checkpoint_id"])["state"] == "READY"
    service.close()
