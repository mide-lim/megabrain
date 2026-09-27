-- Roll back only the F6 I1-B Web applicable-enrichment read authority overlay.
--
-- SOURCE ARTIFACT ONLY. Execute only during a separately human-authorized
-- I1-B rollback. This removes exactly the I1-B enrichment identity-read delta.
--
-- Required psql acknowledgement:
--   -v i1_b_web_applicable_enrichment_read_rollback_ack=true
\set ON_ERROR_STOP on

\if :{?i1_b_web_applicable_enrichment_read_rollback_ack}
\else
    \echo 'missing i1_b_web_applicable_enrichment_read_rollback_ack; refusing rollback'
    \quit 3
\endif

\if :i1_b_web_applicable_enrichment_read_rollback_ack
\else
    \echo 'i1_b_web_applicable_enrichment_read_rollback_ack must be true; refusing rollback'
    \quit 3
\endif

BEGIN;

REVOKE SELECT (sha256)
ON TABLE app.reels
FROM megabrain_web;

REVOKE SELECT (
    source_object_key,
    source_sha256,
    pipeline_version
)
ON TABLE app.reel_enrichments
FROM megabrain_web;

COMMIT;
