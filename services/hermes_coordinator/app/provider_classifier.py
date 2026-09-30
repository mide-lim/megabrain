from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from .provider_usage import HermesUsageDocument, UsageWindow

CHANNEL_PROVIDERS = {"openai_codex": "openai-codex"}


class ProviderState(str, Enum):
    AVAILABLE = "AVAILABLE"
    AUTH_EXPIRED = "AUTH_EXPIRED"
    QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
    TRANSIENT_FAILURE = "TRANSIENT_FAILURE"
    UNKNOWN = "UNKNOWN"


class ReasonCode(str, Enum):
    USAGE_AVAILABLE = "USAGE_AVAILABLE"
    USAGE_WINDOW_EXHAUSTED = "USAGE_WINDOW_EXHAUSTED"
    PROBE_TIMEOUT = "PROBE_TIMEOUT"
    PROBE_UNAVAILABLE = "PROBE_UNAVAILABLE"
    PROBE_NONZERO = "PROBE_NONZERO"
    PROBE_MALFORMED = "PROBE_MALFORMED"
    PROBE_SCHEMA_UNSUPPORTED = "PROBE_SCHEMA_UNSUPPORTED"
    PROVIDER_UNSUPPORTED = "PROVIDER_UNSUPPORTED"
    AUTH_EXPLICITLY_EXPIRED = "AUTH_EXPLICITLY_EXPIRED"


@dataclass(frozen=True)
class UsageWindowSummary:
    label: str
    used_percent: float
    resets_at: str | None


@dataclass(frozen=True)
class ProviderObservation:
    channel_id: str
    provider: str | None
    state: ProviderState
    observed_at: str
    provider_fetched_at: str | None
    reset_at: str | None
    source: str | None
    reason_code: ReasonCode
    windows_summary: tuple[UsageWindowSummary, ...]
    probe_exit_code: int | None
    timed_out: bool


def utc_rfc3339(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be offset-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class ProviderObservationClassifier:
    """Classifies only provider evidence with an explicit implementation."""

    def classify(
        self,
        *,
        channel_id: str,
        usage: HermesUsageDocument,
        observed_at: datetime,
        probe_exit_code: int = 0,
    ) -> ProviderObservation:
        expected_provider = CHANNEL_PROVIDERS.get(channel_id)
        if expected_provider != usage.provider:
            return self.unknown(
                channel_id=channel_id,
                provider=usage.provider,
                observed_at=observed_at,
                probe_exit_code=probe_exit_code,
                reason_code=ReasonCode.PROVIDER_UNSUPPORTED,
            )
        summaries = tuple(self._window_summary(window) for window in usage.windows)
        if usage.unavailable_reason is not None:
            return ProviderObservation(
                channel_id=channel_id,
                provider=usage.provider,
                state=ProviderState.UNKNOWN,
                observed_at=utc_rfc3339(observed_at),
                provider_fetched_at=utc_rfc3339(usage.fetched_at),
                reset_at=None,
                source=usage.source,
                reason_code=ReasonCode.PROBE_UNAVAILABLE,
                windows_summary=summaries,
                probe_exit_code=probe_exit_code,
                timed_out=False,
            )
        exhausted = tuple(window for window in usage.windows if window.used_percent >= 100)
        if exhausted:
            reset_at = None
            if all(window.resets_at is not None for window in exhausted):
                reset_at = utc_rfc3339(max(window.resets_at for window in exhausted if window.resets_at is not None))
            return ProviderObservation(
                channel_id=channel_id,
                provider=usage.provider,
                state=ProviderState.QUOTA_EXHAUSTED,
                observed_at=utc_rfc3339(observed_at),
                provider_fetched_at=utc_rfc3339(usage.fetched_at),
                reset_at=reset_at,
                source=usage.source,
                reason_code=ReasonCode.USAGE_WINDOW_EXHAUSTED,
                windows_summary=summaries,
                probe_exit_code=probe_exit_code,
                timed_out=False,
            )
        return ProviderObservation(
            channel_id=channel_id,
            provider=usage.provider,
            state=ProviderState.AVAILABLE,
            observed_at=utc_rfc3339(observed_at),
            provider_fetched_at=utc_rfc3339(usage.fetched_at),
            reset_at=None,
            source=usage.source,
            reason_code=ReasonCode.USAGE_AVAILABLE,
            windows_summary=summaries,
            probe_exit_code=probe_exit_code,
            timed_out=False,
        )

    @staticmethod
    def unknown(
        *,
        channel_id: str,
        provider: str | None,
        observed_at: datetime,
        probe_exit_code: int | None,
        reason_code: ReasonCode,
    ) -> ProviderObservation:
        return ProviderObservation(
            channel_id=channel_id,
            provider=provider,
            state=ProviderState.UNKNOWN,
            observed_at=utc_rfc3339(observed_at),
            provider_fetched_at=None,
            reset_at=None,
            source=None,
            reason_code=reason_code,
            windows_summary=(),
            probe_exit_code=probe_exit_code,
            timed_out=False,
        )

    @staticmethod
    def _window_summary(window: UsageWindow) -> UsageWindowSummary:
        return UsageWindowSummary(
            label=window.label,
            used_percent=window.used_percent,
            resets_at=None if window.resets_at is None else utc_rfc3339(window.resets_at),
        )
