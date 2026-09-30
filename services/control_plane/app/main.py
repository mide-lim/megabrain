"""Local AF_UNIX service entry point; never opens a TCP listener."""
from __future__ import annotations

import argparse
import grp
import os
import pwd
import socket
import stat
import struct
from pathlib import Path

from .auth import HermeticCapabilityIssuer, ProductionCapabilityAuthority, authorize
from .errors import ControlPlaneError, fail
from .protocol import recv_frame, send_frame, validate_envelope
from .service import ControlPlaneService

_PRODUCTION_CHANNELS = {"openai_codex"}


def _prepare_socket_directory(directory: Path, socket_gid: int | None) -> None:
    """Prepare only the AF_UNIX runtime directory; registry paths stay owner-only."""
    try:
        metadata = os.lstat(directory)
    except FileNotFoundError:
        try:
            directory.mkdir(mode=0o700, parents=True, exist_ok=False)
            metadata = os.lstat(directory)
        except OSError as exc:
            raise fail("REGISTRY_UNAVAILABLE", "socket directory unavailable") from exc
    except OSError as exc:
        raise fail("REGISTRY_UNAVAILABLE", "socket directory unavailable") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.geteuid():
        raise fail("REGISTRY_UNAVAILABLE", "unsafe socket directory")
    try:
        if socket_gid is None:
            os.chmod(directory, 0o700)
        else:
            os.chown(directory, -1, socket_gid)
            os.chmod(directory, 0o750)
    except OSError as exc:
        raise fail("REGISTRY_UNAVAILABLE", "socket directory unavailable") from exc


def get_peer_credentials(client: socket.socket) -> tuple[int, int, int]:
    """Extract Linux kernel credentials from the accepted AF_UNIX socket."""
    try:
        raw = client.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        return struct.unpack("3i", raw)
    except (AttributeError, OSError, struct.error) as exc:
        raise fail("UNAUTHORIZED", "unauthorized") from exc


def _scope_for_request(service, operation, body):
    task_id, resource_id = body.get("task_id"), body.get("resource_id")
    if operation in {"BindResourceIdentity", "MarkResourceTerminal", "ReconcileObservation"}: task_id, resource_id = service.resource_scope(resource_id)
    elif operation in {"ResolveGate", "ConsumeGate"}: task_id, resource_id = service.gate_scope(body.get("gate_id"))
    elif operation == "RecordHeartbeat" and resource_id: task_id, resource_id = service.resource_scope(resource_id)
    return task_id, resource_id


def _exchange_bootstrap(service: ControlPlaneService, request: dict, authority: ProductionCapabilityAuthority, peer_uid: int) -> dict:
    body = request["body"]
    if not isinstance(body, dict) or set(body) != {"bootstrap_id", "bootstrap_secret", "task_id", "channel_id"}:
        raise fail("UNAUTHORIZED", "unauthorized")
    try:
        result = authority.exchange(body["bootstrap_id"], body["bootstrap_secret"], body["task_id"], body["channel_id"], peer_uid)
        if body["channel_id"] not in _PRODUCTION_CHANNELS or service.get_task(body["task_id"])["task_id"] != body["task_id"]:
            raise fail("UNAUTHORIZED", "unauthorized")
        return result
    except (ControlPlaneError, KeyError, TypeError, ValueError):
        raise fail("UNAUTHORIZED", "unauthorized")


