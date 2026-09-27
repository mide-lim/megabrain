-- F6 I1-B Web applicable-enrichment read authority overlay.
--
-- SOURCE ARTIFACT ONLY. Execute only during a separately human-authorized
-- I1-B rollout, as a PostgreSQL role administrator. This adds only the three
-- enrichment identity columns needed by the guarded request and fallback read.
\set ON_ERROR_STOP on

BEGIN;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_roles
        WHERE rolname = 'megabrain_web'
    ) THEN
        RAISE EXCEPTION 'megabrain_web is required';
    END IF;

    IF to_regclass('app.reels') IS NULL
       OR to_regclass('app.reel_enrichments') IS NULL THEN
        RAISE EXCEPTION 'app.reels and app.reel_enrichments are required';
    END IF;

    IF (
        SELECT count(*)
        FROM information_schema.columns
        WHERE table_schema = 'app'
          AND table_name = 'reels'
          AND column_name = 'sha256'
    ) <> 1 THEN
        RAISE EXCEPTION 'app.reels.sha256 is required';
    END IF;

    IF (
        SELECT count(*)
        FROM information_schema.columns
        WHERE table_schema = 'app'
          AND table_name = 'reel_enrichments'
          AND column_name IN (
              'source_object_key',
              'source_sha256',
              'pipeline_version'
          )
    ) <> 3 THEN
        RAISE EXCEPTION 'I1-B applicable enrichment identity columns are required';
    END IF;
END
$$;

-- Existing Web Reel SELECT authority does not include the source digest.
GRANT SELECT (sha256)
ON TABLE app.reels
TO megabrain_web;

GRANT SELECT (
    source_object_key,
    source_sha256,
    pipeline_version
)
ON TABLE app.reel_enrichments
TO megabrain_web;

COMMIT;
