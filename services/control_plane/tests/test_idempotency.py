import pytest

from app.errors import ControlPlaneError
from app.service import ControlPlaneService
from helpers import CORR, HERMES, task_body


def test_idempotency_replays_only_exact_same_request_and_scope(tmp_path):
    service = ControlPlaneService(tmp_path / "db.sqlite")
    body = task_body()
    first = service.create_task(HERMES, "same", CORR, body, capability_id="cap-a")
    assert service.create_task(HERMES, "same", CORR, body, capability_id="cap-a") == first
    assert service.con.execute("SELECT count(*) FROM tasks").fetchone()[0] == 1
    with pytest.raises(ControlPlaneError, match="IDEMPOTENCY_CONFLICT"):
        service.create_task(HERMES, "same", CORR, body, capability_id="cap-b")
    with pytest.raises(ControlPlaneError, match="IDEMPOTENCY_CONFLICT"):
        service.create_task(HERMES, "same", CORR, task_body(workers=0), capability_id="cap-a")
    service.close()
