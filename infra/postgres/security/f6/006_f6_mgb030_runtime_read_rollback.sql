-- Roll back only the F6 MGB-030 runtime read-authority overlay.
--
-- SOURCE ARTIFACT ONLY.
--
-- Required psql acknowledgement:
--   -v f6_mgb030_runtime_read_rollback_ack=true

\set ON_ERROR_STOP on

\if :{?f6_mgb030_runtime_read_rollback_ack}
\else
    \echo 'missing f6_mgb030_runtime_read_rollback_ack; refusing rollback'
    \quit 3
\endif

\if :f6_mgb030_runtime_read_rollback_ack
\else
    \echo 'f6_mgb030_runtime_read_rollback_ack must be true; refusing rollback'
    \quit 3
\endif

BEGIN;

REVOKE SELECT (updated_at)
ON TABLE app.reels
FROM megabrain_mgb030;

REVOKE SELECT (
    started_at,
    provider_request_id,
    retry_of_attempt_id
)
ON TABLE app.reel_enrichment_attempts
FROM megabrain_mgb030;

COMMIT;
