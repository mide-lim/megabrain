from __future__ import annotations

from pathlib import Path

import pytest

from app import database, reel_ingestion
from app.reel_ingestion import (
    INSERT_REEL_QUERY,
    SELECT_REEL_IDENTITY_QUERY,
    InvalidReelUrl,
    ReelIdentityConflict,
    ReelRegistrationUnavailable,
    TelegramAdapterMetadata,
    normalize_instagram_reel_url,
    register_reel,
)

MIGRATION_PATH = (
    Path(__file__).resolve().parents[3]
    / "infra/postgres/migrations/004_f3_web_reel_ingestion.sql"
)


def persisted_reel(**overrides):
    row = {
        "id": 42,
        "shortcode": "abc_123",
        "original_url": "https://www.instagram.com/reel/abc_123/",
        "source": "instagram",
        "status": "received",
        "telegram_chat_id": None,
        "telegram_user_id": None,
        "telegram_message_id": None,
        "raw_message": None,
        "received_at": "registration-time",
    }
    row.update(overrides)
    return row


class FakeCursor:
    def __init__(self, *, insert_result=None, existing_rows=None, error=None) -> None:
        self.insert_result = insert_result
        self.existing_rows = [] if existing_rows is None else existing_rows
        self.error = error
        self.calls = []
        self._last_query = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def execute(self, query, parameters):
        if self.error is not None:
            raise self.error
        self.calls.append((query, parameters))
        self._last_query = query

    def fetchone(self):
        if self._last_query == INSERT_REEL_QUERY:
            return self.insert_result
        return None

    def fetchall(self):
        if self._last_query == SELECT_REEL_IDENTITY_QUERY:
            return self.existing_rows
        return []


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self.cursor_instance = cursor
        self.cursor_arguments = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def cursor(self, **kwargs):
        self.cursor_arguments.append(kwargs)
        return self.cursor_instance


def configure_database(monkeypatch, cursor: FakeCursor) -> FakeConnection:
    connection = FakeConnection(cursor)
    monkeypatch.setattr(database, "connect", lambda: connection)
    return connection


@pytest.mark.parametrize(
    ("raw_url", "expected_shortcode"),
    [
        ("https://instagram.com/reel/abc_123", "abc_123"),
        ("https://instagram.com/reels/abc_123", "abc_123"),
        ("https://www.instagram.com/reel/abc_123/", "abc_123"),
        ("https://instagram.com/reel/abc_123?utm_source=telegram", "abc_123"),
        ("https://instagram.com/reel/abc_123#caption", "abc_123"),
        ("https://instagram.com/reel/abc_123", "abc_123"),
        ("https://www.instagram.com/reel/abc_123", "abc_123"),
        ("http://instagram.com/reel/abc_123", "abc_123"),
    ],
)
def test_normalize_instagram_reel_url_accepts_approved_forms(
    raw_url: str, expected_shortcode: str
) -> None:
    canonical_url, shortcode = normalize_instagram_reel_url(raw_url)

    assert shortcode == expected_shortcode
    assert canonical_url == "https://www.instagram.com/reel/abc_123/"


@pytest.mark.parametrize(
    "raw_url",
    [
        "https://instagram.com/reel/bad.code",
        "https://example.com/reel/abc_123",
        "https://instagram.com.example.com/reel/abc_123",
        "https://user:password@instagram.com/reel/abc_123",
        "https://instagram.com:444/reel/abc_123",
        "https://instagram.com:bad/reel/abc_123",
        "https://instagram.com/p/abc_123",
        "https://instagram.com/reel/abc_123/extra",
        "https://instagram.com/reel/",
        "not a URL",
        "/reel/abc_123",
        "ftp://instagram.com/reel/abc_123",
        "https://reels.instagram.com/reel/abc_123",
        "https://instagram.com./reel/abc_123",
        "https://instagram.com/reel/abc%2F123",
    ],
)
def test_normalize_instagram_reel_url_rejects_unapproved_forms(raw_url: str) -> None:
    with pytest.raises(InvalidReelUrl):
        normalize_instagram_reel_url(raw_url)


def test_register_reel_creates_source_neutral_reel_without_telegram_metadata(
    monkeypatch,
) -> None:
    cursor = FakeCursor(insert_result=persisted_reel())
    connection = configure_database(monkeypatch, cursor)

    registered = register_reel("http://instagram.com/reels/abc_123?from=telegram")

    assert registered.created is True
    assert registered.source == "instagram"
    assert registered.status == "received"
    assert registered.original_url == "https://www.instagram.com/reel/abc_123/"
    assert registered.telegram_chat_id is None
    assert registered.telegram_user_id is None
    assert registered.telegram_message_id is None
    assert registered.raw_message is None
    assert connection.cursor_arguments == [{"row_factory": reel_ingestion.dict_row}]
    assert cursor.calls == [
        (
            INSERT_REEL_QUERY,
            (
                "abc_123",
                "https://www.instagram.com/reel/abc_123/",
                None,
                None,
                None,
                None,
            ),
        )
    ]
    assert "CURRENT_TIMESTAMP" in INSERT_REEL_QUERY


