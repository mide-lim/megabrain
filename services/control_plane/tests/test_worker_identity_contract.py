import hashlib

import pytest

from app.auth import HermeticCapabilityIssuer
from app.errors import ControlPlaneError
from app.main import dispatch_request
from app.service import ControlPlaneService
from app.worker_identity import matches_launch_expectation
from helpers import CORR, CORR2, MANAGER, ready_task


BOOT_ID = "018f3d4a-7b8c-7c9d-8e1f-0123456789ab"
FAKE_LAUNCH_NONCE = "FAKE_TC8B_LAUNCH_NONCE_SENTINEL_" + ("A" * 32)


class HermeticWorkerIdentityVerifier:
    """Explicit test-only verifier; production must inject its own verifier."""

    def __init__(self):
        self.calls = []

    def verify(self, resource_id, expectation, observation):
        self.calls.append((resource_id, expectation, observation))
        return (
            expectation["executable_class"] == "hermetic-worker-v1"
            and observation["executable"] == "/hermetic/bin/worker"
            and observation["cwd"] == expectation["worktree_ref"]
            and observation["parent_pid"] == 1
        )


def launch_nonce():
    return FAKE_LAUNCH_NONCE


def expectation(nonce):
    return {
        "kind": "WORKER_PROCESS_V1",
        "expected_boot_id": BOOT_ID,
        "expected_uid": 1000,
        "executable_class": "hermetic-worker-v1",
        "worktree_ref": "/hermetic/worktrees/task",
        "nonce_sha256": hashlib.sha256(nonce.encode("ascii")).hexdigest(),
    }


def observation():
    return {
        "pid": 101,
        "start_time": "7384921",
        "boot_id": BOOT_ID,
        "uid": 1000,
        "parent_pid": 1,
        "process_group": 101,
        "cwd": "/hermetic/worktrees/task",
        "executable": "/hermetic/bin/worker",
        "cgroup": None,
    }


def worker_request(nonce):
    return {
        "resource_type": "WORKER",
        "requested_operation": {"operation": "worker.run", "target_scope": "task-worktree"},
        "expected_identity": expectation(nonce),
        "budget_reservation": {},
        "metadata": {"command_profile": "test"},
        "heartbeat_required": True,
    }


def test_worker_allocation_commits_typed_pre_spawn_expectation_idempotently_without_raw_nonce(tmp_path):
    nonce = launch_nonce()
    service = ControlPlaneService(tmp_path / "db.sqlite")
    task_id = ready_task(service, MANAGER)

    first = service.allocate_resource(MANAGER, "worker-allocation", CORR, task_id, worker_request(nonce))
    replay = service.allocate_resource(MANAGER, "worker-allocation", CORR, task_id, worker_request(nonce))

    assert replay == first
    assert service.con.execute("SELECT count(*) FROM resource_leases").fetchone()[0] == 1
    lease = service.get_task_resources(task_id)[0]
    assert lease["state"] == "ALLOCATED"
    assert lease["expected_identity"] == expectation(nonce)
    assert "pid" not in lease["expected_identity"]
    dump = "\n".join(row[0] for row in service.con.iterdump())
    assert nonce not in dump
    assert "launch_nonce" not in dump
    service.close()


