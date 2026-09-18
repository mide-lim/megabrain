-- Roll back only the F4 Web owner-auth SELECT reconciliation.
--
-- WARNING:
--
-- Revoking these two column privileges restores the authority that existed
-- before the production hotfix and makes the current owner UPSERT contract
-- unable to authenticate successfully.
--
-- Required psql variable:
--
--   -v f4_web_auth_hotfix_rollback_ack=true

\set ON_ERROR_STOP on

\if :{?f4_web_auth_hotfix_rollback_ack}
\else
    \echo 'missing f4_web_auth_hotfix_rollback_ack; refusing rollback'
    \quit 3
\endif

\if :f4_web_auth_hotfix_rollback_ack
\else
    \echo 'f4_web_auth_hotfix_rollback_ack must be true; refusing rollback'
    \quit 3
\endif

BEGIN;

REVOKE SELECT (provider, email_normalized)
ON TABLE app.auth_users
FROM megabrain_web;

COMMIT;
