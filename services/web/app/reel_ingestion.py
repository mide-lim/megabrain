from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlsplit

from psycopg.rows import dict_row

from app import database

SHORTCODE_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
REEL_PATH_PATTERN = re.compile(r"^/(?:reel|reels)/([A-Za-z0-9_-]+)/?$")
ALLOWED_HOSTS = {"instagram.com", "www.instagram.com"}

INSERT_REEL_QUERY = """
INSERT INTO app.reels (
    shortcode,
    original_url,
    source,
    status,
    telegram_chat_id,
    telegram_user_id,
    telegram_message_id,
    raw_message,
    received_at
)
VALUES (
    %s,
    %s,
    'instagram',
    'received',
    %s,
    %s,
    %s,
    %s,
    CURRENT_TIMESTAMP
)
ON CONFLICT DO NOTHING
RETURNING
    id,
    shortcode,
    original_url,
    source,
    status,
    telegram_chat_id,
    telegram_user_id,
    telegram_message_id,
    raw_message,
    received_at
"""

SELECT_REEL_IDENTITY_QUERY = """
SELECT
    id,
    shortcode,
    original_url,
    source,
    status,
    telegram_chat_id,
    telegram_user_id,
    telegram_message_id,
    raw_message,
    received_at
FROM app.reels
WHERE shortcode = %s
   OR original_url = %s
"""


class InvalidReelUrl(ValueError):
    """Raised when an Instagram Reel URL does not satisfy the registration contract."""


class ReelIdentityConflict(RuntimeError):
    """Raised when persisted Reel natural identities disagree."""


class ReelRegistrationUnavailable(RuntimeError):
    """Raised when registration cannot safely determine a persisted Reel."""


@dataclass(frozen=True)
class TelegramAdapterMetadata:
    telegram_chat_id: int
    telegram_user_id: int
    telegram_message_id: int
    raw_message: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("telegram_user_id", "telegram_message_id"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{field_name} must be a positive integer")
        if (
            isinstance(self.telegram_chat_id, bool)
            or not isinstance(self.telegram_chat_id, int)
            or self.telegram_chat_id == 0
        ):
            raise ValueError("telegram_chat_id must be a non-zero integer")
        if self.raw_message is not None and not isinstance(self.raw_message, str):
            raise ValueError("raw_message must be a string or None")


@dataclass(frozen=True)
class RegisteredReel:
    id: int
    shortcode: str
    original_url: str
    source: str
    status: str
    telegram_chat_id: int | None
    telegram_user_id: int | None
    telegram_message_id: int | None
    raw_message: str | None
    received_at: Any
    created: bool


def normalize_instagram_reel_url(raw_url: str) -> tuple[str, str]:
    """Validate an Instagram Reel URL and return its canonical URL and shortcode."""
    if not isinstance(raw_url, str) or not raw_url or raw_url != raw_url.strip():
        raise InvalidReelUrl("Invalid Instagram Reel URL")

    try:
        parsed = urlsplit(raw_url)
        port = parsed.port
    except (TypeError, ValueError):
        raise InvalidReelUrl("Invalid Instagram Reel URL") from None

    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise InvalidReelUrl("Invalid Instagram Reel URL")
    if parsed.username is not None or parsed.password is not None:
        raise InvalidReelUrl("Invalid Instagram Reel URL")
    if parsed.netloc.endswith(":"):
        raise InvalidReelUrl("Invalid Instagram Reel URL")

    hostname = parsed.hostname
    if hostname is None or hostname.lower() not in ALLOWED_HOSTS:
        raise InvalidReelUrl("Invalid Instagram Reel URL")
    if hostname.endswith("."):
        raise InvalidReelUrl("Invalid Instagram Reel URL")

    default_port = 80 if parsed.scheme == "http" else 443
    if port is not None and port != default_port:
        raise InvalidReelUrl("Invalid Instagram Reel URL")

    path_match = REEL_PATH_PATTERN.fullmatch(parsed.path)
    if path_match is None:
        raise InvalidReelUrl("Invalid Instagram Reel URL")

    shortcode = path_match.group(1)
    if not SHORTCODE_PATTERN.fullmatch(shortcode):
        raise InvalidReelUrl("Invalid Instagram Reel URL")

    return f"https://www.instagram.com/reel/{shortcode}/", shortcode


def register_reel(
    raw_url: str,
    telegram_metadata: TelegramAdapterMetadata | None = None,
) -> RegisteredReel:
    """Create a Reel or return the exact existing Reel identified by its URL."""
    canonical_url, shortcode = normalize_instagram_reel_url(raw_url)
    metadata_values = _telegram_values(telegram_metadata)

    try:
        with (
            database.connect() as connection,
            connection.cursor(row_factory=dict_row) as cursor,
        ):
            cursor.execute(
                INSERT_REEL_QUERY,
                (shortcode, canonical_url, *metadata_values),
            )
            inserted = cursor.fetchone()
            if inserted is not None:
                return _registered_reel(inserted, created=True)

            cursor.execute(SELECT_REEL_IDENTITY_QUERY, (shortcode, canonical_url))
            return _resolve_existing(cursor.fetchall(), shortcode, canonical_url)
    except (ReelIdentityConflict, ReelRegistrationUnavailable):
        raise
    except Exception:
        raise ReelRegistrationUnavailable(
            "Reel registration temporarily unavailable"
        ) from None


def _telegram_values(
    telegram_metadata: TelegramAdapterMetadata | None,
) -> tuple[int | None, int | None, int | None, str | None]:
    if telegram_metadata is None:
        return None, None, None, None
    if not isinstance(telegram_metadata, TelegramAdapterMetadata):
        raise ValueError("telegram_metadata must be TelegramAdapterMetadata or None")
    return (
        telegram_metadata.telegram_chat_id,
        telegram_metadata.telegram_user_id,
        telegram_metadata.telegram_message_id,
        telegram_metadata.raw_message,
    )


def _resolve_existing(
    rows: list[Mapping[str, Any]],
    shortcode: str,
    canonical_url: str,
) -> RegisteredReel:
    if len(rows) != 1:
        raise ReelRegistrationUnavailable("Reel registration temporarily unavailable")

    row = rows[0]
    persisted_shortcode = row["shortcode"]
    persisted_url = row["original_url"]
    if persisted_shortcode == shortcode and persisted_url == canonical_url:
        return _registered_reel(row, created=False)
    if persisted_shortcode == shortcode or persisted_url == canonical_url:
        raise ReelIdentityConflict("Reel natural identity conflict")
    raise ReelRegistrationUnavailable("Reel registration temporarily unavailable")


def _registered_reel(row: Mapping[str, Any], *, created: bool) -> RegisteredReel:
    return RegisteredReel(
        id=row["id"],
        shortcode=row["shortcode"],
        original_url=row["original_url"],
        source=row["source"],
        status=row["status"],
        telegram_chat_id=row["telegram_chat_id"],
        telegram_user_id=row["telegram_user_id"],
        telegram_message_id=row["telegram_message_id"],
        raw_message=row["raw_message"],
        received_at=row["received_at"],
        created=created,
    )
