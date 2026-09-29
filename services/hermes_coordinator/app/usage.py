from __future__ import annotations

import json
import math
import os
import stat
from pathlib import Path
from typing import Any

from .errors import UsageError
from .models import UsageEvidence

MAX_USAGE_FILE_BYTES = 64 * 1024
MAX_USAGE_STRING_LENGTH = 256
MAX_USAGE_COUNTER = 10**15

_MAIN_KEYS = {
    "estimated_cost_usd", "cost_status", "cost_source", "input_tokens", "output_tokens",
    "cache_read_tokens", "cache_write_tokens", "reasoning_tokens", "total_tokens", "api_calls",
    "model", "provider", "session_id", "completed", "partial", "interrupted", "turn_exit_reason",
}
_REQUIRED_KEYS = _MAIN_KEYS | {"failed", "service_tier"}
_ALLOWED_KEYS = _REQUIRED_KEYS | {"auxiliary", "total_including_auxiliary", "failure"}
_AUX_COUNTERS = {
    "api_calls", "input_tokens", "output_tokens", "cache_read_tokens",
    "cache_write_tokens", "reasoning_tokens", "estimated_cost_usd",
}


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise UsageError("duplicate usage key")
        value[key] = item
    return value


def _reject_constant(_value: str) -> None:
    raise UsageError("non-finite numeric value")


def _optional_string(value: object, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > MAX_USAGE_STRING_LENGTH:
        raise UsageError(f"invalid {name}")
    return value


def _optional_counter(value: object, name: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= MAX_USAGE_COUNTER:
        raise UsageError(f"invalid {name}")
    return value


def _optional_cost(value: object, name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise UsageError(f"invalid {name}")
    if not math.isfinite(value) or not 0 <= value <= MAX_USAGE_COUNTER:
        raise UsageError(f"invalid {name}")
    return float(value)


def _optional_bool(value: object, name: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise UsageError(f"invalid {name}")
    return value


def _validate_auxiliary(value: object) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise UsageError("invalid auxiliary")
    expected = _AUX_COUNTERS | {"total_tokens", "by_task"}
    if set(value) != expected or not isinstance(value["by_task"], dict):
        raise UsageError("unsupported auxiliary schema")
    for key in _AUX_COUNTERS - {"estimated_cost_usd"}:
        _optional_counter(value[key], f"auxiliary.{key}")
    _optional_counter(value["total_tokens"], "auxiliary.total_tokens")
    _optional_cost(value["estimated_cost_usd"], "auxiliary.estimated_cost_usd")

    for task, counters in value["by_task"].items():
        _optional_string(task, "auxiliary task")
        if not isinstance(counters, dict) or set(counters) - _AUX_COUNTERS:
            raise UsageError("unsupported auxiliary task schema")
        for key, item in counters.items():
            if key == "estimated_cost_usd":
                _optional_cost(item, f"auxiliary.{task}.{key}")
            else:
                _optional_counter(item, f"auxiliary.{task}.{key}")


def _total_api_calls(value: object, main_calls: int | None) -> int | None:
    if value is None:
        return main_calls
    if not isinstance(value, dict) or set(value) != {"estimated_cost_usd", "total_tokens", "api_calls"}:
        raise UsageError("unsupported total_including_auxiliary schema")
    _optional_cost(value["estimated_cost_usd"], "total_including_auxiliary.estimated_cost_usd")
    _optional_counter(value["total_tokens"], "total_including_auxiliary.total_tokens")
    total = _optional_counter(value["api_calls"], "total_including_auxiliary.api_calls")
    if total is not None and main_calls is not None and total < main_calls:
        raise UsageError("total api_calls is below main-loop api_calls")
    return total


def parse_usage_json(text: str | bytes) -> UsageEvidence:
    try:
        raw = json.loads(text, object_pairs_hook=_reject_duplicate_keys, parse_constant=_reject_constant)
    except (json.JSONDecodeError, UnicodeDecodeError, UsageError) as exc:
        raise UsageError("malformed usage JSON") from exc

    if not isinstance(raw, dict):
        raise UsageError("usage root must be an object")
    if set(raw) - _ALLOWED_KEYS or _REQUIRED_KEYS - set(raw):
        raise UsageError("usage schema is unsupported")

    model = _optional_string(raw["model"], "model")
    provider = _optional_string(raw["provider"], "provider")
    api_calls = _optional_counter(raw["api_calls"], "api_calls")
    input_tokens = _optional_counter(raw["input_tokens"], "input_tokens")
    output_tokens = _optional_counter(raw["output_tokens"], "output_tokens")
    cache_read_tokens = _optional_counter(raw["cache_read_tokens"], "cache_read_tokens")
    cache_write_tokens = _optional_counter(raw["cache_write_tokens"], "cache_write_tokens")
    reasoning_tokens = _optional_counter(raw["reasoning_tokens"], "reasoning_tokens")
    total_tokens = _optional_counter(raw["total_tokens"], "total_tokens")
    estimated_cost_usd = _optional_cost(raw["estimated_cost_usd"], "estimated_cost_usd")
    completed = _optional_bool(raw["completed"], "completed")
    partial = _optional_bool(raw["partial"], "partial")
    interrupted = _optional_bool(raw["interrupted"], "interrupted")
    if not isinstance(raw["failed"], bool):
        raise UsageError("invalid failed")

    for key in ("cost_status", "cost_source", "session_id", "turn_exit_reason", "service_tier", "failure"):
        if key in raw:
            _optional_string(raw[key], key)

    _validate_auxiliary(raw.get("auxiliary"))
    total_api_calls = _total_api_calls(raw.get("total_including_auxiliary"), api_calls)

    return UsageEvidence(
        model=model,
        provider=provider,
        api_calls=api_calls,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
        reasoning_tokens=reasoning_tokens,
        total_tokens=total_tokens,
        estimated_cost_usd=estimated_cost_usd,
        total_api_calls=total_api_calls,
        completed=completed,
        partial=partial,
        interrupted=interrupted,
        failed=raw["failed"],
        turn_exit_reason=_optional_string(raw["turn_exit_reason"], "turn_exit_reason"),
    )


def read_private_usage_file(path: Path) -> UsageEvidence:
    metadata = os.lstat(path)
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise UsageError("usage file is unsafe")

    if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) != 0o600:
        raise UsageError("usage file is not private")
    if metadata.st_size > MAX_USAGE_FILE_BYTES:
        raise UsageError("usage file is too large")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
            raise UsageError("usage file changed during read")
        content = os.read(fd, MAX_USAGE_FILE_BYTES + 1)
    finally:
        os.close(fd)
    if len(content) > MAX_USAGE_FILE_BYTES:
        raise UsageError("usage file is too large")
    return parse_usage_json(content)
