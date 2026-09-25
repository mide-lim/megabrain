-- Roll back only the F6 Web transcription-request queue authority overlay.
--
-- SOURCE ARTIFACT ONLY. Execute only during a separately human-authorized
-- TC4-WEB-QUEUE-AUTHORITY rollback. This preserves F4 curation, registration,
-- authentication, category, hotfix, MGB-020, and MGB-030 authority.
--
-- After this rollback, the F6 Web "Transcrever" request endpoint can no longer
-- function with megabrain_web because its fallback read and queue update lose
-- the F6 column authority.
--
-- Required psql acknowledgement:
--   -v f6_web_transcription_queue_rollback_ack=true

\set ON_ERROR_STOP on

\if :{?f6_web_transcription_queue_rollback_ack}
\else
    \echo 'missing f6_web_transcription_queue_rollback_ack; refusing rollback'
    \quit 3
\endif

\if :f6_web_transcription_queue_rollback_ack
\else
    \echo 'f6_web_transcription_queue_rollback_ack must be true; refusing rollback'
    \quit 3
\endif

BEGIN;

REVOKE SELECT (transcription_attempt_id)
ON TABLE app.reels
FROM megabrain_web;

REVOKE UPDATE (
    transcription_status,
    transcription_attempt_id,
    updated_at
)
ON TABLE app.reels
FROM megabrain_web;

COMMIT;
