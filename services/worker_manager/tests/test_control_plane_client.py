import json
import socket
import struct
import threading
import time

import pytest

from app.control_plane_client import (
    ControlPlaneClient,
    ControlPlaneProtocolError,
    ControlPlaneRemoteError,
    ControlPlaneUnavailableError,
)


CORR = "corr_018f3d4a-7b8c-7c9d-8e1f-0123456789ac"
TASK = "task_018f3d4a-7b8c-7c9d-8e1f-0123456789ab"
CAP = {"capability_id": "opaque-test-capability"}
EXPECTATION = {
    "kind": "WORKER_PROCESS_V1",
    "expected_boot_id": "018f3d4a-7b8c-7c9d-8e1f-0123456789ad",
    "expected_uid": 1000,
    "executable_class": "fake-worker-v1",
    "worktree_ref": "/fake/worktree",
    "nonce_sha256": "a" * 64,
}
OPERATION = {"operation": "worker.run", "target_scope": "task-worktree"}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def serve_once(path, response_factory, *, delay=0.0):
    ready = threading.Event()
    captured = {}

    def run():
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(path))
            server.listen(1)
            ready.set()
            client, _ = server.accept()
            with client:
                header = client.recv(4)
                size = struct.unpack(">I", header)[0]
                raw = bytearray()
                while len(raw) < size:
                    raw.extend(client.recv(size - len(raw)))
                captured["request"] = json.loads(raw.decode())
                if delay:
                    time.sleep(delay)
                response = response_factory(captured["request"])
                if response is not None:
                    encoded = canonical(response)
                    client.sendall(struct.pack(">I", len(encoded)) + encoded)

    thread = threading.Thread(target=run)
    thread.start()
    assert ready.wait(1)
    return thread, captured


def client(path, *, timeout=1.0):
    return ControlPlaneClient(path, connect_timeout_seconds=timeout, request_timeout_seconds=timeout)


def test_allocate_uses_fixed_worker_manager_caller_and_forwarded_capability(tmp_path):
    path = tmp_path / "cp.sock"

    def response(request):
        return {
            "protocol_version": "1.0",
            "correlation_id": request["correlation_id"],
            "result": {"resource_id": "rsrc_one", "revision": 0, "state": "ALLOCATED"},
        }

    thread, captured = serve_once(path, response)
    result = client(path).allocate_worker(
        task_id=TASK,
        correlation_id=CORR,
        capability=CAP,
        idempotency_key="allocate-key",
        requested_operation=OPERATION,
        expectation=EXPECTATION,
    )
    thread.join(1)

    request = captured["request"]
    assert result["state"] == "ALLOCATED"
    assert request["caller"] == {"role": "WORKER_MANAGER", "identity_id": "manager"}
    assert request["authorization"] == CAP
    assert request["operation"] == "AllocateResource"
    assert request["body"]["expected_identity"] == EXPECTATION
    assert "launch_nonce" not in request["body"]


def test_bind_transports_nonce_and_validates_resource_state_and_revision(tmp_path):
    path = tmp_path / "cp.sock"
    nonce = "A" * 43

    def response(request):
        return {
            "protocol_version": "1.0",
            "correlation_id": request["correlation_id"],
            "result": {"resource_id": "rsrc_one", "revision": 1, "state": "ACTIVE"},
        }

    thread, captured = serve_once(path, response)
    result = client(path).bind_worker(
        resource_id="rsrc_one",
        correlation_id=CORR,
        capability=CAP,
        idempotency_key="bind-key",
        expected_revision=0,
        observation={"pid": 1},
        launch_nonce=nonce,
    )
    thread.join(1)

    assert result["state"] == "ACTIVE"
    assert captured["request"]["body"]["launch_nonce"] == nonce
    assert captured["request"]["expected_revision"] == 0


@pytest.mark.parametrize(
    "result",
    [
        {"resource_id": "rsrc_wrong", "revision": 1, "state": "ACTIVE"},
        {"resource_id": "rsrc_one", "revision": 1, "state": "TERMINAL"},
        {"resource_id": "rsrc_one", "revision": 99, "state": "ACTIVE"},
        {"resource_id": "rsrc_one", "state": "ACTIVE"},
    ],
)
def test_unexpected_bind_result_fails_closed(tmp_path, result):
    path = tmp_path / "cp.sock"

    def response(request):
        return {"protocol_version": "1.0", "correlation_id": request["correlation_id"], "result": result}

    thread, _ = serve_once(path, response)
    with pytest.raises(ControlPlaneProtocolError):
        client(path).bind_worker(
            resource_id="rsrc_one",
            correlation_id=CORR,
            capability=CAP,
            idempotency_key="bind-key",
            expected_revision=0,
            observation={"pid": 1},
            launch_nonce="A" * 43,
        )
    thread.join(1)


def test_remote_error_is_typed_and_does_not_fabricate_result(tmp_path):
    path = tmp_path / "cp.sock"

    def response(request):
        return {
            "protocol_version": "1.0",
            "correlation_id": request["correlation_id"],
            "error": {"code": "IDENTITY_BIND_FAILED"},
        }

    thread, _ = serve_once(path, response)
    with pytest.raises(ControlPlaneRemoteError, match="IDENTITY_BIND_FAILED"):
        client(path).bind_worker(
            resource_id="rsrc_one",
            correlation_id=CORR,
            capability=CAP,
            idempotency_key="bind-key",
            expected_revision=0,
            observation={"pid": 1},
            launch_nonce="A" * 43,
        )
    thread.join(1)


def test_request_timeout_is_bounded(tmp_path):
    path = tmp_path / "cp.sock"

    thread, _ = serve_once(path, lambda request: None, delay=0.15)
    with pytest.raises(ControlPlaneUnavailableError):
        client(path, timeout=0.03).allocate_worker(
            task_id=TASK,
            correlation_id=CORR,
            capability=CAP,
            idempotency_key="allocate-key",
            requested_operation=OPERATION,
            expectation=EXPECTATION,
        )
    thread.join(1)


def test_non_socket_target_and_invalid_timeout_are_rejected(tmp_path):
    target = tmp_path / "not-a-socket"
    target.write_text("not a socket")

    with pytest.raises(ControlPlaneUnavailableError):
        client(target).allocate_worker(
            task_id=TASK,
            correlation_id=CORR,
            capability=CAP,
            idempotency_key="allocate-key",
            requested_operation=OPERATION,
            expectation=EXPECTATION,
        )
    with pytest.raises(ValueError):
        ControlPlaneClient("/tmp/control-plane.sock", request_timeout_seconds=31)


def test_terminalization_forwards_revision_and_reason(tmp_path):
    path = tmp_path / "cp.sock"

    def response(request):
        return {
            "protocol_version": "1.0",
            "correlation_id": request["correlation_id"],
            "result": {"resource_id": "rsrc_one", "revision": 2, "state": "TERMINAL"},
        }

    thread, captured = serve_once(path, response)
    result = client(path).terminalize_worker(
        resource_id="rsrc_one",
        correlation_id=CORR,
        capability=CAP,
        idempotency_key="terminal-key",
        expected_revision=1,
        reason={"code": "COMPLETED"},
    )
    thread.join(1)

    assert result["revision"] == 2
    assert captured["request"]["body"]["reason"] == {"code": "COMPLETED"}
    assert captured["request"]["expected_revision"] == 1
