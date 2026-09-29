import pytest

from app.auth import HermeticCapabilityIssuer, authorize
from app.errors import ControlPlaneError
from helpers import CORR, HERMES, MANAGER


def test_role_capability_target_and_expiry_fail_closed():
    issuer = HermeticCapabilityIssuer()
    task_id = "task_018f3d4a-7b8c-7c9d-8e1f-0123456789ab"
    resource_id = "rsrc_018f3d4a-7b8c-7c9d-8e1f-0123456789ab"
    worker = {"role": "WORKER", "identity_id": "worker"}
    capability = issuer.issue("worker-heartbeat", "WORKER", "worker", ["RecordHeartbeat"], "2099-01-01T00:00:00.000Z", task_id, resource_id)
    authorize(worker, capability, "RecordHeartbeat", task_id, resource_id, issuer)
    with pytest.raises(ControlPlaneError, match="UNAUTHORIZED"):
        authorize(worker, capability, "RecordHeartbeat", task_id, None, issuer)
    with pytest.raises(ControlPlaneError, match="UNAUTHORIZED"):
        authorize(MANAGER, capability, "AllocateResource", task_id, issuer=issuer)
    expired = issuer.issue("expired", "HERMES_COORDINATOR", "hermes", ["CreateTask"], "2020-01-01T00:00:00.000Z")
    with pytest.raises(ControlPlaneError, match="UNAUTHORIZED"):
        authorize(HERMES, expired, "CreateTask", issuer=issuer)
