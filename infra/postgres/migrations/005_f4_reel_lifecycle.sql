-- F4.2 explicit Reel lifecycle persistence.
--
-- Production execution requires a separate human authorization. This migration
-- intentionally performs no per-row enrichment inspection: existing rows use
-- the conservative transcription_status='not_requested' until F4.3 owns a
-- separately authorized reconciliation/synchronization design.
BEGIN;

DO $$
BEGIN
    IF to_regclass('app.reels') IS NULL THEN
        RAISE EXCEPTION 'app.reels is required for F4.2 lifecycle migration';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'app'
          AND table_name = 'reels'
          AND column_name = 'status'
    ) THEN
        RAISE EXCEPTION 'app.reels.status is required for F4.2 lifecycle migration';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'app'
          AND table_name = 'reels'
          AND column_name IN ('download_status', 'curation_status', 'transcription_status')
    ) THEN
        RAISE EXCEPTION 'F4.2 lifecycle columns already exist; migration is not replay-safe';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'app.reels'::regclass
          AND conname = 'reels_status_check'
          AND contype = 'c'
    ) THEN
        RAISE EXCEPTION 'app.reels.reels_status_check is required for F4.2 lifecycle migration';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM app.reels
        WHERE status IS NULL
           OR status NOT IN ('received', 'downloading', 'downloaded', 'download_failed')
    ) THEN
        RAISE EXCEPTION 'unexpected app.reels.status value prevents F4.2 lifecycle migration';
    END IF;
END $$;

ALTER TABLE app.reels
    RENAME COLUMN status TO download_status;

ALTER TABLE app.reels
    DROP CONSTRAINT reels_status_check;

UPDATE app.reels
SET download_status = 'failed'
WHERE download_status = 'download_failed';

ALTER TABLE app.reels
    ADD COLUMN curation_status TEXT NOT NULL DEFAULT 'inbox',
    ADD COLUMN transcription_status TEXT NOT NULL DEFAULT 'not_requested',
    ADD CONSTRAINT reels_download_status_check
        CHECK (download_status IN ('received', 'downloading', 'downloaded', 'failed')),
    ADD CONSTRAINT reels_curation_status_check
        CHECK (curation_status IN ('inbox', 'organized')),
    ADD CONSTRAINT reels_transcription_status_check
        CHECK (transcription_status IN ('not_requested', 'queued', 'processing', 'completed', 'failed'));

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM app.reels
        WHERE download_status NOT IN ('received', 'downloading', 'downloaded', 'failed')
           OR curation_status NOT IN ('inbox', 'organized')
           OR transcription_status NOT IN ('not_requested', 'queued', 'processing', 'completed', 'failed')
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
              'reels_transcription_status_check'
          )
          AND contype = 'c'
    ) <> 3 THEN
        RAISE EXCEPTION 'resulting Reel lifecycle constraints are missing';
    END IF;
END $$;

COMMIT;
