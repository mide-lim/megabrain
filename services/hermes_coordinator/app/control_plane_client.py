"""Bounded UDS client for the coordinator's fixed Control Plane operations."""
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
_CALLER = {"role": "HERMES_COORDINATOR", "identity_id": "hermes"}


class ControlPlaneClientError(RuntimeError):
    """Bounded error returned by the Control Plane client."""


class ControlPlaneUnavailableError(ControlPlaneClientError):
    """The local Control Plane UDS could not provide a bounded response."""


class ControlPlaneProtocolError(ControlPlaneClientError):
    """The peer did not satisfy the versioned Control Plane protocol."""


class ControlPlaneRemoteError(ControlPlaneClientError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ControlPlaneClient:
    """Coordinator-only API; intentionally not a generic Control Plane client."""

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

    def get_execution_budget(self, task_id: str, correlation_id: str, capability: dict[str, Any]) -> dict[str, Any]:
        result = self._request("GetExecutionBudget", task_id, correlation_id, capability, {"task_id": task_id})
        return self._task_result(result, task_id)

    def evaluate_provider_preflight(
        self,
        task_id: str,
        correlation_id: str,
        channel_id: str,
        capability: dict[str, Any],
        *,
        fallback_authorized: bool = False,
    ) -> dict[str, Any]:
        result = self._request(
            "EvaluateProviderPreflight",
            task_id,
            correlation_id,
            capability,
            {"task_id": task_id, "channel_id": channel_id, "fallback_authorized": fallback_authorized},
        )
        if not isinstance(result, dict) or result.get("channel_id") != channel_id:
            raise ControlPlaneProtocolError("unexpected provider preflight result")
        return result

    def admit_model_call(
        self,
        task_id: str,
        correlation_id: str,
        observed_context_tokens: int,
        capability: dict[str, Any],
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if not isinstance(idempotency_key, str) or not idempotency_key or idempotency_key == correlation_id:
            raise ValueError("distinct model admission idempotency key is required")
        result = self._request(
            "AdmitModelCall",
            task_id,
            correlation_id,
            capability,
            {
                "task_id": task_id,
                "execution_role": "COORDINATOR",
                "execution_scope": None,
                "observed_context_tokens": observed_context_tokens,
            },
            idempotency_key=idempotency_key,
        )
        return self._task_result(result, task_id, require_task_id=False)

    def _request(
        self,
        operation: str,
        task_id: str,
        correlation_id: str,
        capability: dict[str, Any],
        body: dict[str, Any],
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(task_id, str) or not task_id or not isinstance(correlation_id, str) or not correlation_id:
            raise ValueError("task and correlation identifiers are required")
        request: dict[str, Any] = {
            "protocol_version": PROTOCOL_VERSION,
            "operation": operation,
            "correlation_id": correlation_id,
            "caller": _CALLER,
            "authorization": capability,
            "body": body,
        }
        if idempotency_key is not None:
            request["idempotency_key"] = idempotency_key
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
        parts = bytearray()
        while len(parts) < size:
            received = client.recv(size - len(parts))
            if not received:
                raise ControlPlaneProtocolError("truncated Control Plane frame")
            parts.extend(received)
        return bytes(parts)

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
    def _task_result(result: object, task_id: str, *, require_task_id: bool = True) -> dict[str, Any]:
        if not isinstance(result, dict):
            raise ControlPlaneProtocolError("unexpected Control Plane result")
        actual_task_id = result.get("task_id")
        if actual_task_id is not None and actual_task_id != task_id:
            raise ControlPlaneProtocolError("Control Plane task mismatch")
        if require_task_id and actual_task_id != task_id:
            raise ControlPlaneProtocolError("missing Control Plane task identifier")
        return result

    @staticmethod
    def _validate_response(response: dict[str, Any], correlation_id: str) -> dict[str, Any]:
        if response.get("protocol_version") != PROTOCOL_VERSION or response.get("correlation_id") != correlation_id:
            raise ControlPlaneProtocolError("unexpected Control Plane response envelope")
        has_result = "result" in response
        has_error = "error" in response
        if set(response) != ({"protocol_version", "correlation_id", "result"} if has_result else {"protocol_version", "correlation_id", "error"}):
            raise ControlPlaneProtocolError("unexpected Control Plane response shape")
        if has_result and not has_error and isinstance(response["result"], dict):
            return response["result"]
        if has_error and not has_result and isinstance(response["error"], dict):
            code = response["error"].get("code")
            if isinstance(code, str) and code:
                raise ControlPlaneRemoteError(code)
        raise ControlPlaneProtocolError("unexpected Control Plane response shape")
