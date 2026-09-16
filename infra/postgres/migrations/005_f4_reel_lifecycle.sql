-- F4.2 explicit Reel lifecycle persistence.
--
-- Production execution requires a separate human authorization. This migration
-- intentionally performs no per-row enrichment reconciliation: existing rows use
-- the conservative transcription_status='not_requested'. F4.3 synchronizes
-- only lifecycle events accepted after its workflow path begins.
--
-- The expected legacy lifecycle shape has app.reels.status and none of the F4
-- lifecycle columns. No legacy CHECK constraint is required or removed: the
-- explicit aggregate-only value preflight below is the compatibility contract.
BEGIN;

DO $$
DECLARE
    legacy_status_exists BOOLEAN;
    target_lifecycle_column_count INTEGER;
BEGIN
    IF to_regclass('app.reels') IS NULL THEN
        RAISE EXCEPTION 'app.reels is required for F4.2 lifecycle migration';
    END IF;

    IF to_regclass('app.reel_enrichment_attempts') IS NULL THEN
        RAISE EXCEPTION 'app.reel_enrichment_attempts is required for F4.3 lifecycle synchronization';
    END IF;

    SELECT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'app'
          AND table_name = 'reels'
          AND column_name = 'status'
    )
    INTO legacy_status_exists;

    SELECT count(*)
    INTO target_lifecycle_column_count
    FROM information_schema.columns
    WHERE table_schema = 'app'
      AND table_name = 'reels'
      AND column_name IN (
          'download_status',
          'curation_status',
          'transcription_status',
          'transcription_attempt_id'
      );

    IF legacy_status_exists THEN
        IF target_lifecycle_column_count <> 0 THEN
            RAISE EXCEPTION 'mixed legacy and F4 lifecycle columns are not replay-safe';
        END IF;
    ELSIF target_lifecycle_column_count = 4 THEN
        RAISE EXCEPTION 'F4 lifecycle schema already complete; migration is not replay-safe';
    ELSIF target_lifecycle_column_count <> 0 THEN
        RAISE EXCEPTION 'partial F4 lifecycle schema is not replay-safe';
    ELSE
        RAISE EXCEPTION 'app.reels.status is required for F4.2 lifecycle migration';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM app.reels
        WHERE status IS NULL
    ) THEN
        RAISE EXCEPTION 'null app.reels.status value prevents F4.2 lifecycle migration';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM app.reels
        WHERE status NOT IN ('received', 'downloading', 'downloaded', 'download_failed')
    ) THEN
        RAISE EXCEPTION 'unknown app.reels.status value prevents F4.2 lifecycle migration';
    END IF;

    PERFORM set_config(
        'f4.lifecycle_reel_count',
        (SELECT count(*)::TEXT FROM app.reels),
        TRUE
    );
END $$;

ALTER TABLE app.reels
    RENAME COLUMN status TO download_status;

UPDATE app.reels
SET download_status = 'failed'
WHERE download_status = 'download_failed';

ALTER TABLE app.reels
    ADD COLUMN curation_status TEXT NOT NULL DEFAULT 'inbox',
    ADD COLUMN transcription_status TEXT NOT NULL DEFAULT 'not_requested',
    ADD COLUMN transcription_attempt_id UUID,
    ADD CONSTRAINT reels_download_status_check
        CHECK (download_status IN ('received', 'downloading', 'downloaded', 'failed')),
    ADD CONSTRAINT reels_curation_status_check
        CHECK (curation_status IN ('inbox', 'organized')),
    ADD CONSTRAINT reels_transcription_status_check
        CHECK (transcription_status IN ('not_requested', 'queued', 'processing', 'completed', 'failed')),
    ADD CONSTRAINT reels_transcription_attempt_state_check
        CHECK (
            (transcription_status = 'processing' AND transcription_attempt_id IS NOT NULL)
            OR (transcription_status <> 'processing' AND transcription_attempt_id IS NULL)
        ),
    ADD CONSTRAINT reels_transcription_attempt_reel_fk
        FOREIGN KEY (transcription_attempt_id, id)
        REFERENCES app.reel_enrichment_attempts (attempt_id, reel_id)
        DEFERRABLE INITIALLY DEFERRED;

DO $$
DECLARE
    expected_row_count BIGINT;
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'app'
          AND table_name = 'reels'
          AND column_name = 'status'
    ) OR (
        SELECT count(*)
        FROM information_schema.columns
        WHERE table_schema = 'app'
          AND table_name = 'reels'
          AND column_name IN (
              'download_status',
              'curation_status',
              'transcription_status',
              'transcription_attempt_id'
          )
    ) <> 4 THEN
        RAISE EXCEPTION 'resulting Reel lifecycle shape is invalid';
    END IF;

    expected_row_count := current_setting('f4.lifecycle_reel_count', TRUE)::BIGINT;
    IF expected_row_count IS NULL
       OR (SELECT count(*) FROM app.reels) <> expected_row_count THEN
        RAISE EXCEPTION 'app.reels row count changed during F4.2 lifecycle migration';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM app.reels
        WHERE download_status IS NULL
           OR download_status NOT IN ('received', 'downloading', 'downloaded', 'failed')
           OR curation_status IS NULL
           OR curation_status NOT IN ('inbox', 'organized')
           OR transcription_status IS NULL
           OR transcription_status NOT IN ('not_requested', 'queued', 'processing', 'completed', 'failed')
           OR (transcription_status = 'processing' AND transcription_attempt_id IS NULL)
           OR (transcription_status <> 'processing' AND transcription_attempt_id IS NOT NULL)
    ) THEN
        RAISE EXCEPTION 'resulting app.reels lifecycle values are invalid';
    END IF;

    IF (
        SELECT count(*)
        FROM pg_constraint
        WHERE conrelid = 'app.reels'::regclass
          AND conname IN (
              'reels_download_status_check',
              'reels_curation_status_check',
              'reels_transcription_status_check',
              'reels_transcription_attempt_state_check',
              'reels_transcription_attempt_reel_fk'
          )
          AND (
              contype = 'c'
              OR conname = 'reels_transcription_attempt_reel_fk'
          )
    ) <> 5 THEN
        RAISE EXCEPTION 'resulting Reel lifecycle constraints are missing';
    END IF;
END $$;

COMMIT;
