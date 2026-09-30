from __future__ import annotations

import json
import os
import socket
import sqlite3
import shutil
import tempfile
import threading
from pathlib import Path

import pytest

from app.auth import ProductionCapabilityAuthority, read_credential_file
from app.errors import ControlPlaneError
from app.main import get_peer_credentials, serve
from app.protocol import recv_frame, send_frame
from helpers import CORR, HERMES, OBSERVER, ready_task


def _credentials(tmp_path: Path, *, generation: int = 1) -> tuple[Path, str]:
    secret = "fake-bootstrap-secret-" + "a" * 64
    directory = tmp_path / "credentials"; directory.mkdir(mode=0o700, parents=True)
    verifier = {"version": 1, "bootstrap_id": "coordinator-v1", "generation": generation, "verifier_sha256": __import__("hashlib").sha256(secret.encode()).hexdigest()}
    (directory / "control-plane-coordinator-bootstrap-verifier").write_text(json.dumps(verifier), encoding="utf-8")
    (directory / "control-plane-capability-signing-key").write_bytes(b"fake-signing-key-" + b"b" * 48)
    return directory, secret


def _bootstrap(path: Path, secret: str, task_id: str, channel_id: str = "openai_codex") -> dict:
    request = {"protocol_version": "1.0", "operation": "ExchangeCoordinatorBootstrap", "correlation_id": CORR, "caller": HERMES, "authorization": {}, "body": {"bootstrap_id": "coordinator-v1", "bootstrap_secret": secret, "task_id": task_id, "channel_id": channel_id}}
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.connect(str(path)); send_frame(client, request); return recv_frame(client)


def _server(tmp_path: Path, authority: ProductionCapabilityAuthority):
    from app.service import ControlPlaneService
    database = tmp_path / "control-plane.sqlite"; service = ControlPlaneService(database); task_id = ready_task(service); service.close()
    socket_dir = Path(tempfile.mkdtemp(prefix="mb-prod-cp-", dir="/tmp"))
    path = socket_dir / "control-plane.sock"; stop = threading.Event(); ready = threading.Event()
    thread = threading.Thread(target=serve, args=(path, database), kwargs={"issuer": authority, "stop_event": stop, "ready_event": ready}, daemon=True)
    thread.start(); assert ready.wait(2)
    return path, database, task_id, stop, thread


def test_production_bootstrap_mints_only_scoped_profiles_and_hides_auth_failures(tmp_path: Path):
    credentials, secret = _credentials(tmp_path)
    authority = ProductionCapabilityAuthority.from_credential_directory(credentials, expected_peer_uid=os.getuid())
    path, database, task_id, stop, thread = _server(tmp_path, authority)
    try:
        success = _bootstrap(path, secret, task_id)["result"]
        coordinator, observer = success["coordinator_capability"], success["observer_capability"]
        assert coordinator["allowed_operations"] == ["AdmitModelCall", "EvaluateProviderPreflight", "GetExecutionBudget"]
        assert coordinator["task_id"] == task_id and coordinator["channel_id"] == "openai_codex"
        assert observer["allowed_operations"] == ["RecordProviderObservation"]
        assert observer["task_id"] is None and observer["channel_id"] == "openai_codex"
        for body in ({**{"bootstrap_id": "wrong", "bootstrap_secret": secret, "task_id": task_id, "channel_id": "openai_codex"}}, {"bootstrap_id": "coordinator-v1", "bootstrap_secret": "wrong", "task_id": task_id, "channel_id": "openai_codex"}, {"bootstrap_id": "coordinator-v1", "bootstrap_secret": secret, "task_id": task_id, "channel_id": "unknown"}):
            request = {"protocol_version": "1.0", "operation": "ExchangeCoordinatorBootstrap", "correlation_id": CORR, "caller": HERMES, "authorization": {}, "body": body}
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.connect(str(path)); send_frame(client, request); response = recv_frame(client)
            assert response["error"]["code"] == "UNAUTHORIZED" and response["error"]["message"] == "unauthorized"
            assert secret not in json.dumps(response)
        assert "capability_proof" not in "\n".join(row[0] for row in sqlite3.connect(database).iterdump())
    finally:
        stop.set(); thread.join(2); shutil.rmtree(path.parent, ignore_errors=True)


def test_production_capability_enforces_proof_ttl_generation_peer_task_and_channel(tmp_path: Path):
    credentials, secret = _credentials(tmp_path)
    authority = ProductionCapabilityAuthority.from_credential_directory(credentials, expected_peer_uid=os.getuid())
    cap = authority.exchange("coordinator-v1", secret, "task_a", "openai_codex", os.getuid())["coordinator_capability"]
    authority.authorize(HERMES, cap, "GetExecutionBudget", task_id="task_a", channel_id=None, peer_uid=os.getuid())
    for field, value in (("task_id", "task_b"), ("channel_id", "other"), ("peer_uid", os.getuid() + 1), ("capability_proof", "0" * 64)):
        altered = dict(cap); altered[field] = value
        with pytest.raises(ControlPlaneError, match="UNAUTHORIZED"):
            authority.authorize(HERMES, altered, "GetExecutionBudget", task_id="task_a", channel_id=None, peer_uid=os.getuid())
    with pytest.raises(ControlPlaneError, match="UNAUTHORIZED"):
        authority.authorize(OBSERVER, cap, "RecordProviderObservation", task_id=None, channel_id="openai_codex", peer_uid=os.getuid())
    rotated = ProductionCapabilityAuthority.from_credential_directory(credentials, expected_peer_uid=os.getuid())
    rotated.generation += 1
    with pytest.raises(ControlPlaneError, match="UNAUTHORIZED"):
        rotated.authorize(HERMES, cap, "GetExecutionBudget", task_id="task_a", channel_id=None, peer_uid=os.getuid())


def test_credential_reader_rejects_symlink_oversize_malformed_and_weak_key(tmp_path: Path):
    target = tmp_path / "target"; target.write_text("x")
    link = tmp_path / "link"; link.symlink_to(target)
    with pytest.raises(ControlPlaneError): read_credential_file(link)
    large = tmp_path / "large"; large.write_bytes(b"x" * 4097)
    with pytest.raises(ControlPlaneError): read_credential_file(large)
    directory, _ = _credentials(tmp_path / "nested")
    (directory / "control-plane-coordinator-bootstrap-verifier").write_text('{"version":1}', encoding="utf-8")
    with pytest.raises(ControlPlaneError): ProductionCapabilityAuthority.from_credential_directory(directory, expected_peer_uid=os.getuid())
    (directory / "control-plane-coordinator-bootstrap-verifier").write_text(json.dumps({"version": 1, "bootstrap_id": "coordinator-v1", "generation": 1, "verifier_sha256": "a" * 64}), encoding="utf-8")
    (directory / "control-plane-capability-signing-key").write_bytes(b"short")
    with pytest.raises(ControlPlaneError): ProductionCapabilityAuthority.from_credential_directory(directory, expected_peer_uid=os.getuid())


def test_real_so_peercred_extraction_on_accepted_unix_socket(tmp_path: Path):
    socket_dir = Path(tempfile.mkdtemp(prefix="mb-peer-", dir="/tmp"))
    path = socket_dir / "peer.sock"; listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); listener.bind(str(path)); listener.listen(1)
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); client.connect(str(path)); accepted, _ = listener.accept()
    try:
        pid, uid, gid = get_peer_credentials(accepted)
        assert pid == os.getpid() and uid == os.getuid() and gid == os.getgid()
    finally:
        accepted.close(); client.close(); listener.close(); shutil.rmtree(socket_dir, ignore_errors=True)
