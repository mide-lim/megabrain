from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATION = REPO_ROOT / "infra/postgres/migrations/006_f6_i1_b_legacy_transcription_reconciliation.sql"
DOCUMENTATION = REPO_ROOT / "docs/F6_INCIDENT_I1_B_LEGACY_LIFECYCLE_COMPATIBILITY.md"
CURRENT_PIPELINE_VERSION = "sprint-3-v1"


@dataclass(frozen=True)
class Reel:
    id: int
    download_status: str
    transcription_status: str
    transcription_attempt_id: str | None
    object_key: str
    sha256: str


@dataclass(frozen=True)
class Enrichment:
    reel_id: int
    source_object_key: str
    source_sha256: str
    pipeline_version: str
    outcome: str


def applicable(reel: Reel, enrichment: Enrichment) -> bool:
    return (
        enrichment.reel_id == reel.id
        and enrichment.source_object_key == reel.object_key
        and enrichment.source_sha256 == reel.sha256
        and enrichment.pipeline_version == CURRENT_PIPELINE_VERSION
    )


def qualify(reel: Reel, enrichments: list[Enrichment]) -> bool:
    return (
        reel.download_status == "downloaded"
        and reel.transcription_status in {"not_requested", "queued"}
        and reel.transcription_attempt_id is None
        and any(applicable(reel, enrichment) for enrichment in enrichments)
    )


def reconcile(reels: list[Reel], enrichments: list[Enrichment]) -> tuple[list[Reel], int]:
    reconciled = [
        replace(reel, transcription_status="completed") if qualify(reel, enrichments) else reel
        for reel in reels
    ]
    return reconciled, sum(before != after for before, after in zip(reels, reconciled))


def sql() -> str:
    assert MIGRATION.is_file(), f"missing I1-B migration: {MIGRATION}"
    return MIGRATION.read_text(encoding="utf-8")


def normalized_sql() -> str:
    return " ".join(sql().upper().split())


def reel(
    *,
    id: int = 101,
    download_status: str = "downloaded",
    transcription_status: str = "not_requested",
    transcription_attempt_id: str | None = None,
    object_key: str = "reels/101.mp4",
    sha256: str = "a" * 64,
) -> Reel:
    return Reel(
        id=id,
        download_status=download_status,
        transcription_status=transcription_status,
        transcription_attempt_id=transcription_attempt_id,
        object_key=object_key,
        sha256=sha256,
    )


def enrichment(
    candidate: Reel, **overrides: object
) -> Enrichment:
    value: dict[str, object] = {
        "reel_id": candidate.id,
        "source_object_key": candidate.object_key,
        "source_sha256": candidate.sha256,
        "pipeline_version": CURRENT_PIPELINE_VERSION,
        "outcome": "transcribed",
    }
    value.update(overrides)
    return Enrichment(**value)  # type: ignore[arg-type]


def test_migration_is_transactional_schema_preconditioned_and_targets_only_the_exact_tuple() -> None:
    migration = normalized_sql()

    assert migration.startswith("-- F6 I1-B")
    assert "BEGIN;" in migration
    assert migration.endswith("COMMIT;")
    assert "TO_REGCLASS('APP.REELS')" in migration
    assert "TO_REGCLASS('APP.REEL_ENRICHMENTS')" in migration
    for column in (
        "'DOWNLOAD_STATUS'",
        "'TRANSCRIPTION_STATUS'",
        "'TRANSCRIPTION_ATTEMPT_ID'",
        "'OBJECT_KEY'",
        "'SHA256'",
        "'UPDATED_AT'",
        "'REEL_ID'",
        "'SOURCE_OBJECT_KEY'",
        "'SOURCE_SHA256'",
        "'PIPELINE_VERSION'",
    ):
        assert column in migration
    assert "UPDATE APP.REELS AS REEL" in migration
    assert "SET TRANSCRIPTION_STATUS = 'COMPLETED', UPDATED_AT = NOW()" in migration
    assert "REEL.DOWNLOAD_STATUS = 'DOWNLOADED'" in migration
    assert "REEL.TRANSCRIPTION_STATUS IN ('NOT_REQUESTED', 'QUEUED')" in migration
    assert "REEL.TRANSCRIPTION_ATTEMPT_ID IS NULL" in migration
    assert "EXISTS ( SELECT 1 FROM APP.REEL_ENRICHMENTS AS ENRICHMENT" in migration
    for comparison in (
        "ENRICHMENT.REEL_ID = REEL.ID",
        "ENRICHMENT.SOURCE_OBJECT_KEY = REEL.OBJECT_KEY",
        "ENRICHMENT.SOURCE_SHA256 = REEL.SHA256",
        "ENRICHMENT.PIPELINE_VERSION = 'SPRINT-3-V1'",
    ):
        assert comparison in migration


