from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from psycopg.rows import dict_row

from app import database
from app.reel_lifecycle import (
    DOWNLOAD_STATUS_DOWNLOADED,
    TRANSCRIPTION_STATUS_COMPLETED,
    TRANSCRIPTION_STATUS_PROCESSING,
    TRANSCRIPTION_STATUS_QUEUED,
    LifecycleStatusError,
    validate_curation_status,
    validate_download_status,
    validate_transcription_status,
)

CURRENT_TRANSCRIPTION_PIPELINE_VERSION = "sprint-3-v1"

APPLICABLE_ENRICHMENT_QUERY = """
    SELECT 1
    FROM app.reel_enrichments AS enrichment
    WHERE enrichment.reel_id = r.id
      AND enrichment.source_object_key = r.object_key
      AND enrichment.source_sha256 = r.sha256
      AND enrichment.pipeline_version = %s
"""

REEL_DETAIL_QUERY = """
SELECT
    r.id,
    r.shortcode,
    r.original_url,
    r.download_status,
    r.curation_status,
    r.transcription_status,
    r.title,
    r.creator,
    r.caption,
    r.duration_seconds,
    r.filename,
    r.mime_type,
    r.file_size_bytes,
    r.storage_provider,
    r.storage_bucket,
    r.object_key,
    r.received_at,
    r.downloaded_at,
    enrichment.completed_at AS enrichment_completed_at,
    enrichment.media_duration_seconds,
    enrichment.outcome AS enrichment_outcome,
    enrichment.transcript_text,
    enrichment.transcript_language
FROM app.reels AS r
LEFT JOIN LATERAL (
    SELECT
        completed_at,
        media_duration_seconds,
        outcome,
        transcript_text,
        transcript_language
    FROM app.reel_enrichments
    WHERE reel_id = r.id
    ORDER BY completed_at DESC, id DESC
    LIMIT 1
) AS enrichment ON TRUE
WHERE r.id = %s
"""

SET_CURATION_STATUS_QUERY = """
UPDATE app.reels
SET curation_status = %s
WHERE id = %s
RETURNING id, download_status, curation_status, transcription_status
"""

REQUEST_TRANSCRIPTION_QUERY = f"""
UPDATE app.reels AS r
SET
    transcription_status = 'queued',
    transcription_attempt_id = NULL,
    updated_at = NOW()
WHERE r.id = %s
  AND r.download_status = 'downloaded'
  AND r.transcription_status IN ('not_requested', 'failed')
  AND r.transcription_attempt_id IS NULL
  AND NOT EXISTS (
{APPLICABLE_ENRICHMENT_QUERY})
RETURNING id, download_status, curation_status, transcription_status
"""

REQUEST_TRANSCRIPTION_LIFECYCLE_QUERY = f"""
SELECT
    r.id,
    r.download_status,
    r.curation_status,
    r.transcription_status,
    r.transcription_attempt_id,
    EXISTS (
{APPLICABLE_ENRICHMENT_QUERY}) AS has_applicable_enrichment
FROM app.reels AS r
WHERE r.id = %s
"""

TranscriptionRequestOutcome = Literal[
    "accepted_new_request",
    "already_queued",
    "already_processing",
    "already_completed",
    "reconciliation_required",
    "not_ready",
    "not_found",
]


@dataclass(frozen=True)
class TranscriptionRequestResult:
    outcome: TranscriptionRequestOutcome
    lifecycle: dict[str, Any] | None


def fetch_reel(reel_id: int) -> dict | None:
    with (
        database.connect() as connection,
        connection.cursor(row_factory=dict_row) as cursor,
    ):
        cursor.execute(REEL_DETAIL_QUERY, (reel_id,))
        return cursor.fetchone()


def set_curation_status(reel_id: int, curation_status: str) -> dict | None:
    """Set the independent curation dimension without rewriting other lifecycle fields."""
    validated_status = validate_curation_status(curation_status)
    with (
        database.connect() as connection,
        connection.cursor(row_factory=dict_row) as cursor,
    ):
        cursor.execute(SET_CURATION_STATUS_QUERY, (validated_status, reel_id))
        return cursor.fetchone()


def _classify_transcription_lifecycle(row: dict[str, Any]) -> TranscriptionRequestResult:
    download_status = validate_download_status(row["download_status"])
    validate_curation_status(row["curation_status"])
    transcription_status = validate_transcription_status(row["transcription_status"])
    transcription_attempt_id = row["transcription_attempt_id"]

    if transcription_status == TRANSCRIPTION_STATUS_PROCESSING:
        if transcription_attempt_id is None:
            raise LifecycleStatusError("Processing transcription is missing its attempt")
    elif transcription_attempt_id is not None:
        raise LifecycleStatusError("Non-processing transcription has an attempt")

    has_applicable_enrichment = row["has_applicable_enrichment"]
    if not isinstance(has_applicable_enrichment, bool):
        raise LifecycleStatusError("Applicable enrichment state is invalid")

    lifecycle = {
        "id": row["id"],
        "download_status": download_status,
        "curation_status": row["curation_status"],
        "transcription_status": transcription_status,
    }

    if download_status != DOWNLOAD_STATUS_DOWNLOADED:
        return TranscriptionRequestResult("not_ready", lifecycle)
    if (
        transcription_status in {"not_requested", "failed"}
        and transcription_attempt_id is None
        and has_applicable_enrichment
    ):
        return TranscriptionRequestResult("reconciliation_required", lifecycle)
    if transcription_status == TRANSCRIPTION_STATUS_QUEUED:
        return TranscriptionRequestResult("already_queued", lifecycle)
    if transcription_status == TRANSCRIPTION_STATUS_PROCESSING:
        return TranscriptionRequestResult("already_processing", lifecycle)
    if transcription_status == TRANSCRIPTION_STATUS_COMPLETED:
        return TranscriptionRequestResult("already_completed", lifecycle)

    raise LifecycleStatusError("Eligible transcription request was not transitioned")


def request_transcription(reel_id: int) -> TranscriptionRequestResult:
    """Atomically queue one eligible transcription request or report current lifecycle."""
    with (
        database.connect() as connection,
        connection.cursor(row_factory=dict_row) as cursor,
    ):
        cursor.execute(
            REQUEST_TRANSCRIPTION_QUERY,
            (reel_id, CURRENT_TRANSCRIPTION_PIPELINE_VERSION),
        )
        transitioned = cursor.fetchone()
        if transitioned is not None:
            return TranscriptionRequestResult("accepted_new_request", transitioned)

        cursor.execute(
            REQUEST_TRANSCRIPTION_LIFECYCLE_QUERY,
            (reel_id, CURRENT_TRANSCRIPTION_PIPELINE_VERSION),
        )
        current = cursor.fetchone()

    if current is None:
        return TranscriptionRequestResult("not_found", None)
    return _classify_transcription_lifecycle(current)
