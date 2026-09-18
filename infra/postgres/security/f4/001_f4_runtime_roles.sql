-- F4 runtime role structure. Execute only under a separate human rollout
-- authorization, as a PostgreSQL role-administration principal. This file is
-- deliberately noninteractive so a disposable integration proof can execute it
-- through psql stdin without supplying a secret. It creates no F4-column grants.
--
-- The roles remain NOLOGIN after this file commits. A separate human production
-- credential-provisioning step must set each role to LOGIN and provision its
-- password outside Git before either role can authenticate as a runtime principal.
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

COMMIT;
