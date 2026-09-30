from __future__ import annotations

import json
from datetime import datetime, timezone

from helpers import SERVICE_ROOT
from app.provider_classifier import ProviderObservationClassifier, ProviderState, ReasonCode
from app.provider_usage import parse_hermes_usage_json


def usage_document(*, windows: list[dict[str, object]], provider: str = "openai-codex") -> object:
    return parse_hermes_usage_json(json.dumps({
        "provider": provider,
        "source": "codex account usage",
        "title": "Account limits",
        "plan": "Pro",
        "fetched_at": "2026-09-29T12:00:00+00:00",
        "windows": windows,
        "details": ["Usage is account-level evidence."],
        "unavailable_reason": None,
    }))


def window(*, used_percent: float, resets_at: str | None = "2026-09-29T18:00:00+00:00") -> dict[str, object]:
    return {
        "label": "5h",
        "used_percent": used_percent,
        "resets_at": resets_at,
        "detail": "Account limit",
    }


def classify(document: object):
    return ProviderObservationClassifier().classify(
        channel_id="openai_codex",
        usage=document,
        observed_at=datetime(2026, 9, 29, 12, 1, tzinfo=timezone.utc),
    )


def test_below_account_limits_is_available() -> None:
    observation = classify(usage_document(windows=[window(used_percent=99.9)]))

    assert observation.state is ProviderState.AVAILABLE
    assert observation.reason_code is ReasonCode.USAGE_AVAILABLE
    assert observation.reset_at is None
    assert observation.provider_fetched_at == "2026-09-29T12:00:00Z"


def test_one_window_exactly_at_limit_is_quota_exhausted() -> None:
    observation = classify(usage_document(windows=[window(used_percent=100)]))

    assert observation.state is ProviderState.QUOTA_EXHAUSTED
    assert observation.reason_code is ReasonCode.USAGE_WINDOW_EXHAUSTED
    assert observation.reset_at == "2026-09-29T18:00:00Z"


def test_one_window_over_limit_is_quota_exhausted() -> None:
    observation = classify(usage_document(windows=[window(used_percent=101.25)]))

    assert observation.state is ProviderState.QUOTA_EXHAUSTED


def test_multiple_exhausted_windows_choose_the_latest_reset() -> None:
    observation = classify(usage_document(windows=[
        window(used_percent=100, resets_at="2026-09-29T18:00:00+00:00"),
        window(used_percent=100, resets_at="2026-09-30T08:00:00+00:00"),
    ]))

    assert observation.state is ProviderState.QUOTA_EXHAUSTED
    assert observation.reset_at == "2026-09-30T08:00:00Z"


def test_exhausted_window_without_a_reset_has_no_invented_reset() -> None:
    observation = classify(usage_document(windows=[window(used_percent=100, resets_at=None)]))

    assert observation.state is ProviderState.QUOTA_EXHAUSTED
    assert observation.reset_at is None


def test_unsupported_provider_fails_closed() -> None:
    observation = classify(usage_document(windows=[window(used_percent=0)], provider="other"))

    assert observation.state is ProviderState.UNKNOWN
    assert observation.reason_code is ReasonCode.PROVIDER_UNSUPPORTED
