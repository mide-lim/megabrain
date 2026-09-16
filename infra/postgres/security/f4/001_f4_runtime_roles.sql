-- F4 runtime role creation template. Execute only under a separate human rollout
-- authorization, as a PostgreSQL role-administration principal, with interactive
-- psql. This file is safe before migration 005 because it creates no F4-column
-- grants.
--
-- psql's \password prompt keeps the operator-provided password out of this file,
-- shell history, process argv, and PostgreSQL statement text. Do not replace it
-- with a password psql variable or a CREATE/ALTER ROLE PASSWORD literal.
--
-- The script intentionally fails if either target role already exists; inspect and
-- resolve that state rather than silently changing an unknown role.

BEGIN;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_roles
        WHERE rolname IN ('megabrain_mgb020', 'megabrain_mgb030')
    ) THEN
        RAISE EXCEPTION 'F4 runtime role already exists; refusing to alter an unknown role';
    END IF;
END
$$;

CREATE ROLE megabrain_mgb020 NOLOGIN
    NOSUPERUSER
    NOCREATEDB
    NOCREATEROLE
    NOREPLICATION
    NOBYPASSRLS
    NOINHERIT;

CREATE ROLE megabrain_mgb030 NOLOGIN
    NOSUPERUSER
    NOCREATEDB
    NOCREATEROLE
    NOREPLICATION
    NOBYPASSRLS
    NOINHERIT;

-- psql prompts twice with terminal echo disabled and sends only a password hash.
\password megabrain_mgb020
\password megabrain_mgb030

ALTER ROLE megabrain_mgb020 LOGIN;
ALTER ROLE megabrain_mgb030 LOGIN;

COMMIT;