def test_worker_allocation_rejects_guessed_process_identity_and_raw_nonce_in_expectation(tmp_path):
    nonce = launch_nonce()
    service = ControlPlaneService(tmp_path / "db.sqlite")
    task_id = ready_task(service, MANAGER)
    request = worker_request(nonce)
    request["expected_identity"]["pid"] = 101
    request["expected_identity"]["launch_nonce"] = nonce

    with pytest.raises(ControlPlaneError, match="INVALID_REQUEST"):
        service.allocate_resource(MANAGER, "bad-worker-allocation", CORR, task_id, request)
    assert service.con.execute("SELECT count(*) FROM resource_leases").fetchone()[0] == 0

    metadata_nonce = worker_request(nonce)
    metadata_nonce["metadata"]["launch_nonce"] = nonce
    with pytest.raises(ControlPlaneError, match="INVALID_REQUEST"):
        service.allocate_resource(MANAGER, "metadata-nonce", CORR, task_id, metadata_nonce)
    assert service.con.execute("SELECT count(*) FROM resource_leases").fetchone()[0] == 0
    service.close()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("kind", "WORKER_PROCESS_V0"),
        ("expected_boot_id", "not-a-canonical-uuid"),
        ("expected_uid", -1),
        ("nonce_sha256", "ABC123"),
    ],
)
def test_worker_allocation_rejects_malformed_launch_expectation(tmp_path, field, value):
    nonce = launch_nonce()
    service = ControlPlaneService(tmp_path / "db.sqlite")
    task_id = ready_task(service, MANAGER)
    request = worker_request(nonce)
    request["expected_identity"][field] = value
    with pytest.raises(ControlPlaneError, match="INVALID_REQUEST"):
        service.allocate_resource(MANAGER, f"bad-expectation-{field}", CORR, task_id, request)
    assert service.con.execute("SELECT count(*) FROM resource_leases").fetchone()[0] == 0
    service.close()


def test_worker_bind_fails_closed_without_injected_verifier_and_leaves_lease_allocated(tmp_path):
    nonce = launch_nonce()
    service = ControlPlaneService(tmp_path / "db.sqlite")
    task_id = ready_task(service, MANAGER)
    allocated = service.allocate_resource(MANAGER, "worker-allocation", CORR, task_id, worker_request(nonce))

    with pytest.raises(ControlPlaneError, match="IDENTITY_BIND_FAILED"):
        service.bind_resource(MANAGER, "worker-bind", CORR2, allocated["resource_id"], 0, observation(), nonce)

    assert service.get_task_resources(task_id)[0]["state"] == "ALLOCATED"
    service.close()


def test_worker_bind_requires_strong_observation_nonce_match_and_explicit_verifier(tmp_path):
    nonce = launch_nonce()
    verifier = HermeticWorkerIdentityVerifier()
    service = ControlPlaneService(tmp_path / "db.sqlite", worker_identity_verifier=verifier)
    task_id = ready_task(service, MANAGER)
    allocated = service.allocate_resource(MANAGER, "worker-allocation", CORR, task_id, worker_request(nonce))

    result = service.bind_resource(MANAGER, "worker-bind", CORR2, allocated["resource_id"], 0, observation(), nonce)
    replay = service.bind_resource(MANAGER, "worker-bind", CORR2, allocated["resource_id"], 0, observation(), nonce)

    assert result["state"] == "ACTIVE"
    assert replay == result
    assert verifier.calls and verifier.calls[0][0] == allocated["resource_id"]
    lease = service.get_task_resources(task_id)[0]
    assert lease["bound_identity"] == observation()
    dump = "\n".join(row[0] for row in service.con.iterdump())
    assert nonce not in dump
    assert "launch_nonce" not in dump
    service.close()


