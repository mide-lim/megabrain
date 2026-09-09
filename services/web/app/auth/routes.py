from __future__ import annotations


class InvalidReturnPath(ValueError):
    """Raised when a return path is not an unambiguous local pathname."""


def validate_local_return_path(value: str) -> str:
    if not isinstance(value, str) or not value.startswith("/") or value.startswith("//"):
        raise InvalidReturnPath("return path must be a local pathname")

    if any(character in value for character in ("\\", "%", "?", "#", ":")) or any(
        ord(character) < 32 or ord(character) == 127 for character in value
    ):
        raise InvalidReturnPath("return path must be an unambiguous local pathname")

    return value
