-- F6 I1-B legacy transcription lifecycle reconciliation.
--
-- SOURCE ARTIFACT ONLY. Production execution remains separately human-gated.
-- This forward data migration corrects only the conservative F4 lifecycle
-- projection when an accepted terminal enrichment already exists for the exact
-- immutable source tuple.
BEGIN;

DO $$
DECLARE
    required_reel_column_count INTEGER;
    required_enrichment_column_count INTEGER;
    required_lifecycle_constraint_count INTEGER;
BEGIN
    IF to_regclass('app.reels') IS NULL THEN
        RAISE EXCEPTION 'app.reels is required for F6 I1-B reconciliation';
    END IF;

    IF to_regclass('app.reel_enrichments') IS NULL THEN
        RAISE EXCEPTION 'app.reel_enrichments is required for F6 I1-B reconciliation';
    END IF;

    SELECT count(*)
    INTO required_reel_column_count
    FROM information_schema.columns
    WHERE table_schema = 'app'
      AND table_name = 'reels'
      AND column_name IN (
          'download_status',
          'transcription_status',
          'transcription_attempt_id',
          'object_key',
          'sha256',
          'updated_at'
      );

    IF required_reel_column_count <> 6 THEN
        RAISE EXCEPTION 'required app.reels lifecycle and immutable source columns are missing';
    END IF;

    SELECT count(*)
    INTO required_enrichment_column_count
    FROM information_schema.columns
    WHERE table_schema = 'app'
      AND table_name = 'reel_enrichments'
      AND column_name IN (
          'reel_id',
          'source_object_key',
          'source_sha256',
          'pipeline_version'
      );

    IF required_enrichment_column_count <> 4 THEN
        RAISE EXCEPTION 'required app.reel_enrichments applicability columns are missing';
    END IF;

    SELECT count(*)
    INTO required_lifecycle_constraint_count
    FROM pg_constraint
    WHERE conrelid = 'app.reels'::regclass
      AND conname IN (
          'reels_transcription_status_check',
          'reels_transcription_attempt_state_check'
      )
      AND contype = 'c';

    IF required_lifecycle_constraint_count <> 2 THEN
        RAISE EXCEPTION 'F4 transcription lifecycle constraints are required for F6 I1-B reconciliation';
    END IF;
END $$;

UPDATE app.reels AS reel
SET
    transcription_status = 'completed',
    updated_at = NOW()
WHERE reel.download_status = 'downloaded'
  AND reel.transcription_status IN ('not_requested', 'queued')
  AND reel.transcription_attempt_id IS NULL
  AND EXISTS (
      SELECT 1
      FROM app.reel_enrichments AS enrichment
      WHERE enrichment.reel_id = reel.id
        AND enrichment.source_object_key = reel.object_key
        AND enrichment.source_sha256 = reel.sha256
        AND enrichment.pipeline_version = 'sprint-3-v1'
  );

COMMIT;
