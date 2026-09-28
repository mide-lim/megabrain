-- F5 Categories: minimal delta for global category rename/delete.
-- Execute only after explicit production authorization.
-- This file does not alter schema, ownership, role membership, or unrelated tables.

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

    IF to_regclass('app.categories') IS NULL THEN
        RAISE EXCEPTION 'app.categories is required';
    END IF;
END
$$;

GRANT UPDATE (name) ON TABLE app.categories TO megabrain_web;
GRANT DELETE ON TABLE app.categories TO megabrain_web;

COMMIT;
