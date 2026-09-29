"""Opaque AP0 identifiers using RFC 9562 UUIDv7-compatible values."""
from __future__ import annotations

import os
import re
import time
import uuid

PREFIXES = {"task", "rsrc", "evt", "gate", "chk", "corr"}
_ID_RE = re.compile(r"^(task|rsrc|evt|gate|chk|corr)_([0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})$")


def uuid7(now_ms: int | None = None, random_bytes=os.urandom) -> str:
    """Return lower-case UUIDv7 without using PID, MAC, or a pseudo-random seed."""
    if now_ms is None:
        now_ms = time.time_ns() // 1_000_000
    if not 0 <= now_ms < 1 << 48:
        raise ValueError("epoch milliseconds out of UUIDv7 range")
    # UUIDv7 has 48 timestamp bits, then 12 + 62 random bits.  Extra CSPRNG
    # bits are deliberately discarded rather than replaced with a counter.
    entropy = int.from_bytes(random_bytes(10), "big") & ((1 << 74) - 1)
    rand_a, rand_b = entropy >> 62, entropy & ((1 << 62) - 1)
    value = (now_ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    return str(uuid.UUID(int=value))


def generate_id(family: str, **kwargs: object) -> str:
    if family not in PREFIXES:
        raise ValueError("unsupported identifier family")
    return f"{family}_{uuid7(**kwargs)}"


def validate_id(value: str, family: str | None = None) -> bool:
    match = _ID_RE.fullmatch(value) if isinstance(value, str) else None
    return bool(match and (family is None or match.group(1) == family))
