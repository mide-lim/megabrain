"""Small validated AP0 transport/domain helpers; no ORM or unsafe serialization."""
from __future__ import annotations
import json, math, re
from datetime import UTC, datetime
from .errors import fail
from .ids import validate_id
_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")

def reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError("duplicate JSON object key")
        result[key] = value
    return result

def jcs_loads(text: str | bytes):
    return json.loads(text, object_pairs_hook=reject_duplicate_keys, parse_constant=lambda _x: (_ for _ in ()).throw(ValueError("non-finite JSON number")))

def _finite(value):
    if isinstance(value, float) and not math.isfinite(value): raise ValueError("non-finite JSON number")
    if isinstance(value, dict):
        for v in value.values(): _finite(v)
    elif isinstance(value, list):
        for v in value: _finite(v)

def jcs_dumps(value: object) -> str:
    _finite(value)
    # RFC 8785-compatible for AP0's bounded JSON subset: UTF-8, sorted keys,
    # no whitespace, no NaN/Infinity. Python escapes only required characters.
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)

def canonical_json(value: object) -> str:
    encoded = jcs_dumps(value)
    if jcs_loads(encoded) != value: raise ValueError("unsupported JSON value")
    return encoded

def require_canonical_json(text: str) -> object:
    parsed = jcs_loads(text)
    if canonical_json(parsed) != text: raise ValueError("JSON is not canonical")
    return parsed

def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")

def validate_timestamp(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", value):
        raise ValueError("timestamp must be UTC RFC3339 milliseconds")
    datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value

def require_semver(value: str) -> str:
    if not isinstance(value, str) or not _SEMVER.fullmatch(value): raise ValueError("invalid schema version")
    if value.split(".")[0] != "1": raise fail("UNSUPPORTED_SCHEMA", "unsupported schema major")
    return value

def require_id(value: str, family: str) -> str:
    if not validate_id(value, family): raise ValueError("invalid identifier")
    return value
