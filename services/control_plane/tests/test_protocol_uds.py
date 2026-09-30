import os
import socket
import sqlite3
import shutil
import tempfile
import threading
from pathlib import Path

import pytest
from app.auth import HermeticCapabilityIssuer
from app.errors import ControlPlaneError
from app.main import serve
from app.protocol import ALL_OPERATIONS, decode_frame, encode_frame, recv_frame, send_frame, validate_envelope


def test_uds_frame_is_bounded_canonical_and_v1_only():
    payload = {"protocol_version": "1.0", "operation": "GetTask", "correlation_id": "corr_018f3d4a-7b8c-7c9d-8e1f-0123456789ab", "caller": {}, "authorization": {}, "body": {"task_id": "task_018f3d4a-7b8c-7c9d-8e1f-0123456789ab"}}
    assert decode_frame(encode_frame(payload)) == payload
    with pytest.raises(ControlPlaneError): validate_envelope(dict(payload, protocol_version="2.0"))
    with pytest.raises(ControlPlaneError): decode_frame(b"\x00\x00\x00\x02[]")


def _task_body():
    return {"created_by": {"identity_type": "AGENT", "identity_id": "hermes"}, "requested_by": {"identity_type": "HUMAN", "identity_id": "owner"}, "allowed_operations": [], "resource_budget": {"workers": 1, "processes": 3, "previews": 1, "worktrees": 1, "temporary_bytes": 0, "artifact_bytes": 0, "runtime_seconds": 60}, "prerequisite_status": {}}


def _request(operation, caller, authorization, body, *, key=None, revision=None):
    request = {"protocol_version": "1.0", "operation": operation, "correlation_id": "corr_018f3d4a-7b8c-7c9d-8e1f-0123456789ab", "caller": caller, "authorization": authorization, "body": body}
    if key is not None: request["idempotency_key"] = key
    if revision is not None: request["expected_revision"] = revision
    return request


def _uds_round_trip(path, request):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.connect(str(path)); send_frame(client, request); return recv_frame(client)


def _server(tmp_path, name):
    socket_dir = Path(tempfile.mkdtemp(prefix="mb-cp-", dir="/tmp"))
    path = socket_dir / f"{name}.sock"
    database = tmp_path / "registry.db"; issuer = HermeticCapabilityIssuer(); stop = threading.Event(); ready = threading.Event()
    thread = threading.Thread(target=serve, args=(path, database), kwargs={"issuer": issuer, "stop_event": stop, "ready_event": ready}, daemon=True); thread.start(); assert ready.wait(2)
    return path, database, issuer, stop, thread


def _stop_server(path, stop, thread):
    stop.set()
    thread.join(2)
    shutil.rmtree(path.parent, ignore_errors=True)


def test_uds_dispatches_authenticated_create_task_and_denies_wrong_role(tmp_path):
    path, _, issuer, stop, thread = _server(tmp_path, "create")
    try:
        hermes = {"role": "HERMES_COORDINATOR", "identity_id": "hermes"}
        capability = issuer.issue("cap-create", "HERMES_COORDINATOR", "hermes", ["CreateTask"], "2099-01-01T00:00:00.000Z")
        created = _uds_round_trip(path, _request("CreateTask", hermes, capability, _task_body(), key="create-task"))
        assert created["result"]["task_id"].startswith("task_")
        denied = _uds_round_trip(path, _request("AllocateResource", hermes, capability, {"task_id": created["result"]["task_id"], "resource_type": "WORKER"}, key="wrong-role"))
        assert denied["error"]["code"] == "UNAUTHORIZED"
    finally:
        _stop_server(path, stop, thread)


def test_uds_dispatch_scopes_read_to_the_capability_task(tmp_path):
    path, _, issuer, stop, thread = _server(tmp_path, "read")
    try:
        hermes = {"role": "HERMES_COORDINATOR", "identity_id": "hermes"}
        create = issuer.issue("cap-create", "HERMES_COORDINATOR", "hermes", ["CreateTask"], "2099-01-01T00:00:00.000Z")
        task_id = _uds_round_trip(path, _request("CreateTask", hermes, create, _task_body(), key="create"))["result"]["task_id"]
        read = issuer.issue("cap-read", "HERMES_COORDINATOR", "hermes", ["GetTask"], "2099-01-01T00:00:00.000Z", task_id=task_id)
        assert _uds_round_trip(path, _request("GetTask", hermes, read, {"task_id": task_id}))["result"]["task_id"] == task_id
        denied = _uds_round_trip(path, _request("GetTask", hermes, read, {"task_id": "task_018f3d4a-7b8c-7c9d-8e1f-0123456789ac"}))
        assert denied["error"]["code"] == "UNAUTHORIZED"
    finally:
        _stop_server(path, stop, thread)


def test_v1_protocol_exposes_named_operations_and_never_persists_capability_proofs(tmp_path):
    assert ALL_OPERATIONS == {"CreateTask", "GetTask", "TransitionTask", "PauseTask", "ResumeTask", "CreateCheckpoint", "AllocateResource", "BindResourceIdentity", "MarkResourceTerminal", "RecordHeartbeat", "CreateGate", "ResolveGate", "ConsumeGate", "AppendEvent", "GetTaskResources", "GetPendingGates", "ReconcileObservation", "GetExecutionBudget", "AdmitModelCall", "ReserveDelegation", "ReleaseDelegation", "ReserveReviewBudget", "RecordProviderObservation", "EvaluateProviderPreflight", "ReserveTransientRetry", "ExchangeCoordinatorBootstrap"}
    path, database, issuer, stop, thread = _server(tmp_path, "proof")
    proof = None
    try:
        unknown = {"role": "HERMES_COORDINATOR", "identity_id": "not-provisioned"}; unknown_cap = issuer.issue("unknown", "HERMES_COORDINATOR", "not-provisioned", ["CreateTask"], "2099-01-01T00:00:00.000Z")
        assert _uds_round_trip(path, _request("CreateTask", unknown, unknown_cap, _task_body(), key="unknown"))["error"]["code"] == "UNKNOWN_IDENTITY"
        hermes = {"role": "HERMES_COORDINATOR", "identity_id": "hermes"}; capability = issuer.issue("proof-id", "HERMES_COORDINATOR", "hermes", ["CreateTask"], "2099-01-01T00:00:00.000Z")
        proof = capability["capability_proof"]
        assert "result" in _uds_round_trip(path, _request("CreateTask", hermes, capability, _task_body(), key="proof"))
    finally:
        _stop_server(path, stop, thread)
    dump = "\n".join(row[0] for row in sqlite3.connect(database).iterdump())
    assert proof not in dump and "capability_proof" not in dump


def test_uds_refuses_startup_without_explicit_capability_issuer(tmp_path):
    path = tmp_path / "no-issuer.sock"
    with pytest.raises(ControlPlaneError, match="UNAUTHORIZED"):
        serve(path, tmp_path / "registry.db")
    assert not path.exists()


def test_uds_refuses_to_unlink_preexisting_socket_path(tmp_path):
    path = tmp_path / "existing.sock"
    path.write_text("sentinel")
    with pytest.raises(ControlPlaneError, match="REGISTRY_UNAVAILABLE"):
        serve(path, tmp_path / "registry.db", issuer=HermeticCapabilityIssuer())
    assert path.read_text() == "sentinel"