def test_register_reel_persists_optional_telegram_adapter_metadata(monkeypatch) -> None:
    metadata = TelegramAdapterMetadata(101, 202, 303, "forwarded message")
    cursor = FakeCursor(
        insert_result=persisted_reel(
            telegram_chat_id=101,
            telegram_user_id=202,
            telegram_message_id=303,
            raw_message="forwarded message",
        )
    )
    configure_database(monkeypatch, cursor)

    registered = register_reel("https://instagram.com/reel/abc_123", metadata)

    assert registered.telegram_chat_id == 101
    assert registered.telegram_user_id == 202
    assert registered.telegram_message_id == 303
    assert registered.raw_message == "forwarded message"
    assert cursor.calls[0][1][-4:] == (101, 202, 303, "forwarded message")


@pytest.mark.parametrize("invalid_ids", [(0, 2, 3), (1, True, 3), (1, 2, -3)])
def test_telegram_metadata_requires_all_valid_ids(invalid_ids) -> None:
    with pytest.raises(ValueError):
        TelegramAdapterMetadata(*invalid_ids)


def test_register_reel_returns_exact_existing_reel_after_duplicate_insert(monkeypatch) -> None:
    cursor = FakeCursor(insert_result=None, existing_rows=[persisted_reel()])
    configure_database(monkeypatch, cursor)

    registered = register_reel("https://instagram.com/reels/abc_123")

    assert registered.created is False
    assert registered.id == 42
    assert cursor.calls == [
        (
            INSERT_REEL_QUERY,
            ("abc_123", "https://www.instagram.com/reel/abc_123/", None, None, None, None),
        ),
        (
            SELECT_REEL_IDENTITY_QUERY,
            ("abc_123", "https://www.instagram.com/reel/abc_123/"),
        ),
    ]


def test_simulated_concurrent_insert_loser_resolves_persisted_winner(monkeypatch) -> None:
    cursor = FakeCursor(insert_result=None, existing_rows=[persisted_reel(id=99)])
    configure_database(monkeypatch, cursor)

    registered = register_reel("https://instagram.com/reel/abc_123")

    assert registered.created is False
    assert registered.id == 99
    assert len(cursor.calls) == 2


def test_register_reel_rejects_same_shortcode_with_different_persisted_url(monkeypatch) -> None:
    cursor = FakeCursor(
        insert_result=None,
        existing_rows=[persisted_reel(original_url="https://www.instagram.com/reel/other/")],
    )
    configure_database(monkeypatch, cursor)

    with pytest.raises(ReelIdentityConflict):
        register_reel("https://instagram.com/reel/abc_123")


def test_register_reel_rejects_same_url_with_different_persisted_shortcode(monkeypatch) -> None:
    cursor = FakeCursor(
        insert_result=None,
        existing_rows=[persisted_reel(shortcode="other")],
    )
    configure_database(monkeypatch, cursor)

    with pytest.raises(ReelIdentityConflict):
        register_reel("https://instagram.com/reel/abc_123")


def test_register_reel_rejects_unresolvable_zero_result_duplicate(monkeypatch) -> None:
    cursor = FakeCursor(insert_result=None, existing_rows=[])
    configure_database(monkeypatch, cursor)

    with pytest.raises(ReelRegistrationUnavailable, match="temporarily unavailable"):
        register_reel("https://instagram.com/reel/abc_123")


def test_register_reel_rejects_multiple_conflicting_identities(monkeypatch) -> None:
    cursor = FakeCursor(
        insert_result=None,
        existing_rows=[persisted_reel(), persisted_reel(id=43, shortcode="other")],
    )
    configure_database(monkeypatch, cursor)

    with pytest.raises(ReelRegistrationUnavailable, match="temporarily unavailable"):
        register_reel("https://instagram.com/reel/abc_123")


def test_database_driver_error_is_safely_hidden(monkeypatch) -> None:
    cursor = FakeCursor(error=RuntimeError("postgres://sensitive-user:password@example"))
    configure_database(monkeypatch, cursor)

    with pytest.raises(ReelRegistrationUnavailable) as error:
        register_reel("https://instagram.com/reel/abc_123")

    assert str(error.value) == "Reel registration temporarily unavailable"
    assert "postgres" not in str(error.value)
    assert error.value.__cause__ is None


def test_registration_sql_never_mutates_reels() -> None:
    assert "UPDATE" not in INSERT_REEL_QUERY.upper()
    assert "UPDATE" not in SELECT_REEL_IDENTITY_QUERY.upper()


def test_f3_migration_contains_only_required_telegram_nullability_changes() -> None:
    assert MIGRATION_PATH.is_file(), f"missing migration: {MIGRATION_PATH}"
    sql = MIGRATION_PATH.read_text(encoding="utf-8")
    normalized = " ".join(sql.upper().split())

    for column_name in (
        "TELEGRAM_CHAT_ID",
        "TELEGRAM_USER_ID",
        "TELEGRAM_MESSAGE_ID",
    ):
        assert f"ALTER COLUMN {column_name} DROP NOT NULL" in normalized
    assert "RAW_MESSAGE" not in normalized
    assert "GRANT" not in normalized
    assert "DROP CONSTRAINT" not in normalized
    assert "UNIQUE" not in normalized
    assert "INDEX" not in normalized
    assert "OBJECT_KEY" not in normalized
    assert normalized == (
        "-- F3.1 WEB REEL INGESTION COMPATIBILITY. ALTER TABLE APP.REELS "
        "ALTER COLUMN TELEGRAM_CHAT_ID DROP NOT NULL, ALTER COLUMN "
        "TELEGRAM_USER_ID DROP NOT NULL, ALTER COLUMN TELEGRAM_MESSAGE_ID "
        "DROP NOT NULL;"
    )
