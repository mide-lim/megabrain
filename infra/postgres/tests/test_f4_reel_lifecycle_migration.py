from __future__ import annotations

import re
from pathlib import Path


MIGRATION_PATH = Path(__file__).resolve().parents[1] / "migrations/005_f4_reel_lifecycle.sql"


def migration_sql() -> str:
    assert MIGRATION_PATH.is_file(), f"missing migration: {MIGRATION_PATH}"
    return MIGRATION_PATH.read_text(encoding="utf-8")


def normalized_sql() -> str:
    return " ".join(migration_sql().upper().split())


def test_migration_preflight_rejects_unknown_legacy_download_statuses() -> None:
    sql = normalized_sql()

    assert "INFORMATION_SCHEMA.COLUMNS" in sql
    assert "COLUMN_NAME = 'STATUS'" in sql
    assert "STATUS IS NULL OR STATUS NOT IN ('RECEIVED', 'DOWNLOADING', 'DOWNLOADED', 'DOWNLOAD_FAILED')" in sql
    assert "UNEXPECTED APP.REELS.STATUS VALUE" in sql
    assert "COALESCE(STATUS" not in sql


def test_migration_renames_status_and_maps_every_approved_legacy_value() -> None:
    sql = normalized_sql()

    assert "RENAME COLUMN STATUS TO DOWNLOAD_STATUS" in sql
    assert "DOWNLOAD_STATUS = 'FAILED'" in sql
    assert "WHERE DOWNLOAD_STATUS = 'DOWNLOAD_FAILED'" in sql
    assert not re.search(r"\bADD COLUMN STATUS\b", sql)
    assert not re.search(r"\bSET STATUS\s*=", sql)


def test_migration_adds_independent_lifecycle_defaults_and_constraints() -> None:
    sql = normalized_sql()

    assert "ADD COLUMN CURATION_STATUS TEXT NOT NULL DEFAULT 'INBOX'" in sql
    assert "ADD COLUMN TRANSCRIPTION_STATUS TEXT NOT NULL DEFAULT 'NOT_REQUESTED'" in sql
    assert "CHECK (DOWNLOAD_STATUS IN ('RECEIVED', 'DOWNLOADING', 'DOWNLOADED', 'FAILED'))" in sql
    assert "CHECK (CURATION_STATUS IN ('INBOX', 'ORGANIZED'))" in sql
    assert "CHECK (TRANSCRIPTION_STATUS IN ('NOT_REQUESTED', 'QUEUED', 'PROCESSING', 'COMPLETED', 'FAILED'))" in sql
    assert "CATEGORY" not in sql


def test_migration_preflights_expected_constraints_and_verifies_result() -> None:
    sql = normalized_sql()

    assert "REELS_STATUS_CHECK" in sql
    assert "DROP CONSTRAINT REELS_STATUS_CHECK" in sql
    assert "REELS_DOWNLOAD_STATUS_CHECK" in sql
    assert "REELS_CURATION_STATUS_CHECK" in sql
    assert "REELS_TRANSCRIPTION_STATUS_CHECK" in sql
    assert "RESULTING REEL LIFECYCLE CONSTRAINTS ARE MISSING" in sql
    assert "GRANT" not in sql
    assert "BEGIN;" in sql
    assert sql.endswith("COMMIT;")


def test_migration_adds_current_transcription_attempt_identity_for_stale_write_protection() -> None:
    sql = normalized_sql()

    assert "TO_REGCLASS('APP.REEL_ENRICHMENT_ATTEMPTS')" in sql
    assert "ADD COLUMN TRANSCRIPTION_ATTEMPT_ID UUID" in sql
    assert "REELS_TRANSCRIPTION_ATTEMPT_REEL_FK" in sql
    assert "FOREIGN KEY (TRANSCRIPTION_ATTEMPT_ID, ID)" in sql
    assert "REFERENCES APP.REEL_ENRICHMENT_ATTEMPTS (ATTEMPT_ID, REEL_ID)" in sql
    assert "DEFERRABLE INITIALLY DEFERRED" in sql
    assert "REELS_TRANSCRIPTION_ATTEMPT_STATE_CHECK" in sql
    assert "TRANSCRIPTION_STATUS = 'PROCESSING'" in sql
