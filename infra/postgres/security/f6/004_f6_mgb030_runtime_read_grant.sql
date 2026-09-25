-- F6 MGB-030 runtime read-authority overlay.
--
-- SOURCE ARTIFACT ONLY. Execute only during a separately human-authorized
-- F6 production cutover recovery gate, as a PostgreSQL role administrator.
--
-- This overlay adds only the four column-scoped SELECT privileges introduced
-- by the F6 MGB-030 workflow. It changes no writes, role attributes,
-- memberships, passwords, LOGIN state, schema objects, or table-wide grants.

\set ON_ERROR_STOP on

BEGIN;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_roles
        WHERE rolname = 'megabrain_mgb030'
    ) THEN
        RAISE EXCEPTION 'megabrain_mgb030 is required';
    END IF;

    IF to_regclass('app.reels') IS NULL
       OR to_regclass('app.reel_enrichment_attempts') IS NULL THEN
        RAISE EXCEPTION 'required F6 MGB-030 relations are missing';
    END IF;

    IF (
        SELECT count(*)
        FROM information_schema.columns
        WHERE table_schema = 'app'
          AND table_name = 'reels'
          AND column_name = 'updated_at'
    ) <> 1 THEN
        RAISE EXCEPTION 'app.reels.updated_at is required';
    END IF;

    IF (
        SELECT count(*)
        FROM information_schema.columns
        WHERE table_schema = 'app'
          AND table_name = 'reel_enrichment_attempts'
          AND column_name IN (
              'started_at',
              'provider_request_id',
              'retry_of_attempt_id'
          )
    ) <> 3 THEN
        RAISE EXCEPTION 'required F6 MGB-030 attempt read columns are missing';
    END IF;
END
$$;

GRANT SELECT (updated_at)
ON TABLE app.reels
TO megabrain_mgb030;

GRANT SELECT (
    started_at,
    provider_request_id,
    retry_of_attempt_id
)
ON TABLE app.reel_enrichment_attempts
TO megabrain_mgb030;

COMMIT;
