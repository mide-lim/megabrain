from __future__ import annotations

import json

import pytest

from helpers import SERVICE_ROOT
from app.provider_usage import UsageParseError, parse_hermes_usage_json


def current_openai_codex_document() -> dict[str, object]:
    return {
        "provider": "openai-codex",
        "source": "codex account usage",
        "title": "Account limits",
        "plan": "Pro",
        "fetched_at": "2026-09-29T12:00:00+00:00",
        "windows": [
            {
                "label": "5h",
                "used_percent": 20,
                "resets_at": "2026-09-29T18:00:00+00:00",
                "detail": "Short-window account limit",
            },
            {
                "label": "weekly",
                "used_percent": 45.5,
                "resets_at": "2026-10-06T08:00:00+00:00",
                "detail": "Weekly account limit",
            },
        ],
        "details": ["Usage is account-level evidence."],
        "unavailable_reason": None,
    }


def test_current_hermes_usage_schema_is_parsed_and_timestamps_are_utc() -> None:
    usage = parse_hermes_usage_json(json.dumps(current_openai_codex_document()))

    assert usage.provider == "openai-codex"
    assert usage.plan == "Pro"
    assert usage.fetched_at.isoformat() == "2026-09-29T12:00:00+00:00"
    assert usage.windows[0].resets_at is not None
    assert usage.windows[0].resets_at.isoformat() == "2026-09-29T18:00:00+00:00"
    assert usage.windows[1].used_percent == 45.5


def test_usage_parser_rejects_malformed_duplicate_and_nonfinite_values() -> None:
    duplicate = json.dumps(current_openai_codex_document()).replace(
        '"provider": "openai-codex"', '"provider": "openai-codex", "provider": "other"', 1
    )
    nonfinite = json.dumps(current_openai_codex_document()).replace('"used_percent": 20', '"used_percent": NaN', 1)

    for value in ["{", duplicate, nonfinite]:
        with pytest.raises(UsageParseError):
            parse_hermes_usage_json(value)


@pytest.mark.parametrize("timestamp", ["not-a-timestamp", "2026-09-29T12:00:00"])
def test_usage_parser_rejects_invalid_or_naive_timestamps(timestamp: str) -> None:
    invalid = current_openai_codex_document()
    invalid["fetched_at"] = timestamp

    with pytest.raises(UsageParseError):
        parse_hermes_usage_json(json.dumps(invalid))


def test_usage_parser_rejects_negative_percent_and_excessive_collections() -> None:
    negative = current_openai_codex_document()
    negative["windows"] = [{
        "label": "5h", "used_percent": -0.01, "resets_at": None, "detail": "Account limit",
    }]
    many_windows = current_openai_codex_document()
    many_windows["windows"] = [{
        "label": "5h", "used_percent": 20, "resets_at": None, "detail": "Account limit",
    }] * 17
    many_details = current_openai_codex_document()
    many_details["details"] = ["detail"] * 33

    for value in [negative, many_windows, many_details]:
        with pytest.raises(UsageParseError):
            parse_hermes_usage_json(json.dumps(value))


def test_usage_parser_rejects_unknown_schema_and_unbounded_strings() -> None:
    unknown = current_openai_codex_document()
    unknown["unexpected"] = "value"
    unbounded = current_openai_codex_document()
    unbounded["windows"] = [{
        "label": "5h", "used_percent": 1, "resets_at": None, "detail": "x" * 2049,
    }]

    for value in [unknown, unbounded]:
        with pytest.raises(UsageParseError):
            parse_hermes_usage_json(json.dumps(value))
