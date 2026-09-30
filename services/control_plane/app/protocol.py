"""Bounded v1.0 length-prefixed canonical JSON UDS protocol."""
from __future__ import annotations

import socket
import struct

from .errors import ControlPlaneError, fail
from .ids import validate_id
from .models import canonical_json, require_canonical_json

MAX_REQUEST = 256 * 1024
MAX_RESPONSE = 1024 * 1024
PROTOCOL_VERSION = "1.0"
READ_OPERATIONS = {"GetTask", "GetTaskResources", "GetPendingGates", "GetExecutionBudget", "EvaluateProviderPreflight"}
MUTATING_OPERATIONS = {"CreateTask", "TransitionTask", "PauseTask", "ResumeTask", "CreateCheckpoint", "AllocateResource", "BindResourceIdentity", "MarkResourceTerminal", "RecordHeartbeat", "CreateGate", "ResolveGate", "ConsumeGate", "AppendEvent", "ReconcileObservation", "AdmitModelCall", "ReserveDelegation", "ReleaseDelegation", "ReserveReviewBudget", "RecordProviderObservation", "ReserveTransientRetry"}
REVISIONED_OPERATIONS = {"TransitionTask", "PauseTask", "ResumeTask", "CreateCheckpoint", "BindResourceIdentity", "MarkResourceTerminal", "ResolveGate", "ConsumeGate"}
BOOTSTRAP_OPERATION = "ExchangeCoordinatorBootstrap"
ALL_OPERATIONS = READ_OPERATIONS | MUTATING_OPERATIONS | {BOOTSTRAP_OPERATION}


def encode_frame(payload: dict, max_size=MAX_RESPONSE) -> bytes:
    raw = canonical_json(payload).encode("utf-8")
    if len(raw) > max_size: raise fail("INVALID_REQUEST", "frame exceeds bound")
    return struct.pack(">I", len(raw)) + raw


def decode_frame(data: bytes, max_size=MAX_REQUEST) -> dict:
    if len(data) < 4: raise fail("INVALID_REQUEST", "invalid frame")
    length = struct.unpack(">I", data[:4])[0]
    if length > max_size or len(data) != length + 4: raise fail("INVALID_REQUEST", "invalid frame length")
    try: payload = require_canonical_json(data[4:].decode("utf-8"))
    except (UnicodeError, ValueError): raise fail("INVALID_REQUEST", "invalid canonical JSON")
    if not isinstance(payload, dict): raise fail("INVALID_REQUEST", "envelope must be object")
    return payload


def recv_frame(sock: socket.socket, max_size=MAX_REQUEST) -> dict:
    header = _read_exact(sock, 4); length = struct.unpack(">I", header)[0]
    if length > max_size: raise fail("INVALID_REQUEST", "frame exceeds bound")
    return decode_frame(header + _read_exact(sock, length), max_size)


def send_frame(sock, payload): sock.sendall(encode_frame(payload))


def _read_exact(sock, size):
    out = bytearray()
    while len(out) < size:
        part = sock.recv(size - len(out))
        if not part: raise fail("INVALID_REQUEST", "truncated frame")
        out.extend(part)
    return bytes(out)


def validate_envelope(request):
    if not isinstance(request, dict): raise fail("INVALID_REQUEST", "invalid request")
    if request.get("protocol_version") != PROTOCOL_VERSION: raise fail("UNSUPPORTED_PROTOCOL", "unsupported protocol version")
    for key in ("operation", "correlation_id", "caller", "authorization", "body"):
        if key not in request: raise fail("INVALID_REQUEST", "missing request field")
    if request["operation"] not in ALL_OPERATIONS: raise fail("INVALID_REQUEST", "unknown operation")
    if not validate_id(request["correlation_id"], "corr") or not isinstance(request["caller"], dict) or not isinstance(request["authorization"], dict) or not isinstance(request["body"], dict):
        raise fail("INVALID_REQUEST", "invalid request envelope")
    if request["operation"] in MUTATING_OPERATIONS and (not isinstance(request.get("idempotency_key"), str) or not request["idempotency_key"]):
        raise fail("INVALID_REQUEST", "mutation requires idempotency key")
    if request["operation"] in REVISIONED_OPERATIONS and (not isinstance(request.get("expected_revision"), int) or request["expected_revision"] < 0):
        raise fail("INVALID_REQUEST", "revisioned mutation requires expected revision")
    return request
