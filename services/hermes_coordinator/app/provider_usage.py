from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

MAX_TOP_LEVEL_STRING_LENGTH = 512
MAX_DETAIL_STRING_LENGTH = 2048
MAX_WINDOWS = 16
MAX_DETAILS = 32

_ROOT_KEYS = {
    "provider",
    "source",
    "title",
    "plan",
    "fetched_at",
    "windows",
    "details",
    "unavailable_reason",
}
_WINDOW_KEYS = {"label", "used_percent", "resets_at", "detail"}
_RFC3339_OFFSET_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$"
)


class UsageParseError(ValueError):
    pass


class UsageSchemaError(UsageParseError):
    pass


@dataclass(frozen=True)
class UsageWindow:
    label: str
    used_percent: float
    resets_at: datetime | None
    detail: str | None


@dataclass(frozen=True)
class HermesUsageDocument:
    provider: str
    source: str
    title: str
    plan: str | None
    fetched_at: datetime
    windows: tuple[UsageWindow, ...]
    details: tuple[str, ...]
    unavailable_reason: str | None


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise UsageParseError("duplicate JSON key")
        result[key] = value
    return result


def _reject_nonfinite(_value: str) -> None:
    raise UsageParseError("non-finite numeric value")


def _bounded_string(value: object, name: str, *, limit: int) -> str:
    if not isinstance(value, str) or not value or len(value) > limit:
        raise UsageParseError(f"invalid {name}")
    return value


def _optional_bounded_string(value: object, name: str, *, limit: int) -> str | None:
    if value is None:
        return None
    return _bounded_string(value, name, limit=limit)


def _parse_timestamp(value: object, name: str, *, optional: bool = False) -> datetime | None:
    if optional and value is None:
        return None
    if not isinstance(value, str) or not _RFC3339_OFFSET_TIMESTAMP.fullmatch(value):
        raise UsageParseError(f"invalid {name}")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as exc:
        raise UsageParseError(f"invalid {name}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise UsageParseError(f"invalid {name}")
    return parsed.astimezone(timezone.utc)


def _parse_window(value: object) -> UsageWindow:
    if not isinstance(value, dict) or set(value) != _WINDOW_KEYS:
        raise UsageSchemaError("unsupported window schema")
    used_percent = value["used_percent"]
    if isinstance(used_percent, bool) or not isinstance(used_percent, (int, float)):
        raise UsageParseError("invalid used_percent")
    if not math.isfinite(used_percent) or used_percent < 0:
        raise UsageParseError("invalid used_percent")
    return UsageWindow(
        label=_bounded_string(value["label"], "window label", limit=MAX_TOP_LEVEL_STRING_LENGTH),
        used_percent=float(used_percent),
        resets_at=_parse_timestamp(value["resets_at"], "resets_at", optional=True),
        detail=_optional_bounded_string(value["detail"], "window detail", limit=MAX_DETAIL_STRING_LENGTH),
    )


def parse_hermes_usage_json(text: str | bytes) -> HermesUsageDocument:
    try:
        raw = json.loads(text, object_pairs_hook=_reject_duplicate_keys, parse_constant=_reject_nonfinite)
    except (json.JSONDecodeError, UnicodeDecodeError, UsageParseError) as exc:
        raise UsageParseError("malformed Hermes usage JSON") from exc
    if not isinstance(raw, dict):
        raise UsageParseError("Hermes usage root must be an object")
    if set(raw) != _ROOT_KEYS:
        raise UsageSchemaError("unsupported Hermes usage schema")
    windows = raw["windows"]
    details = raw["details"]
    if not isinstance(windows, list) or len(windows) > MAX_WINDOWS:
        raise UsageParseError("invalid usage windows")
    if not isinstance(details, list) or len(details) > MAX_DETAILS:
        raise UsageParseError("invalid usage details")
    fetched_at = _parse_timestamp(raw["fetched_at"], "fetched_at")
    assert fetched_at is not None
    return HermesUsageDocument(
        provider=_bounded_string(raw["provider"], "provider", limit=MAX_TOP_LEVEL_STRING_LENGTH),
        source=_bounded_string(raw["source"], "source", limit=MAX_TOP_LEVEL_STRING_LENGTH),
        title=_bounded_string(raw["title"], "title", limit=MAX_TOP_LEVEL_STRING_LENGTH),
        plan=_optional_bounded_string(raw["plan"], "plan", limit=MAX_TOP_LEVEL_STRING_LENGTH),
        fetched_at=fetched_at,
        windows=tuple(_parse_window(window) for window in windows),
        details=tuple(
            _bounded_string(detail, "usage detail", limit=MAX_DETAIL_STRING_LENGTH) for detail in details
        ),
        unavailable_reason=_optional_bounded_string(
            raw["unavailable_reason"], "unavailable_reason", limit=MAX_TOP_LEVEL_STRING_LENGTH
        ),
    )
