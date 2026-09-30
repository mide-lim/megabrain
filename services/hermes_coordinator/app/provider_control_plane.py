"""Narrow OBSERVABILITY_ADAPTER client for provider observations."""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .control_plane_client import ControlPlaneClient, ControlPlaneProtocolError
from .provider_classifier import CHANNEL_PROVIDERS, ProviderObservation

_OBSERVER_CALLER = {"role": "OBSERVABILITY_ADAPTER", "identity_id": "observer"}
_ADAPTER_SOURCE = "hermes_usage_probe"
_MAX_METADATA_BYTES = 8 * 1024
_MAX_WINDOWS = 16
_SAFE_UPSTREAM_SOURCES = frozenset({"codex account usage"})


class ProviderObservationClient:
    """Records provider evidence only; it cannot evaluate or admit work."""

    def __init__(
        self,
        socket_path: str | Path,
        *,
        connect_timeout_seconds: float = 2.0,
        request_timeout_seconds: float = 5.0,
    ) -> None:
        self._transport = ControlPlaneClient(
            socket_path,
            connect_timeout_seconds=connect_timeout_seconds,
            request_timeout_seconds=request_timeout_seconds,
            _caller=_OBSERVER_CALLER,
        )

    def record_provider_observation(
        self,
        observation: ProviderObservation,
        correlation_id: str,
        capability: dict[str, Any],
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if not isinstance(idempotency_key, str) or not idempotency_key or idempotency_key == correlation_id:
            raise ValueError("distinct provider observation idempotency key is required")
        body = provider_observation_payload(observation)
        result = self._transport._request(
            "RecordProviderObservation",
            None,
            correlation_id,
            capability,
            body,
            idempotency_key=idempotency_key,
        )
        return self._record_result(result, body)

    @staticmethod
    def _record_result(result: object, body: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(result, dict) or set(result) != {"channel_id", "state", "observed_at", "reset_at", "revision"}:
            raise ControlPlaneProtocolError("unexpected provider observation result")
        if any(result[field] != body[field] for field in ("channel_id", "state", "observed_at", "reset_at")):
            raise ControlPlaneProtocolError("provider observation result mismatch")
        revision = result["revision"]
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
            raise ControlPlaneProtocolError("invalid provider observation revision")
        return result


def provider_observation_payload(observation: ProviderObservation) -> dict[str, Any]:
    """Map a parsed/local ProviderObservation to the bounded Control Plane body."""
    if not isinstance(observation, ProviderObservation):
        raise ValueError("a ProviderObservation is required")
    if not isinstance(observation.channel_id, str) or not observation.channel_id or len(observation.channel_id) > 128:
        raise ValueError("bounded channel_id is required")
    state = observation.state.value
    metadata = {
        "reason_code": observation.reason_code.value,
        "provider": _known_provider(observation.channel_id, observation.provider),
        "provider_fetched_at": _timestamp_or_none(observation.provider_fetched_at),
        "probe_exit_code": _exit_code_or_none(observation.probe_exit_code),
        "timed_out": _bool(observation.timed_out, "timed_out"),
        "windows_summary": _windows_summary(observation),
    }
    _require_small_metadata(metadata)
    return {
        "channel_id": observation.channel_id,
        "state": state,
        "observed_at": _timestamp(observation.observed_at),
        "reset_at": _timestamp_or_none(observation.reset_at),
        "source": _source(observation.source),
        "metadata": metadata,
    }


def _timestamp_or_none(value: object) -> str | None:
    return None if value is None else _timestamp(value)


def _timestamp(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("provider observation timestamp must be text")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as exc:
        raise ValueError("provider observation timestamp must be RFC3339") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("provider observation timestamp must include an offset")
    return parsed.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _source(value: object) -> str:
    if isinstance(value, str) and value in _SAFE_UPSTREAM_SOURCES:
        return value
    return _ADAPTER_SOURCE


def _known_provider(channel_id: str, provider: object) -> str | None:
    if isinstance(provider, str) and provider == CHANNEL_PROVIDERS.get(channel_id):
        return provider
    return None


def _exit_code_or_none(value: object) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < -255 or value > 255:
        raise ValueError("probe exit code is outside bounded limits")
    return value


def _bool(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be boolean")
    return value


def _windows_summary(observation: ProviderObservation) -> list[dict[str, Any]]:
    if len(observation.windows_summary) > _MAX_WINDOWS:
        raise ValueError("provider windows exceed bounded limits")
    result = []
    for index, window in enumerate(observation.windows_summary, start=1):
        if not isinstance(window.used_percent, (int, float)) or isinstance(window.used_percent, bool) or not math.isfinite(window.used_percent):
            raise ValueError("provider window percentage must be finite")
        result.append(
            {
                "label": f"window_{index}",
                "used_percent": float(window.used_percent),
                "resets_at": _timestamp_or_none(window.resets_at),
            }
        )
    return result


def _require_small_metadata(metadata: dict[str, Any]) -> None:
    encoded = json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(encoded) > _MAX_METADATA_BYTES:
        raise ValueError("provider metadata exceeds bounded limits")
