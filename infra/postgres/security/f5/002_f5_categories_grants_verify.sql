-- F5 Categories: bounded read-only authority verification.
-- Run after the grant delta. This verifies only the new F5 authority boundary.

BEGIN READ ONLY;

DO $$
BEGIN
    IF NOT has_column_privilege(
        'megabrain_web',
        'app.categories',
        'name',
        'UPDATE'
    ) THEN
        RAISE EXCEPTION 'megabrain_web is missing UPDATE(name) on app.categories';
    END IF;

    IF NOT has_table_privilege(
        'megabrain_web',
        'app.categories',
        'DELETE'
    ) THEN
        RAISE EXCEPTION 'megabrain_web is missing DELETE on app.categories';
    END IF;

    IF has_table_privilege(
        'megabrain_web',
        'app.categories',
        'UPDATE'
    ) THEN
        RAISE EXCEPTION 'unexpected table-level UPDATE on app.categories';
    END IF;

    IF has_table_privilege(
        'megabrain_web',
        'app.categories',
        'TRUNCATE'
    ) THEN
        RAISE EXCEPTION 'unexpected TRUNCATE on app.categories';
    END IF;

    IF has_schema_privilege(
        'megabrain_web',
        'app',
        'CREATE'
    ) THEN
        RAISE EXCEPTION 'unexpected CREATE on schema app';
    END IF;
END
$$;

ROLLBACK;
