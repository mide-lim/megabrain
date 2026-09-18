-- F4 Web owner-auth privilege reconciliation.
--
-- Production discovery during F4.6P:
--
-- resolve_or_bootstrap_owner() uses:
--
--   ON CONFLICT (provider) DO UPDATE
--
-- and its update projection reads EXCLUDED.email_normalized.
--
-- PostgreSQL therefore requires SELECT authority on both provider and
-- email_normalized for megabrain_web to execute the production UPSERT.
--
-- This is the exact production-proven least-privilege delta.
-- Table-wide SELECT remains denied.

\set ON_ERROR_STOP on

BEGIN;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_roles
        WHERE rolname='megabrain_web'
    ) THEN
        RAISE EXCEPTION
            'megabrain_web role is required';
    END IF;

    IF to_regclass('app.auth_users') IS NULL THEN
        RAISE EXCEPTION
            'app.auth_users is required';
    END IF;
END
$$;

GRANT SELECT (provider, email_normalized)
ON TABLE app.auth_users
TO megabrain_web;

COMMIT;