def test_worker_bind_rejects_bad_nonce_or_missing_strong_identity_without_partial_bind(tmp_path):
    nonce = launch_nonce()
    verifier = HermeticWorkerIdentityVerifier()
    service = ControlPlaneService(tmp_path / "db.sqlite", worker_identity_verifier=verifier)
    task_id = ready_task(service, MANAGER)
    allocated = service.allocate_resource(MANAGER, "worker-allocation", CORR, task_id, worker_request(nonce))

    with pytest.raises(ControlPlaneError, match="IDENTITY_MISMATCH"):
        service.bind_resource(MANAGER, "wrong-nonce", CORR2, allocated["resource_id"], 0, observation(), "B" * 43)
    assert service.get_task_resources(task_id)[0]["state"] == "ALLOCATED"

    wrong_uid = observation()
    wrong_uid["uid"] = 1001
    with pytest.raises(ControlPlaneError, match="IDENTITY_MISMATCH"):
        service.bind_resource(MANAGER, "wrong-uid", CORR2, allocated["resource_id"], 0, wrong_uid, nonce)

    incomplete = observation()
    incomplete.pop("start_time")
    with pytest.raises(ControlPlaneError, match="INVALID_REQUEST"):
        service.bind_resource(MANAGER, "missing-start", CORR2, allocated["resource_id"], 0, incomplete, nonce)

    missing_boot = observation()
    missing_boot.pop("boot_id")
    with pytest.raises(ControlPlaneError, match="INVALID_REQUEST"):
        service.bind_resource(MANAGER, "missing-boot", CORR2, allocated["resource_id"], 0, missing_boot, nonce)
    with pytest.raises(ControlPlaneError, match="INVALID_REQUEST"):
        service.bind_resource(MANAGER, "pid-only", CORR2, allocated["resource_id"], 0, {"pid": 101}, nonce)
    assert service.get_task_resources(task_id)[0]["state"] == "ALLOCATED"

    unknown_field = observation()
    unknown_field["ignored"] = "must-not-be-discarded"
    with pytest.raises(ControlPlaneError, match="INVALID_REQUEST"):
        service.bind_resource(MANAGER, "unknown-field", CORR2, allocated["resource_id"], 0, unknown_field, nonce)
    with pytest.raises(ControlPlaneError, match="INVALID_REQUEST"):
        service.bind_resource(MANAGER, "short-nonce", CORR2, allocated["resource_id"], 0, observation(), "A" * 42)

    unverified = observation()
    unverified["executable"] = "/untrusted/bin/worker"
    with pytest.raises(ControlPlaneError, match="IDENTITY_MISMATCH"):
        service.bind_resource(MANAGER, "verifier-mismatch", CORR2, allocated["resource_id"], 0, unverified, nonce)
    assert service.get_task_resources(task_id)[0]["state"] == "ALLOCATED"
    service.close()


def test_non_worker_process_binding_keeps_existing_exact_identity_semantics(tmp_path):
    service = ControlPlaneService(tmp_path / "db.sqlite")
    task_id = ready_task(service, MANAGER)
    identity = {"pid": 202, "start_time": "500", "boot_id": BOOT_ID}
    request = {
        "resource_type": "PROCESS",
        "requested_operation": {"operation": "worker.run", "target_scope": "task-worktree"},
        "expected_identity": identity,
        "budget_reservation": {},
        "metadata": {},
    }
    allocated = service.allocate_resource(MANAGER, "process-allocation", CORR, task_id, request)
    assert service.bind_resource(MANAGER, "process-bind", CORR2, allocated["resource_id"], 0, identity)["state"] == "ACTIVE"
    service.close()


def test_matcher_requires_boot_uid_nonce_and_verified_evidence():
    nonce = launch_nonce()
    assert matches_launch_expectation(expectation(nonce), observation(), nonce, True)
    assert not matches_launch_expectation(expectation(nonce), observation(), nonce, False)

    wrong_boot = observation()
    wrong_boot["boot_id"] = "018f3d4a-7b8c-7c9d-8e1f-0123456789ac"
    assert not matches_launch_expectation(expectation(nonce), wrong_boot, nonce, True)

    wrong_uid = observation()
    wrong_uid["uid"] = 1001
    assert not matches_launch_expectation(expectation(nonce), wrong_uid, nonce, True)


def test_protocol_dispatch_passes_transient_worker_nonce_without_persisting_it(tmp_path):
    nonce = launch_nonce()
    issuer = HermeticCapabilityIssuer()
    service = ControlPlaneService(tmp_path / "db.sqlite", worker_identity_verifier=HermeticWorkerIdentityVerifier())
    task_id = ready_task(service, MANAGER)
    allocated = service.allocate_resource(MANAGER, "worker-allocation", CORR, task_id, worker_request(nonce))
    capability = issuer.issue("worker-bind", "WORKER_MANAGER", "manager", ["BindResourceIdentity"], "2099-01-01T00:00:00.000Z", task_id=task_id, resource_id=allocated["resource_id"])

    result = dispatch_request(service, {
        "operation": "BindResourceIdentity",
        "body": {"resource_id": allocated["resource_id"], "identity": observation(), "launch_nonce": nonce},
        "caller": MANAGER,
        "authorization": capability,
        "idempotency_key": "worker-bind",
        "correlation_id": CORR2,
        "expected_revision": 0,
    }, issuer)

    assert result["state"] == "ACTIVE"
    dump = "\n".join(row[0] for row in service.con.iterdump())
    assert nonce not in dump and "launch_nonce" not in dump
    service.close()
