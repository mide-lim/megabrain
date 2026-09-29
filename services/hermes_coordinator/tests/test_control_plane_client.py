from __future__ import annotations

import json
import socket
import struct
import tempfile
import threading
import time
import uuid
from pathlib import Path

import pytest

from helpers import SERVICE_ROOT
from control_plane_fixture import CORRELATION_ID, ControlPlaneFixture
from app.control_plane_client import (
    ControlPlaneClient,
    ControlPlaneProtocolError,
    ControlPlaneRemoteError,
    ControlPlaneUnavailableError,
    MAX_REQUEST_BYTES,
)


OPERATIONS = ["GetExecutionBudget", "EvaluateProviderPreflight", "AdmitModelCall"]


def client(fixture: ControlPlaneFixture, **kwargs) -> ControlPlaneClient:
    return ControlPlaneClient(fixture.socket_path, **kwargs)


def test_real_uds_client_uses_three_narrow_operations_and_preserves_correlation(tmp_path) -> None:
    fixture = ControlPlaneFixture(tmp_path)
    try:
        capability = fixture.capability(OPERATIONS)
        instance = client(fixture)

        budget = instance.get_execution_budget(fixture.task_id, CORRELATION_ID, capability)
        preflight = instance.evaluate_provider_preflight(fixture.task_id, CORRELATION_ID, "test-channel", capability)
        admission = instance.admit_model_call(
            fixture.task_id,
            CORRELATION_ID,
            12,
            capability,
            idempotency_key="tc7a2-admit-1",
        )

        assert budget["task_id"] == fixture.task_id
        assert preflight["decision"] == "ADMIT"
        assert admission["decision"] == "ADMIT"
        assert fixture.budget()["model_calls_used"] == 1
    finally:
        fixture.close()


def test_identical_admission_replay_does_not_double_debit_and_changed_body_conflicts(tmp_path) -> None:
    fixture = ControlPlaneFixture(tmp_path)
    try:
        capability = fixture.capability(OPERATIONS)
        instance = client(fixture)
        first = instance.admit_model_call(fixture.task_id, CORRELATION_ID, 7, capability, idempotency_key="same-key")

        assert first == instance.admit_model_call(fixture.task_id, CORRELATION_ID, 7, capability, idempotency_key="same-key")
        assert fixture.budget()["model_calls_used"] == 1
        with pytest.raises(ControlPlaneRemoteError, match="IDEMPOTENCY_CONFLICT"):
            instance.admit_model_call(fixture.task_id, CORRELATION_ID, 8, capability, idempotency_key="same-key")
        assert fixture.budget()["model_calls_used"] == 1
    finally:
        fixture.close()


def test_unavailable_socket_fails_without_network_fallback(tmp_path) -> None:
    instance = ControlPlaneClient(tmp_path / "missing.sock", connect_timeout_seconds=1, request_timeout_seconds=1)

    with pytest.raises(ControlPlaneUnavailableError):
        instance.get_execution_budget(
            "task_018f3d4a-7b8c-7c9d-8e1f-0123456789ab",
            CORRELATION_ID,
            {},
        )


def test_client_rejects_empty_path_and_oversized_request_before_connect(tmp_path) -> None:
    with pytest.raises(ValueError):
        ControlPlaneClient("")

    instance = ControlPlaneClient(tmp_path / "missing.sock")
    with pytest.raises(ControlPlaneProtocolError):
        instance.get_execution_budget(
            "task_018f3d4a-7b8c-7c9d-8e1f-0123456789ab",
            CORRELATION_ID,
            {"padding": "x" * MAX_REQUEST_BYTES},
        )


def _fake_peer(tmp_path, payload: bytes | None, *, hold_open: bool = False):
    path = Path(tempfile.gettempdir()) / f"peer-{uuid.uuid4().hex[:16]}.sock"
    ready = threading.Event()

    def serve() -> None:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(path))
            server.listen(1)
            ready.set()
            with server.accept()[0] as conn:
                conn.recv(4096)
                if hold_open:
                    time.sleep(0.3)
                elif payload is not None:
                    conn.sendall(payload)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    assert ready.wait(1)
    return path, thread


@pytest.mark.parametrize(
    "payload",
    [
        struct.pack(">I", 1024 * 1024 + 1),
        struct.pack(">I", 8) + b"{}",
        struct.pack(">I", 4) + b"nope",
        struct.pack(">I", 3) + b"[] ",
    ],
)
def test_malformed_or_invalid_uds_response_fails_closed(tmp_path, payload) -> None:
    path, thread = _fake_peer(tmp_path, payload)
    instance = ControlPlaneClient(path, connect_timeout_seconds=1, request_timeout_seconds=1)

    with pytest.raises(ControlPlaneProtocolError):
        instance.get_execution_budget("task_018f3d4a-7b8c-7c9d-8e1f-0123456789ab", CORRELATION_ID, {})
    thread.join(1)


def test_timeout_and_unexpected_response_task_id_fail_closed(tmp_path) -> None:
    path, thread = _fake_peer(tmp_path, None, hold_open=True)
    instance = ControlPlaneClient(path, connect_timeout_seconds=1, request_timeout_seconds=0.1)
    with pytest.raises(ControlPlaneUnavailableError):
        instance.get_execution_budget("task_018f3d4a-7b8c-7c9d-8e1f-0123456789ab", CORRELATION_ID, {})
    thread.join(1)

    mismatch = {
        "correlation_id": CORRELATION_ID,
        "protocol_version": "1.0",
        "result": {"task_id": "task_018f3d4a-7b8c-7c9d-8e1f-0123456789ac"},
    }
    encoded = json.dumps(mismatch, sort_keys=True, separators=(",", ":")).encode()
    path, thread = _fake_peer(tmp_path / "mismatch", struct.pack(">I", len(encoded)) + encoded)
    instance = ControlPlaneClient(path, connect_timeout_seconds=1, request_timeout_seconds=1)
    with pytest.raises(ControlPlaneProtocolError):
        instance.get_execution_budget("task_018f3d4a-7b8c-7c9d-8e1f-0123456789ab", CORRELATION_ID, {})
    thread.join(1)


def test_expired_capability_is_returned_as_bounded_remote_rejection(tmp_path) -> None:
    fixture = ControlPlaneFixture(tmp_path)
    try:
        capability = fixture.capability(["GetExecutionBudget"], expires_at="2026-09-28T00:00:00.000Z")
        with pytest.raises(ControlPlaneRemoteError, match="UNAUTHORIZED") as exc_info:
            client(fixture).get_execution_budget(fixture.task_id, CORRELATION_ID, capability)
        assert capability["capability_proof"] not in str(exc_info.value)
    finally:
        fixture.close()
