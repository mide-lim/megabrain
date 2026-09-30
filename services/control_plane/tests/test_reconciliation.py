from app.adapters.reconciliation import ExpectedResource, ObservedResource, reconcile, reconcile_unknown
from app.service import ControlPlaneService
from helpers import CORR, CORR2, MANAGER, OBSERVER, HermeticWorkerIdentityVerifier, WORKER_LAUNCH_NONCE, ready_task, worker_observation, worker_request


def test_reconciliation_classifies_pid_reuse_unknown_and_denied_without_runtime_mutation(tmp_path):
    expected = ExpectedResource("t", "r", "PROCESS", "ACTIVE", {"pid": 7, "start_time": "a", "boot_id": "old"}, None, True, None, "1.0.0")
    mismatch = reconcile(expected, ObservedResource("process", "1", {"status": "IDENTITY_MISMATCH"}, "2026-09-29T00:00:00.000Z", "evidence:pid"))
    assert mismatch.result == "IDENTITY_MISMATCH" and mismatch.blocking_reason["code"] == "IDENTITY_MISMATCH"
    assert reconcile_unknown(ObservedResource("process", "1", {"status": "UNKNOWN"}, "2026-09-29T00:00:00.000Z", "evidence:legacy")).result == "UNOWNED_UNKNOWN"
    assert reconcile(expected, ObservedResource("docker", "1", {"status": "ACCESS_DENIED"}, "2026-09-29T00:00:00.000Z", "evidence:denied")).blocking_reason["code"] == "ADAPTER_UNAVAILABLE"
    service = ControlPlaneService(tmp_path / "db.sqlite", worker_identity_verifier=HermeticWorkerIdentityVerifier()); task_id = ready_task(service, MANAGER)
    resource = service.allocate_resource(MANAGER, "allocate", CORR, task_id, worker_request()); service.bind_resource(MANAGER, "bind", CORR2, resource["resource_id"], 0, worker_observation(), WORKER_LAUNCH_NONCE)
    before = service.get_task_resources(task_id)[0]["state"]
    result = service.reconcile_observation(OBSERVER, "reconcile", CORR, resource["resource_id"], "process", "1", {"status": "IDENTITY_MISMATCH"}, "2026-09-29T00:00:00.000Z", "evidence:mismatch")
    assert result["result"] == "IDENTITY_MISMATCH" and service.get_task_resources(task_id)[0]["state"] == before
    service.close()
