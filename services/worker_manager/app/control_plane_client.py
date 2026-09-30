"""Narrow bounded UDS client for Worker Manager lease operations."""
from __future__ import annotations

import json
import os
import socket
import stat
import struct
from pathlib import Path
from typing import Any

MAX_REQUEST_BYTES = 256 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024
PROTOCOL_VERSION = "1.0"
DEFAULT_CONNECT_TIMEOUT_SECONDS = 2.0
DEFAULT_REQUEST_TIMEOUT_SECONDS = 5.0
MAX_TIMEOUT_SECONDS = 30.0
_CALLER = {"role": "WORKER_MANAGER", "identity_id": "manager"}


class ControlPlaneClientError(RuntimeError):
    pass


class ControlPlaneUnavailableError(ControlPlaneClientError):
    pass


class ControlPlaneProtocolError(ControlPlaneClientError):
    pass


class ControlPlaneRemoteError(ControlPlaneClientError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ControlPlaneClient:
    """Expose only the lease operations needed by the Worker Manager."""

    def __init__(
        self,
        socket_path: str | Path,
        *,
        connect_timeout_seconds: float = DEFAULT_CONNECT_TIMEOUT_SECONDS,
        request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        if not isinstance(socket_path, (str, Path)) or not str(socket_path):
            raise ValueError("a Control Plane socket path is required")
        self.socket_path = Path(socket_path)
        self.connect_timeout_seconds = self._timeout(connect_timeout_seconds)
        self.request_timeout_seconds = self._timeout(request_timeout_seconds)

    def allocate_worker(
        self,
        *,
        task_id: str,
        correlation_id: str,
        capability: dict[str, Any],
        idempotency_key: str,
        requested_operation: dict[str, Any],
        expectation: dict[str, Any],
    ) -> dict[str, Any]:
        result = self._request(
            "AllocateResource",
            correlation_id,
            capability,
            {
                "task_id": task_id,
                "resource_type": "WORKER",
                "requested_operation": requested_operation,
                "expected_identity": expectation,
                "budget_reservation": {},
                "metadata": {"command_profile": "worker-manager"},
                "heartbeat_required": True,
            },
            idempotency_key=idempotency_key,
        )
        return self._resource_result(result, state="ALLOCATED", revision=0)

    def bind_worker(
        self,
        *,
        resource_id: str,
        correlation_id: str,
        capability: dict[str, Any],
        idempotency_key: str,
        expected_revision: int,
        observation: dict[str, Any],
        launch_nonce: str,
    ) -> dict[str, Any]:
        result = self._request(
            "BindResourceIdentity",
            correlation_id,
            capability,
            {
                "resource_id": resource_id,
                "identity": observation,
                "launch_nonce": launch_nonce,
            },
            idempotency_key=idempotency_key,
            expected_revision=expected_revision,
        )
        return self._resource_result(
            result,
            state="ACTIVE",
            resource_id=resource_id,
            revision=expected_revision + 1,
        )

    def terminalize_worker(
        self,
        *,
        resource_id: str,
        correlation_id: str,
        capability: dict[str, Any],
        idempotency_key: str,
        expected_revision: int,
        reason: dict[str, Any],
    ) -> dict[str, Any]:
        result = self._request(
            "MarkResourceTerminal",
            correlation_id,
            capability,
            {"resource_id": resource_id, "reason": reason},
            idempotency_key=idempotency_key,
            expected_revision=expected_revision,
        )
        return self._resource_result(
            result,
            state="TERMINAL",
            resource_id=resource_id,
            revision=expected_revision + 1,
        )

    def _request(
        self,
        operation: str,
        correlation_id: str,
        capability: dict[str, Any],
        body: dict[str, Any],
        *,
        idempotency_key: str,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        if not isinstance(correlation_id, str) or not correlation_id:
            raise ValueError("correlation identifier required")
        if not isinstance(idempotency_key, str) or not idempotency_key or len(idempotency_key) > 256:
            raise ValueError("bounded idempotency key required")
        if not isinstance(capability, dict):
            raise ValueError("capability payload required")
        request: dict[str, Any] = {
            "protocol_version": PROTOCOL_VERSION,
            "operation": operation,
            "correlation_id": correlation_id,
            "caller": _CALLER,
            "authorization": capability,
            "body": body,
            "idempotency_key": idempotency_key,
        }
        if expected_revision is not None:
            if not isinstance(expected_revision, int) or isinstance(expected_revision, bool) or expected_revision < 0:
                raise ValueError("nonnegative expected revision required")
            request["expected_revision"] = expected_revision
        raw = self._canonical_json(request)
        if len(raw) > MAX_REQUEST_BYTES:
            raise ControlPlaneProtocolError("request exceeds Control Plane bound")
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(self.connect_timeout_seconds)
                client.connect(str(self.socket_path))
                self._require_socket_target()
                client.settimeout(self.request_timeout_seconds)
                client.sendall(struct.pack(">I", len(raw)) + raw)
                response = self._recv_frame(client)
        except ControlPlaneProtocolError:
            raise
        except (FileNotFoundError, ConnectionRefusedError, TimeoutError, socket.timeout, OSError) as exc:
            raise ControlPlaneUnavailableError("Control Plane unavailable") from exc
        return self._validate_response(response, correlation_id)

    def _require_socket_target(self) -> None:
        try:
            metadata = os.stat(self.socket_path)
        except OSError as exc:
            raise ControlPlaneUnavailableError("Control Plane unavailable") from exc
        if not stat.S_ISSOCK(metadata.st_mode):
            raise ControlPlaneProtocolError("Control Plane target is not a Unix socket")

    def _recv_frame(self, client: socket.socket) -> dict[str, Any]:
        header = self._read_exact(client, 4)
        length = struct.unpack(">I", header)[0]
        if length > MAX_RESPONSE_BYTES:
            raise ControlPlaneProtocolError("response exceeds Control Plane bound")
        raw = self._read_exact(client, length)
        try:
            decoded = json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=self._no_duplicate_keys,
                parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("non-finite JSON")),
            )
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
            raise ControlPlaneProtocolError("invalid Control Plane JSON") from exc
        if not isinstance(decoded, dict) or self._canonical_json(decoded) != raw:
            raise ControlPlaneProtocolError("noncanonical Control Plane response")
        return decoded

    @staticmethod
    def _read_exact(client: socket.socket, size: int) -> bytes:
        out = bytearray()
        while len(out) < size:
            part = client.recv(size - len(out))
            if not part:
                raise ControlPlaneProtocolError("truncated Control Plane frame")
            out.extend(part)
        return bytes(out)

    @staticmethod
    def _no_duplicate_keys(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    @staticmethod
    def _canonical_json(value: object) -> bytes:
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ControlPlaneProtocolError("invalid Control Plane JSON value") from exc

    @staticmethod
    def _timeout(value: float) -> float:
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 < value <= MAX_TIMEOUT_SECONDS:
            raise ValueError("Control Plane timeout is outside bounded limits")
        return float(value)

    @staticmethod
    def _resource_result(
        result: object,
        *,
        state: str,
        resource_id: str | None = None,
        revision: int,
    ) -> dict[str, Any]:
        if not isinstance(result, dict) or set(result) != {"resource_id", "revision", "state"}:
            raise ControlPlaneProtocolError("unexpected resource result")
        if result["state"] != state or result["revision"] != revision:
            raise ControlPlaneProtocolError("unexpected resource state")
        if not isinstance(result["resource_id"], str) or not result["resource_id"]:
            raise ControlPlaneProtocolError("invalid resource identifier")
        if resource_id is not None and result["resource_id"] != resource_id:
            raise ControlPlaneProtocolError("Control Plane resource mismatch")
        return result

    @staticmethod
    def _validate_response(response: dict[str, Any], correlation_id: str) -> dict[str, Any]:
        if response.get("protocol_version") != PROTOCOL_VERSION or response.get("correlation_id") != correlation_id:
            raise ControlPlaneProtocolError("unexpected Control Plane response envelope")
        has_result, has_error = "result" in response, "error" in response
        expected = {"protocol_version", "correlation_id", "result"} if has_result else {"protocol_version", "correlation_id", "error"}
        if set(response) != expected:
            raise ControlPlaneProtocolError("unexpected Control Plane response shape")
        if has_result and not has_error and isinstance(response["result"], dict):
            return response["result"]
        if has_error and not has_result and isinstance(response["error"], dict):
            code = response["error"].get("code")
            if isinstance(code, str) and code:
                raise ControlPlaneRemoteError(code)
        raise ControlPlaneProtocolError("unexpected Control Plane response shape")
