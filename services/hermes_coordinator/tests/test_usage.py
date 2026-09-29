from __future__ import annotations

import json
from pathlib import Path

from helpers import SERVICE_ROOT, mode
from app.errors import UsageError
from app.usage import parse_usage_json, read_private_usage_file


def current_report() -> dict:
    return {
        "estimated_cost_usd": 0.25,
        "cost_status": "estimated",
        "cost_source": "fixture",
        "input_tokens": 3,
        "output_tokens": 4,
        "cache_read_tokens": 1,
        "cache_write_tokens": 0,
        "reasoning_tokens": 2,
        "total_tokens": 7,
        "api_calls": 2,
        "model": "test-model",
        "provider": "test",
        "session_id": "sid",
        "completed": True,
        "partial": False,
        "interrupted": False,
        "turn_exit_reason": "stop",
        "failed": False,
        "service_tier": None,
        "auxiliary": {
            "api_calls": 1,
            "input_tokens": 10,
            "output_tokens": 2,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "reasoning_tokens": 0,
            "estimated_cost_usd": 0.01,
            "total_tokens": 12,
            "by_task": {"title_generation": {
                "api_calls": 1,
                "input_tokens": 10,
                "output_tokens": 2,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
                "reasoning_tokens": 0,
                "estimated_cost_usd": 0.01,
            }},
        },
        "total_including_auxiliary": {
            "estimated_cost_usd": 0.26,
            "total_tokens": 19,
            "api_calls": 3,
        },
    }


def test_current_hermes_usage_schema_is_parsed() -> None:
    usage = parse_usage_json(json.dumps(current_report()))

    assert usage.model == "test-model"
    assert usage.provider == "test"
    assert usage.api_calls == 2
    assert usage.total_api_calls == 3
    assert usage.cache_read_tokens == 1
    assert usage.estimated_cost_usd == 0.25
    assert usage.completed is True
    assert usage.failed is False


def test_usage_requires_current_supported_schema() -> None:
    invalid = current_report()
    invalid["unexpected"] = 4
    for value in ["[]", '{"model":"a"}', json.dumps(invalid)]:
        try:
            parse_usage_json(value)
        except UsageError:
            continue
        raise AssertionError("invalid usage was accepted")


def test_usage_rejects_negative_nonfinite_duplicate_and_unbounded_values() -> None:
    negative = current_report()
    negative["api_calls"] = -1
    nonfinite = json.dumps(current_report()).replace('"api_calls": 2', '"api_calls": NaN', 1)
    duplicate = json.dumps(current_report()).replace(
        '"model": "test-model"', '"model": "test-model", "model": "other"', 1
    )
    unbounded = current_report()
    unbounded["model"] = "x" * 257
    for value in [json.dumps(negative), nonfinite, duplicate, json.dumps(unbounded)]:
        try:
            parse_usage_json(value)
        except UsageError:
            continue
        raise AssertionError("invalid usage was accepted")


def test_total_including_auxiliary_cannot_underreport_main_calls() -> None:
    value = current_report()
    value["total_including_auxiliary"]["api_calls"] = 1
    try:
        parse_usage_json(json.dumps(value))
    except UsageError:
        return
    raise AssertionError("underreported total api calls were accepted")


def test_private_usage_file_requires_0600(tmp_path: Path) -> None:
    path = tmp_path / "usage.json"
    path.write_text(json.dumps(current_report()), encoding="utf-8")
    path.chmod(0o600)

    usage = read_private_usage_file(path)

    assert usage.api_calls == 2
    assert usage.total_api_calls == 3
    assert mode(path) == 0o600