def dispatch_request(service: ControlPlaneService, request: dict, issuer, *, peer_uid: int | None = None) -> dict:
    """Authorize and dispatch; proofs are never passed to storage."""
    operation, body = request["operation"], request["body"]
    if operation == "ExchangeCoordinatorBootstrap":
        if not isinstance(issuer, ProductionCapabilityAuthority) or peer_uid is None: raise fail("UNAUTHORIZED", "unauthorized")
        return _exchange_bootstrap(service, request, issuer, peer_uid)
    if not isinstance(body, dict): raise fail("INVALID_REQUEST", "operation body must be an object")
    task_id, resource_id = _scope_for_request(service, operation, body)
    authorize(request["caller"], request["authorization"], operation, task_id, resource_id, issuer, channel_id=body.get("channel_id"), peer_uid=peer_uid)
    caller, key, correlation_id = request["caller"], request.get("idempotency_key"), request["correlation_id"]
    capability_id, revision = request["authorization"]["capability_id"], request.get("expected_revision")
    if operation == "CreateTask": return service.create_task(caller, key, correlation_id, body, capability_id)
    if operation == "GetTask": return service.get_task(task_id)
    if operation == "GetExecutionBudget": return service.get_execution_budget(task_id)
    if operation == "GetTaskResources": return {"task_id": task_id, "resources": service.get_task_resources(task_id)}
    if operation == "GetPendingGates": return {"task_id": task_id, "gates": service.get_pending_gates(task_id, resource_id)}
    if operation == "TransitionTask": return service.transition_task(caller, key, correlation_id, task_id, revision, body.get("target"), body.get("reason"), capability_id)
    if operation == "PauseTask": return service.pause_task(caller, key, correlation_id, task_id, revision, body.get("reason"), body.get("snapshot"), capability_id)
    if operation == "ResumeTask": return service.resume_task(caller, key, correlation_id, task_id, revision, body.get("checkpoint_id"), capability_id)
    if operation == "CreateCheckpoint": return service.create_checkpoint(caller, key, correlation_id, task_id, revision, body.get("snapshot"), capability_id)
    if operation == "AllocateResource": return service.allocate_resource(caller, key, correlation_id, task_id, {k: v for k, v in body.items() if k != "task_id"}, capability_id)
    if operation == "BindResourceIdentity": return service.bind_resource(caller, key, correlation_id, resource_id, revision, body.get("identity"), capability_id)
    if operation == "MarkResourceTerminal": return service.terminalize_resource(caller, key, correlation_id, resource_id, revision, body.get("reason"), capability_id)
    if operation == "RecordHeartbeat": return service.record_heartbeat(caller, key, correlation_id, task_id, resource_id, body.get("sequence"), body.get("status", "EXPECTED"), body.get("evidence_ref"), capability_id)
    if operation == "CreateGate": return service.create_gate(caller, key, correlation_id, task_id, {k: v for k, v in body.items() if k != "task_id"}, capability_id)
    if operation == "ResolveGate": return service.resolve_gate(caller, key, correlation_id, body.get("gate_id"), revision, body.get("approve"), body.get("authorization_reference"), body.get("expires_at"), capability_id)
    if operation == "ConsumeGate": return service.consume_gate(caller, key, correlation_id, body.get("gate_id"), revision, body.get("operation"), capability_id=capability_id)
    if operation == "AppendEvent": return service.append_event(caller, key, correlation_id, task_id, resource_id, body.get("event_type"), body.get("payload"), capability_id)
    if operation == "ReconcileObservation": return service.reconcile_observation(caller, key, correlation_id, resource_id, body.get("adapter_type"), body.get("adapter_version"), body.get("observation"), body.get("observed_at"), body.get("evidence_ref"), capability_id)
    if operation == "AdmitModelCall": return service.admit_model_call(caller, key, correlation_id, task_id, body.get("execution_role"), body.get("execution_scope"), body.get("observed_context_tokens"), capability_id)
    if operation == "ReserveDelegation": return service.reserve_delegation(caller, key, correlation_id, task_id, capability_id)
    if operation == "ReleaseDelegation": return service.release_delegation(caller, key, correlation_id, task_id, capability_id)
    if operation == "ReserveReviewBudget": return service.reserve_review_budget(caller, key, correlation_id, task_id, body.get("requested_calls"), capability_id)
    if operation == "RecordProviderObservation": return service.record_provider_observation(caller, key, correlation_id, body.get("channel_id"), body.get("state"), body.get("observed_at"), body.get("reset_at"), body.get("source"), body.get("metadata"), capability_id)
    if operation == "EvaluateProviderPreflight": return service.evaluate_provider_preflight(task_id, body.get("channel_id"), body.get("fallback_authorized"))
    if operation == "ReserveTransientRetry": return service.reserve_transient_retry(caller, key, correlation_id, task_id, body.get("channel_id"), capability_id)
    raise fail("INVALID_REQUEST", "unsupported operation")


def serve(socket_path, database_path, *, issuer=None, stop_event=None, ready_event=None, socket_mode: int = 0o600, socket_gid: int | None = None):
    if issuer is None: raise fail("UNAUTHORIZED", "runtime capability issuer is not configured")
    path = Path(socket_path); _prepare_socket_directory(path.parent, socket_gid)
    if path.exists(): raise fail("REGISTRY_UNAVAILABLE", "socket path already exists")
    service = ControlPlaneService(database_path); sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(str(path)); os.chmod(path, socket_mode)
    if socket_gid is not None: os.chown(path, -1, socket_gid)
    sock.listen(16); sock.settimeout(0.1)
    if ready_event: ready_event.set()
    try:
        while not (stop_event and stop_event.is_set()):
            try: client, _ = sock.accept()
            except TimeoutError: continue
            with client:
                correlation_id = "unknown"
                try:
                    _, peer_uid, _ = get_peer_credentials(client)
                    request = validate_envelope(recv_frame(client)); correlation_id = request["correlation_id"]
                    send_frame(client, {"protocol_version": "1.0", "correlation_id": correlation_id, "result": dispatch_request(service, request, issuer, peer_uid=peer_uid)})
                except ControlPlaneError as exc: send_frame(client, exc.envelope(correlation_id))
                except (KeyError, TypeError, ValueError): send_frame(client, fail("INVALID_REQUEST", "invalid request").envelope(correlation_id))
    finally:
        sock.close(); service.close(); path.unlink(missing_ok=True)


def _production_issuer() -> ProductionCapabilityAuthority:
    directory = os.environ.get("CREDENTIALS_DIRECTORY")
    if not directory: raise fail("UNAUTHORIZED", "credential unavailable")
    try: uid = pwd.getpwnam("megabrain-hermes").pw_uid
    except KeyError: raise fail("UNAUTHORIZED", "credential unavailable")
    return ProductionCapabilityAuthority.from_credential_directory(directory, expected_peer_uid=uid)


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--socket", required=True); parser.add_argument("--database", required=True); args = parser.parse_args()
    try: group_id = grp.getgrnam("megabrain-control-plane-clients").gr_gid
    except KeyError: raise SystemExit("Control Plane group unavailable")
    serve(args.socket, args.database, issuer=_production_issuer(), socket_mode=0o660, socket_gid=group_id)


if __name__ == "__main__": main()
