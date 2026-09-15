from __future__ import annotations

import pytest

from app.reel_ingestion import INSERT_REEL_QUERY, SELECT_REEL_IDENTITY_QUERY
from app.reel_lifecycle import (
    CURATION_STATUS_INBOX,
    DOWNLOAD_STATUS_DOWNLOADED,
    DOWNLOAD_STATUS_DOWNLOADING,
    DOWNLOAD_STATUS_FAILED,
    DOWNLOAD_STATUS_RECEIVED,
    TRANSCRIPTION_STATUS_NOT_REQUESTED,
    LifecycleStatusError,
    default_reel_lifecycle,
    map_legacy_download_status,
    validate_curation_status,
    validate_download_status,
    validate_transcription_status,
)


@pytest.mark.parametrize(
    ("legacy_status", "download_status"),
    [
        ("received", DOWNLOAD_STATUS_RECEIVED),
        ("downloading", DOWNLOAD_STATUS_DOWNLOADING),
        ("downloaded", DOWNLOAD_STATUS_DOWNLOADED),
        ("download_failed", DOWNLOAD_STATUS_FAILED),
    ],
)
def test_legacy_download_statuses_map_to_explicit_download_lifecycle(
    legacy_status: str, download_status: str
) -> None:
    assert map_legacy_download_status(legacy_status) == download_status


def test_unknown_legacy_download_status_is_rejected() -> None:
    with pytest.raises(LifecycleStatusError, match="Unknown legacy download status"):
        map_legacy_download_status("invented")


def test_existing_reel_defaults_are_conservative_and_independent() -> None:
    lifecycle = default_reel_lifecycle()

    assert lifecycle == {
        "curation_status": CURATION_STATUS_INBOX,
        "transcription_status": TRANSCRIPTION_STATUS_NOT_REQUESTED,
    }


@pytest.mark.parametrize("value", ["received", "downloading", "downloaded", "failed"])
def test_download_status_accepts_only_approved_vocabulary(value: str) -> None:
    assert validate_download_status(value) == value


@pytest.mark.parametrize("value", ["inbox", "organized"])
def test_curation_status_accepts_only_approved_vocabulary(value: str) -> None:
    assert validate_curation_status(value) == value


@pytest.mark.parametrize(
    "value", ["not_requested", "queued", "processing", "completed", "failed"]
)
def test_transcription_status_accepts_only_approved_vocabulary(value: str) -> None:
    assert validate_transcription_status(value) == value


@pytest.mark.parametrize(
    "validator",
    [validate_download_status, validate_curation_status, validate_transcription_status],
)
def test_lifecycle_validators_reject_unapproved_values(validator) -> None:
    with pytest.raises(LifecycleStatusError):
        validator("organized_by_category")


def test_reel_registration_uses_download_status_without_legacy_status_column() -> None:
    for query in (INSERT_REEL_QUERY, SELECT_REEL_IDENTITY_QUERY):
        assert "download_status" in query
        assert "\n    status," not in query


def test_telegram_and_web_registration_share_the_same_download_lifecycle(monkeypatch) -> None:
    from app import database, reel_ingestion
    from tests.test_reel_ingestion import FakeConnection, FakeCursor, persisted_reel

    web_cursor = FakeCursor(insert_result=persisted_reel())
    telegram_cursor = FakeCursor(insert_result=persisted_reel())
    connections = iter((FakeConnection(web_cursor), FakeConnection(telegram_cursor)))
    monkeypatch.setattr(database, "connect", lambda: next(connections))

    from_web = reel_ingestion.register_reel("https://instagram.com/reel/web_source")
    from_telegram = reel_ingestion.register_reel(
        "https://instagram.com/reel/telegram_source",
        reel_ingestion.TelegramAdapterMetadata(101, 202, 303),
    )

    assert from_web.download_status == from_telegram.download_status == "received"
