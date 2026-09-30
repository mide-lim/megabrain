import pytest
import threading

from app.errors import ControlPlaneError
from app.service import ControlPlaneService
from helpers import CORR, CORR2, HERMES, HUMAN, MANAGER, HermeticWorkerIdentityVerifier, WORKER_LAUNCH_NONCE, grant, ready_task, worker_observation, worker_request


def test_allocation_binds_strong_identity_tracks_event_sequence_and_releases_failed_reservation(tmp_path):
    service = ControlPlaneService(tmp_path / "db.sqlite", worker_identity_verifier=HermeticWorkerIdentityVerifier())
    task_id = ready_task(service, MANAGER)
    request = worker_request()
    allocated = service.allocate_resource(MANAGER, "allocation", CORR, task_id, request)
    resource_id = allocated["resource_id"]
    row = service.con.execute("SELECT last_event_sequence FROM resource_leases WHERE resource_id=?", (resource_id,)).fetchone()
    assert row[0] > 0
    bad_observation = worker_observation(); bad_observation["boot_id"] = "018f3d4a-7b8c-7c9d-8e1f-0123456789ac"
    with pytest.raises(ControlPlaneError, match="IDENTITY_MISMATCH"):
        service.bind_resource(MANAGER, "bad-bind", CORR2, resource_id, 0, bad_observation, WORKER_LAUNCH_NONCE)
    assert service.bind_resource(MANAGER, "bind", CORR2, resource_id, 0, worker_observation(), WORKER_LAUNCH_NONCE)["state"] == "ACTIVE"
    with pytest.raises(ControlPlaneError, match="BUDGET_EXCEEDED|RESOURCE_LIMIT_REACHED"):
        service.allocate_resource(MANAGER, "second", CORR, task_id, request)
    assert service.terminalize_resource(MANAGER, "terminal", CORR2, resource_id, 1, {"code": "RESOURCE_CREATION_FAILED"})["state"] == "TERMINAL"
    replacement = service.allocate_resource(MANAGER, "replacement", CORR, task_id, request)
    assert replacement["state"] == "ALLOCATED"
    service.close()


def test_allocation_rejects_ungranted_operation_and_public_preview(tmp_path):
    service = ControlPlaneService(tmp_path / "db.sqlite")
    task_id = ready_task(service, MANAGER, operations=[])
    with pytest.raises(ControlPlaneError, match="UNAUTHORIZED"):
        service.allocate_resource(MANAGER, "ungranted", CORR, task_id, worker_request())
    service.close()


def test_gated_allocation_consumes_approval_atomically_and_cannot_reuse_it(tmp_path):
    service = ControlPlaneService(tmp_path / "db.sqlite")
    task_id = ready_task(service, MANAGER, operations=[grant(gate_requirement="REQUIRED")])
    request = worker_request(); operation = request["requested_operation"]
    gate = service.create_gate(HERMES, "gate-for-worker", CORR, task_id, {"requested_operation": operation, "required_authority": {"kind": "OWNER"}})
    service.resolve_gate(HUMAN, "approve-worker", CORR2, gate["gate_id"], 0, True, "approval:worker", "2099-01-01T00:00:00.000Z")
    request["gate_id"] = gate["gate_id"]
    allocated = service.allocate_resource(MANAGER, "gated-allocation", CORR, task_id, request)
    assert service.con.execute("SELECT status FROM gates WHERE gate_id=?", (gate["gate_id"],)).fetchone()[0] == "CONSUMED"
    service.terminalize_resource(MANAGER, "release-gated", CORR2, allocated["resource_id"], 0, {"code": "RESOURCE_CREATION_FAILED"})
    with pytest.raises(ControlPlaneError, match="GATE_ALREADY_CONSUMED"):
        service.allocate_resource(MANAGER, "reuse-gate", CORR2, task_id, request)
    service.close()


def test_duplicate_resource_replays_and_budget_race_commits_at_most_one(tmp_path):
    database = tmp_path / "db.sqlite"; service = ControlPlaneService(database); task_id = ready_task(service, MANAGER)
    first = service.allocate_resource(MANAGER, "duplicate", CORR, task_id, worker_request())
    assert service.allocate_resource(MANAGER, "duplicate", CORR, task_id, worker_request()) == first
    service.terminalize_resource(MANAGER, "release", CORR2, first["resource_id"], 0, {"code": "RESOURCE_CREATION_FAILED"}); service.close()
    outcomes = []
    def allocate(key):
        instance = ControlPlaneService(database)
        try: outcomes.append(("ok", instance.allocate_resource(MANAGER, key, CORR, task_id, worker_request())))
        except ControlPlaneError as exc: outcomes.append(("error", exc.code))
        finally: instance.close()
    threads = [threading.Thread(target=allocate, args=(f"race-{index}",)) for index in range(2)]
    for thread in threads: thread.start()
    for thread in threads: thread.join()
    assert sum(kind == "ok" for kind, _ in outcomes) == 1
    assert {value for kind, value in outcomes if kind == "error"} <= {"BUDGET_EXCEEDED", "RESOURCE_LIMIT_REACHED"}
