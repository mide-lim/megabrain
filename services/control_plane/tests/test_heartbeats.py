import pytest

from app.errors import ControlPlaneError
from app.service import ControlPlaneService
from helpers import CORR, CORR2, MANAGER, worker_request, ready_task


def test_heartbeat_projection_sequence_and_missed_to_stale_are_non_destructive(tmp_path):
    service = ControlPlaneService(tmp_path / "db.sqlite")
    task_id = ready_task(service, MANAGER)
    resource = service.allocate_resource(MANAGER, "allocation", CORR, task_id, worker_request())
    service.bind_resource(MANAGER, "bind", CORR2, resource["resource_id"], 0, worker_request()["expected_identity"])
    assert service.record_heartbeat(MANAGER, "heartbeat", CORR, task_id, resource["resource_id"], 1)["sequence"] == 1
    with pytest.raises(ControlPlaneError, match="INVALID_REQUEST"):
        service.record_heartbeat(MANAGER, "duplicate", CORR2, task_id, resource["resource_id"], 1)
    last = service.con.execute("SELECT last_heartbeat FROM resource_leases WHERE resource_id=?", (resource["resource_id"],)).fetchone()[0]
    date, clock = last.split("T"); second = int(clock[6:8]); at_90 = f"{date}T{clock[:6]}{(second + 91) % 60:02d}.000Z"
    # A deterministic direct SQL timestamp avoids any host/runtime observation.
    service.con.execute("UPDATE resource_leases SET last_heartbeat='2026-09-29T00:00:00.000Z' WHERE resource_id=?", (resource["resource_id"],))
    assert resource["resource_id"] in service.evaluate_heartbeats(MANAGER, CORR2, "2026-09-29T00:01:31.000Z")
    assert service.get_task_resources(task_id)[0]["state"] == "HEARTBEAT_MISSED"
    service.evaluate_heartbeats(MANAGER, CORR, "2026-09-29T00:02:31.000Z")
    assert service.get_task_resources(task_id)[0]["state"] == "STALE_CANDIDATE"
    service.close()
