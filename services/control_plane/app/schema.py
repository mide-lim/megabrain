"""Secret-free bounded payload validation."""
from __future__ import annotations
from .models import canonical_json
_SECRET_MARKERS = ("password", "secret", "token", "capability_proof", "authorization", "private_key", "environment", "cookie")
def validate_secret_free(value: object, depth: int = 0) -> object:
    if depth > 16: raise ValueError("payload nesting exceeds bound")
    if isinstance(value, dict):
        if len(value) > 128: raise ValueError("payload has too many fields")
        for key, item in value.items():
            if not isinstance(key, str) or any(marker in key.lower() for marker in _SECRET_MARKERS):
                raise ValueError("secret-bearing field prohibited")
            validate_secret_free(item, depth + 1)
    elif isinstance(value, list):
        if len(value) > 512: raise ValueError("payload array exceeds bound")
        for item in value: validate_secret_free(item, depth + 1)
    elif not isinstance(value, (str, int, float, bool, type(None))): raise ValueError("unsupported payload type")
    canonical_json(value)
    return value
