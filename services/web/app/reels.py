from __future__ import annotations

from psycopg.rows import dict_row

from app import database
from app.reel_lifecycle import validate_curation_status

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
