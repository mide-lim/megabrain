from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


MIGRATION_PATH = Path(__file__).resolve().parents[1] / "migrations/005_f4_reel_lifecycle.sql"
TARGET_LIFECYCLE_COLUMNS = frozenset(
    {
        "download_status",
        "curation_status",
        "transcription_status",
        "transcription_attempt_id",
    }
)


@dataclass(frozen=True)
class LegacyLifecycleFixture:
    columns: frozenset[str]
    check_constraints: frozenset[str]
    status_values: tuple[str, ...]


# This fixture models the human-proven pre-F4 restore shape. It intentionally
# has no invented legacy constraint, including no reels_status_check.
PROVEN_PRODUCTION_LIKE_LEGACY = LegacyLifecycleFixture(
    columns=frozenset({"id", "status"}),
    check_constraints=frozenset(),
    status_values=("received", "downloading", "downloaded", "download_failed"),
)


def migration_sql() -> str:
    assert MIGRATION_PATH.is_file(), f"missing migration: {MIGRATION_PATH}"
    return MIGRATION_PATH.read_text(encoding="utf-8")


def normalized_sql() -> str:
    return " ".join(migration_sql().upper().split())


def test_proven_production_like_legacy_fixture_is_accepted_without_a_named_constraint() -> None:
    sql = normalized_sql()

    assert PROVEN_PRODUCTION_LIKE_LEGACY.columns & {"status"} == {"status"}
    assert not (PROVEN_PRODUCTION_LIKE_LEGACY.columns & TARGET_LIFECYCLE_COLUMNS)
    assert PROVEN_PRODUCTION_LIKE_LEGACY.check_constraints == frozenset()
    assert set(PROVEN_PRODUCTION_LIKE_LEGACY.status_values) == {
        "received",
        "downloading",
        "downloaded",
        "download_failed",
    }
    assert "REELS_STATUS_CHECK" not in sql
    assert "DROP CONSTRAINT" not in sql
    assert "EXPECTED LEGACY LIFECYCLE SHAPE" in sql


def test_migration_preflight_rejects_null_and_unknown_legacy_statuses() -> None:
    sql = normalized_sql()

    assert "INFORMATION_SCHEMA.COLUMNS" in sql
    assert "COLUMN_NAME = 'STATUS'" in sql
    assert "STATUS IS NULL" in sql
    assert "NULL APP.REELS.STATUS VALUE" in sql
    assert "STATUS NOT IN ('RECEIVED', 'DOWNLOADING', 'DOWNLOADED', 'DOWNLOAD_FAILED')" in sql
    assert "UNKNOWN APP.REELS.STATUS VALUE" in sql
    assert "COALESCE(STATUS" not in sql


def test_migration_preflight_rejects_mixed_partial_and_replayed_lifecycle_shapes() -> None:
    sql = normalized_sql()

    for column in TARGET_LIFECYCLE_COLUMNS:
        assert f"'{column.upper()}'" in sql
    assert "TARGET_LIFECYCLE_COLUMN_COUNT" in sql
    assert "MIXED LEGACY AND F4 LIFECYCLE COLUMNS" in sql
    assert "PARTIAL F4 LIFECYCLE SCHEMA" in sql
    assert "F4 LIFECYCLE SCHEMA ALREADY COMPLETE" in sql
    assert "APP.REELS.STATUS IS REQUIRED" in sql
    assert "NOT REPLAY-SAFE" in sql


def test_migration_renames_status_and_maps_every_approved_legacy_value() -> None:
    sql = normalized_sql()

    assert "RENAME COLUMN STATUS TO DOWNLOAD_STATUS" in sql
    assert "DOWNLOAD_STATUS = 'FAILED'" in sql
    assert "WHERE DOWNLOAD_STATUS = 'DOWNLOAD_FAILED'" in sql
    assert not re.search(r"\bADD COLUMN STATUS\b", sql)
    assert not re.search(r"\bSET STATUS\s*=", sql)


def test_migration_preserves_rows_and_initializes_independent_lifecycle_defaults() -> None:
    sql = normalized_sql()

    assert "F4.LIFECYCLE_REEL_COUNT" in sql
    assert "SET_CONFIG(" in sql
    assert "CURRENT_SETTING('F4.LIFECYCLE_REEL_COUNT'" in sql
    assert "ROW COUNT CHANGED" in sql
    assert "ADD COLUMN CURATION_STATUS TEXT NOT NULL DEFAULT 'INBOX'" in sql
    assert "ADD COLUMN TRANSCRIPTION_STATUS TEXT NOT NULL DEFAULT 'NOT_REQUESTED'" in sql
    assert "CATEGORY" not in sql
    assert "DELETE FROM APP.REELS" not in sql
    assert "TRUNCATE" not in sql
    assert "DROP TABLE" not in sql


def test_migration_creates_and_verifies_target_lifecycle_constraints() -> None:
    sql = normalized_sql()

    assert "CHECK (DOWNLOAD_STATUS IN ('RECEIVED', 'DOWNLOADING', 'DOWNLOADED', 'FAILED'))" in sql
    assert "CHECK (CURATION_STATUS IN ('INBOX', 'ORGANIZED'))" in sql
    assert "CHECK (TRANSCRIPTION_STATUS IN ('NOT_REQUESTED', 'QUEUED', 'PROCESSING', 'COMPLETED', 'FAILED'))" in sql
    assert "REELS_DOWNLOAD_STATUS_CHECK" in sql
    assert "REELS_CURATION_STATUS_CHECK" in sql
    assert "REELS_TRANSCRIPTION_STATUS_CHECK" in sql
    assert "RESULTING REEL LIFECYCLE SHAPE IS INVALID" in sql
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
