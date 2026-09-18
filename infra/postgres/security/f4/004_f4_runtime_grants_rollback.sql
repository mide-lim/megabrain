-- F4 dedicated-runtime privilege rollback only. This is not a schema rollback.
--
-- Case A, before either n8n workflow uses its dedicated credential: an authorized
-- operator may run this after confirming the new roles are unused.
--
-- Case B, after either credential switch: first quiesce MGB-020/MGB-030, restore
-- the separately approved prior credential assignment only if the schema/runtime
-- compatibility decision permits it, and verify the dedicated credentials are
-- detached from every F4 workflow node. Do not run this file until that human
-- credential-detachment proof exists. After F4 writes, forward-fix is preferred.
--
-- Required psql acknowledgement variable, with an affirmative boolean value:
--   f4_dedicated_credentials_detached=true

\if :{?f4_dedicated_credentials_detached}
\else
  \echo 'missing human credential-detachment acknowledgement; refusing rollback'
  \quit
\endif
\if :f4_dedicated_credentials_detached
\else
  \echo 'credential-detachment acknowledgement must be true; refusing rollback'
  \quit
\endif

-- Phase 1 commits NOLOGIN before any session check. This prevents a new login
-- from racing the destructive phase under PostgreSQL transaction visibility.
BEGIN;
ALTER ROLE megabrain_mgb020 NOLOGIN;
ALTER ROLE megabrain_mgb030 NOLOGIN;
COMMIT;

-- If this phase fails, both roles intentionally remain NOLOGIN. Human recovery
-- must account for that disabled state before deciding whether to re-enable them.
BEGIN;
DO $$
BEGIN
    -- Quiesce is required before this point. Terminate any residual dedicated
    -- connections, then recheck; no new login can succeed after phase 1.
    PERFORM pg_terminate_backend(activity.pid)
    FROM pg_stat_activity AS activity
    WHERE activity.usename IN ('megabrain_mgb020', 'megabrain_mgb030')
      AND activity.pid <> pg_backend_pid();

    IF EXISTS (
        SELECT 1
        FROM pg_stat_activity
        WHERE usename IN ('megabrain_mgb020', 'megabrain_mgb030')
          AND pid <> pg_backend_pid()
    ) THEN
        RAISE EXCEPTION 'active F4 dedicated-role sessions exist; quiesce before rollback';
    END IF;
END
$$;

REVOKE ALL PRIVILEGES ON SCHEMA app FROM megabrain_mgb020, megabrain_mgb030;
REVOKE ALL PRIVILEGES ON TABLE
    app.reels,
    app.reel_enrichment_attempts,
    app.reel_enrichments,
    app.categories,
    app.reel_categories,
    app.auth_transactions,
    app.auth_users,
    app.auth_sessions
FROM megabrain_mgb020, megabrain_mgb030;
REVOKE ALL PRIVILEGES ON SEQUENCE
    app.reels_id_seq,
    app.categories_id_seq,
    app.auth_users_id_seq,
    app.reel_enrichments_id_seq
FROM megabrain_mgb020, megabrain_mgb030;

-- DROP ROLE remains fail-closed if unrelated dependent grants or ownership exist.
DROP ROLE megabrain_mgb020;
DROP ROLE megabrain_mgb030;

COMMIT;