def test_migration_reconciles_not_requested_and_queued_accepted_results_without_hard_coded_reel_ids() -> None:
    not_requested = reel(id=101, transcription_status="not_requested")
    queued = reel(id=102, transcription_status="queued")
    rows, changed = reconcile(
        [not_requested, queued],
        [enrichment(not_requested), enrichment(queued)],
    )

    assert [row.transcription_status for row in rows] == ["completed", "completed"]
    assert changed == 2
    assert not re.search(r"\b(?:12|15|18|20)\b", sql())


def test_empty_transcript_is_an_accepted_terminal_result_and_reconciles_to_completed() -> None:
    candidate = reel()
    rows, changed = reconcile([candidate], [enrichment(candidate, outcome="empty_transcript")])

    assert rows == [replace(candidate, transcription_status="completed")]
    assert changed == 1
    assert "OUTCOME" not in normalized_sql()


def test_migration_excludes_completed_rows_and_historical_failed_attempts_without_an_applicable_enrichment() -> None:
    completed = reel(transcription_status="completed")
    failed_attempt = reel(transcription_status="failed", transcription_attempt_id=None)
    rows, changed = reconcile([completed, failed_attempt], [])

    assert rows == [completed, failed_attempt]
    assert changed == 0


def test_migration_rejects_wrong_object_key_sha256_or_pipeline_version() -> None:
    candidate = reel()
    mismatches = [
        enrichment(candidate, source_object_key="reels/other.mp4"),
        enrichment(candidate, source_sha256="b" * 64),
        enrichment(candidate, pipeline_version="sprint-3-v2"),
    ]
    rows, changed = reconcile([candidate], mismatches)

    assert rows == [candidate]
    assert changed == 0


def test_migration_is_idempotent_and_never_models_attempt_or_enrichment_mutation() -> None:
    candidate = reel()
    enrichments = [enrichment(candidate)]

    first_rows, first_changed = reconcile([candidate], enrichments)
    second_rows, second_changed = reconcile(first_rows, enrichments)

    assert first_changed == 1
    assert second_changed == 0
    assert second_rows == first_rows
    migration = normalized_sql()
    update_segment = migration.split("UPDATE APP.REELS AS REEL", 1)[1]
    assert "TRANSCRIPTION_ATTEMPT_ID =" not in update_segment
    assert "UPDATE APP.REEL_ENRICHMENTS" not in migration
    assert "INSERT INTO APP.REEL_ENRICHMENTS" not in migration
    assert "DELETE FROM APP.REEL_ENRICHMENTS" not in migration
    assert "UPDATE APP.REEL_ENRICHMENT_ATTEMPTS" not in migration
    assert "INSERT INTO APP.REEL_ENRICHMENT_ATTEMPTS" not in migration
    assert "DELETE FROM APP.REEL_ENRICHMENT_ATTEMPTS" not in migration


def test_i1_b_documentation_records_human_gated_rollout_and_i1_c_boundary() -> None:
    assert DOCUMENTATION.is_file(), f"missing I1-B documentation: {DOCUMENTATION}"
    documentation = DOCUMENTATION.read_text(encoding="utf-8")

    for required_text in (
        "F4",
        "MGB-030",
        "source_object_key",
        "source_sha256",
        "pipeline_version",
        "006_f6_i1_b_legacy_transcription_reconciliation.sql",
        "empty_transcript",
        "reconciliation_required",
        "transcription_lifecycle_reconciliation_required",
        "HTTP 409",
        "megabrain_web",
        "human-gated",
        "I1-C",
    ):
        assert required_text in documentation
