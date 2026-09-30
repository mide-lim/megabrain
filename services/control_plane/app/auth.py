"""Capability authorities: hermetic tests and production AF_UNIX bootstrap."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .errors import fail
from .models import canonical_json, validate_timestamp

ROLE_OPS = {
    "HERMES_COORDINATOR": {"CreateTask", "GetTask", "TransitionTask", "PauseTask", "ResumeTask", "CreateCheckpoint", "CreateGate", "AppendEvent", "GetTaskResources", "GetPendingGates", "ReconcileObservation", "GetExecutionBudget", "AdmitModelCall", "ReserveDelegation", "ReleaseDelegation", "ReserveReviewBudget", "EvaluateProviderPreflight"},
    "WORKER_MANAGER": {"GetTask", "GetTaskResources", "AllocateResource", "BindResourceIdentity", "MarkResourceTerminal", "RecordHeartbeat", "TransitionTask", "CreateCheckpoint", "ConsumeGate", "AppendEvent", "GetExecutionBudget", "AdmitModelCall", "ReserveDelegation", "ReleaseDelegation", "EvaluateProviderPreflight", "ReserveTransientRetry"},
    "WORKER": {"RecordHeartbeat", "AppendEvent", "MarkResourceTerminal", "GetTask", "GetTaskResources"}, "REVIEWER": {"GetTask", "GetTaskResources", "GetPendingGates", "AppendEvent", "ReconcileObservation", "GetExecutionBudget", "AdmitModelCall"}, "JANITOR": {"ReconcileObservation", "AppendEvent"}, "HUMAN_GATE_ADAPTER": {"GetPendingGates", "ResolveGate"}, "OBSERVABILITY_ADAPTER": {"ReconcileObservation", "AppendEvent", "RecordProviderObservation"},
}
_HERMETIC_IDENTITIES = {"HERMES_COORDINATOR": {"hermes"}, "WORKER_MANAGER": {"manager"}, "WORKER": {"worker"}, "REVIEWER": {"reviewer"}, "JANITOR": {"janitor"}, "HUMAN_GATE_ADAPTER": {"human"}, "OBSERVABILITY_ADAPTER": {"observer"}}
_REQUIRED_CAPABILITY_FIELDS = {"capability_id", "role", "identity_id", "allowed_operations", "expires_at", "task_id", "resource_id", "nonce", "capability_proof"}
_PRODUCTION_FIELDS = {"capability_id", "role", "identity_id", "allowed_operations", "expires_at", "task_id", "channel_id", "peer_uid", "generation", "nonce", "capability_proof"}
_MAX_CREDENTIAL_BYTES = 4096
_MAX_TTL_SECONDS = 300
_PROFILES = {"HERMES_COORDINATOR": ("hermes", ["AdmitModelCall", "EvaluateProviderPreflight", "GetExecutionBudget"]), "OBSERVABILITY_ADAPTER": ("observer", ["RecordProviderObservation"])}


def read_credential_file(path: str | Path) -> bytes:
    """Read one bounded no-follow regular systemd credential without content leaks."""
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(Path(path), flags)
        try:
            metadata = os.fstat(fd)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > _MAX_CREDENTIAL_BYTES:
                raise ValueError
            value = os.read(fd, _MAX_CREDENTIAL_BYTES + 1)
            if len(value) > _MAX_CREDENTIAL_BYTES:
                raise ValueError
            return value
        finally:
            os.close(fd)
    except (OSError, ValueError) as exc:
        raise fail("UNAUTHORIZED", "credential unavailable") from exc


class HermeticCapabilityIssuer:
    """Test-only issuer; deliberately separate from production issuance."""
    def __init__(self, secret: bytes = b"ap0-hermetic-test-issuer"): self.secret = secret
    def issue(self, capability_id: str, role: str, identity_id: str, operations: list[str], expires_at: str, task_id: str | None = None, resource_id: str | None = None, nonce: str = "n") -> dict:
        payload = {"capability_id": capability_id, "role": role, "identity_id": identity_id, "allowed_operations": operations, "expires_at": expires_at, "task_id": task_id, "resource_id": resource_id, "nonce": nonce}
        payload["capability_proof"] = hmac.new(self.secret, canonical_json(payload).encode(), hashlib.sha256).hexdigest(); return payload
    def validate(self, capability: dict) -> dict:
        if not isinstance(capability, dict) or set(capability) != _REQUIRED_CAPABILITY_FIELDS: raise fail("UNAUTHORIZED", "invalid capability")
        proof = capability["capability_proof"]; payload = {k: v for k, v in capability.items() if k != "capability_proof"}
        if not isinstance(proof, str) or len(proof) != 64 or not hmac.compare_digest(proof, hmac.new(self.secret, canonical_json(payload).encode(), hashlib.sha256).hexdigest()): raise fail("UNAUTHORIZED", "invalid capability")
        try: expiry = validate_timestamp(payload["expires_at"])
        except (KeyError, ValueError) as exc: raise fail("UNAUTHORIZED", "invalid capability expiry") from exc
        if datetime.fromisoformat(expiry.replace("Z", "+00:00")) <= datetime.now(UTC): raise fail("UNAUTHORIZED", "expired capability")
        if not isinstance(payload["capability_id"], str) or not payload["capability_id"] or not isinstance(payload["nonce"], str) or not payload["nonce"] or not isinstance(payload["allowed_operations"], list): raise fail("UNAUTHORIZED", "invalid capability")
        return payload


class ProductionCapabilityAuthority:
    """Short-lived HMAC capabilities bound to peer UID, task, channel, generation."""
    def __init__(self, *, bootstrap_id: str, verifier_sha256: str, generation: int, signing_key: bytes, expected_peer_uid: int) -> None:
        if not isinstance(bootstrap_id, str) or not bootstrap_id or len(bootstrap_id) > 128 or not isinstance(generation, int) or isinstance(generation, bool) or generation < 1 or not isinstance(expected_peer_uid, int) or expected_peer_uid < 0 or not isinstance(verifier_sha256, str) or len(verifier_sha256) != 64 or any(char not in "0123456789abcdef" for char in verifier_sha256) or not isinstance(signing_key, bytes) or len(signing_key) < 32:
            raise fail("UNAUTHORIZED", "credential unavailable")
        self.bootstrap_id, self.verifier_sha256, self.generation, self.signing_key, self.expected_peer_uid = bootstrap_id, verifier_sha256, generation, signing_key, expected_peer_uid

    @classmethod
    def from_credential_directory(cls, directory: str | Path, *, expected_peer_uid: int) -> "ProductionCapabilityAuthority":
        root = Path(directory)
        try:
            verifier = json.loads(read_credential_file(root / "control-plane-coordinator-bootstrap-verifier").decode("utf-8"))
            if not isinstance(verifier, dict) or set(verifier) != {"version", "bootstrap_id", "generation", "verifier_sha256"} or verifier.get("version") != 1:
                raise ValueError
            key = read_credential_file(root / "control-plane-capability-signing-key")
            return cls(bootstrap_id=verifier["bootstrap_id"], verifier_sha256=verifier["verifier_sha256"], generation=verifier["generation"], signing_key=key, expected_peer_uid=expected_peer_uid)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError, KeyError, ControlPlaneError) as exc:
            raise fail("UNAUTHORIZED", "credential unavailable") from exc

    def exchange(self, bootstrap_id: object, bootstrap_secret: object, task_id: object, channel_id: object, peer_uid: int) -> dict:
        if not all(isinstance(value, str) and value and len(value) <= 256 for value in (bootstrap_id, bootstrap_secret, task_id, channel_id)) or peer_uid != self.expected_peer_uid or bootstrap_id != self.bootstrap_id or not hmac.compare_digest(hashlib.sha256(bootstrap_secret.encode()).hexdigest(), self.verifier_sha256):
            raise fail("UNAUTHORIZED", "unauthorized")
        return {"coordinator_capability": self._mint("HERMES_COORDINATOR", task_id, channel_id, peer_uid), "observer_capability": self._mint("OBSERVABILITY_ADAPTER", None, channel_id, peer_uid)}

    def _mint(self, role: str, task_id: str | None, channel_id: str, peer_uid: int) -> dict:
        identity_id, operations = _PROFILES[role]; expiry = (datetime.now(UTC) + timedelta(seconds=_MAX_TTL_SECONDS)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        payload = {"capability_id": secrets.token_urlsafe(24), "role": role, "identity_id": identity_id, "allowed_operations": operations, "expires_at": expiry, "task_id": task_id, "channel_id": channel_id, "peer_uid": peer_uid, "generation": self.generation, "nonce": secrets.token_urlsafe(18)}
        payload["capability_proof"] = hmac.new(self.signing_key, canonical_json(payload).encode(), hashlib.sha256).hexdigest(); return payload

    def validate(self, capability: object) -> dict:
        if not isinstance(capability, dict) or set(capability) != _PRODUCTION_FIELDS: raise fail("UNAUTHORIZED", "unauthorized")
        proof = capability.get("capability_proof"); payload = {k: v for k, v in capability.items() if k != "capability_proof"}
        if not isinstance(proof, str) or len(proof) != 64 or not hmac.compare_digest(proof, hmac.new(self.signing_key, canonical_json(payload).encode(), hashlib.sha256).hexdigest()): raise fail("UNAUTHORIZED", "unauthorized")
        try: expiry = datetime.fromisoformat(validate_timestamp(payload["expires_at"]).replace("Z", "+00:00"))
        except (ValueError, KeyError) as exc: raise fail("UNAUTHORIZED", "unauthorized") from exc
        if expiry <= datetime.now(UTC) or payload.get("generation") != self.generation or payload.get("role") not in _PROFILES or payload.get("identity_id") != _PROFILES[payload["role"]][0] or payload.get("allowed_operations") != _PROFILES[payload["role"]][1] or not isinstance(payload.get("peer_uid"), int) or payload["peer_uid"] < 0 or not isinstance(payload.get("channel_id"), str) or not payload["channel_id"] or (payload.get("task_id") is not None and not isinstance(payload["task_id"], str)):
            raise fail("UNAUTHORIZED", "unauthorized")
        return payload

    def authorize(self, caller: dict, capability: dict, operation: str, *, task_id: str | None, channel_id: str | None, peer_uid: int) -> None:
        cap = self.validate(capability)
        if caller != {"role": cap["role"], "identity_id": cap["identity_id"]} or operation not in cap["allowed_operations"] or peer_uid != cap["peer_uid"] or (cap["task_id"] is not None and cap["task_id"] != task_id) or (channel_id is not None and cap["channel_id"] != channel_id):
            raise fail("UNAUTHORIZED", "unauthorized")


def authorize(caller: dict, capability: dict, operation: str, task_id: str | None = None, resource_id: str | None = None, issuer=None, *, channel_id: str | None = None, peer_uid: int | None = None) -> None:
    if isinstance(issuer, ProductionCapabilityAuthority):
        issuer.authorize(caller, capability, operation, task_id=task_id, channel_id=channel_id, peer_uid=-1 if peer_uid is None else peer_uid); return
    if not isinstance(caller, dict): raise fail("UNKNOWN_IDENTITY", "unknown caller identity")
    role, identity = caller.get("role"), caller.get("identity_id")
    if role not in ROLE_OPS or not isinstance(identity, str) or not identity or identity not in _HERMETIC_IDENTITIES.get(role, set()): raise fail("UNKNOWN_IDENTITY", "unknown caller identity")
    if operation not in ROLE_OPS[role]: raise fail("UNAUTHORIZED", "role operation denied")
    cap = (issuer or HermeticCapabilityIssuer()).validate(capability)
    if cap["role"] != role or cap["identity_id"] != identity or operation not in cap["allowed_operations"]: raise fail("UNAUTHORIZED", "capability scope denied")
    if cap["task_id"] not in (None, task_id) or cap["resource_id"] not in (None, resource_id): raise fail("UNAUTHORIZED", "capability target denied")
    if role == "WORKER" and (not cap["task_id"] or not cap["resource_id"]): raise fail("UNAUTHORIZED", "worker capability must bind a task and resource")


from .errors import ControlPlaneError
