-- Read-only F6 MGB-030 runtime read-authority verifier.
--
-- SOURCE ARTIFACT ONLY. This verifier reads PostgreSQL catalogs only.
-- It requires the historical F4 MGB-030 SELECT authority plus exactly the
-- four F6 read columns required by the F6 workflow.

\set ON_ERROR_STOP on

WITH checks(name, expected, actual) AS (
    VALUES
        (
            'MGB030_SCHEMA_USAGE',
            TRUE,
            has_schema_privilege(
                'megabrain_mgb030',
                'app',
                'USAGE'
            )
        ),
        (
            'MGB030_SCHEMA_CREATE',
            FALSE,
            has_schema_privilege(
                'megabrain_mgb030',
                'app',
                'CREATE'
            )
        ),
        (
            'MGB030_F6_CAN_READ_REELS_UPDATED_AT',
            TRUE,
            has_column_privilege(
                'megabrain_mgb030',
                'app.reels',
                'updated_at',
                'SELECT'
            )
        ),
        (
            'MGB030_F6_CAN_READ_ATTEMPT_SCHEDULING_FIELDS',
            TRUE,
            has_column_privilege(
                'megabrain_mgb030',
                'app.reel_enrichment_attempts',
                'started_at',
                'SELECT'
            )
            AND has_column_privilege(
                'megabrain_mgb030',
                'app.reel_enrichment_attempts',
                'provider_request_id',
                'SELECT'
            )
            AND has_column_privilege(
                'megabrain_mgb030',
                'app.reel_enrichment_attempts',
                'retry_of_attempt_id',
                'SELECT'
            )
        ),
        (
            'MGB030_REELS_TABLE_WIDE_SELECT',
            FALSE,
            has_table_privilege(
                'megabrain_mgb030',
                'app.reels',
                'SELECT'
            )
        ),
        (
            'MGB030_ATTEMPTS_TABLE_WIDE_SELECT',
            FALSE,
            has_table_privilege(
                'megabrain_mgb030',
                'app.reel_enrichment_attempts',
                'SELECT'
            )
        ),
        (
            'MGB030_ENRICHMENTS_TABLE_WIDE_SELECT',
            FALSE,
            has_table_privilege(
                'megabrain_mgb030',
                'app.reel_enrichments',
                'SELECT'
            )
        )
), allowed_columns(
    role_name,
    relation_name,
    privilege,
    columns
) AS (
    VALUES
        (
            'megabrain_mgb030',
            'app.reels',
            'SELECT',
            ARRAY[
                'id',
                'shortcode',
                'object_key',
                'sha256',
                'file_size_bytes',
                'download_status',
                'transcription_status',
                'transcription_attempt_id',
                'updated_at'
            ]
        ),
        (
            'megabrain_mgb030',
            'app.reel_enrichment_attempts',
            'SELECT',
            ARRAY[
                'attempt_id',
                'reel_id',
                'source_object_key',
                'expected_sha256',
                'expected_size_bytes',
                'pipeline_version',
                'contract_version',
                'language_hint',
                'status',
                'retryable',
                'error_code',
                'error_stage',
                'started_at',
                'provider_request_id',
                'retry_of_attempt_id'
            ]
        ),
        (
            'megabrain_mgb030',
            'app.reel_enrichments',
            'SELECT',
            ARRAY[
                'id',
                'reel_id',
                'source_attempt_id',
                'source_object_key',
                'source_sha256',
                'pipeline_version',
                'outcome'
            ]
        )
), missing_columns AS (
    SELECT
        allowed.relation_name,
        required.column_name
    FROM allowed_columns AS allowed
    CROSS JOIN LATERAL
        unnest(allowed.columns)
        AS required(column_name)
    WHERE NOT has_column_privilege(
        allowed.role_name,
        allowed.relation_name,
        required.column_name,
        allowed.privilege
    )
), excess_columns AS (
    SELECT
        allowed.relation_name,
        attribute.attname
    FROM allowed_columns AS allowed
    JOIN pg_class AS relation
      ON relation.oid =
         allowed.relation_name::regclass
    JOIN pg_attribute AS attribute
      ON attribute.attrelid = relation.oid
    WHERE attribute.attnum > 0
      AND NOT attribute.attisdropped
      AND attribute.attname <> ALL (
          allowed.columns
      )
      AND has_column_privilege(
          allowed.role_name,
          allowed.relation_name,
          attribute.attname,
          allowed.privilege
      )
), mgb030_memberships AS (
    SELECT 1
    FROM pg_auth_members AS membership
    JOIN pg_roles AS member_role
      ON member_role.oid = membership.member
    WHERE member_role.rolname =
          'megabrain_mgb030'
), public_authority AS (
    SELECT 1
    FROM pg_namespace AS namespace
    CROSS JOIN LATERAL aclexplode(
        COALESCE(
            namespace.nspacl,
            acldefault(
                'n',
                namespace.nspowner
            )
        )
    ) AS privilege
    WHERE namespace.nspname = 'app'
      AND privilege.grantee = 0

    UNION ALL

    SELECT 1
    FROM pg_class AS relation
    CROSS JOIN LATERAL aclexplode(
        COALESCE(
            relation.relacl,
            acldefault(
                'r',
                relation.relowner
            )
        )
    ) AS privilege
    WHERE relation.oid IN (
        'app.reels'::regclass,
        'app.reel_enrichment_attempts'::regclass,
        'app.reel_enrichments'::regclass
    )
      AND privilege.grantee = 0

    UNION ALL

    SELECT 1
    FROM pg_attribute AS attribute
    JOIN pg_class AS relation
      ON relation.oid =
         attribute.attrelid
    CROSS JOIN LATERAL aclexplode(
        COALESCE(
            attribute.attacl,
            acldefault(
                'c',
                relation.relowner
            )
        )
    ) AS privilege
    WHERE attribute.attrelid IN (
        'app.reels'::regclass,
        'app.reel_enrichment_attempts'::regclass,
        'app.reel_enrichments'::regclass
    )
      AND attribute.attnum > 0
      AND NOT attribute.attisdropped
      AND privilege.grantee = 0

    UNION ALL

    SELECT 1
    FROM pg_class AS sequence
    CROSS JOIN LATERAL aclexplode(
        COALESCE(
            sequence.relacl,
            acldefault(
                's',
                sequence.relowner
            )
        )
    ) AS privilege
    WHERE sequence.oid =
          'app.reel_enrichments_id_seq'::regclass
      AND privilege.grantee = 0
), boundary_checks(
    name,
    expected,
    actual
) AS (
    VALUES
        (
            'MGB030_F6_EFFECTIVE_SELECT_ALLOWLIST',
            TRUE,
            NOT EXISTS (
                SELECT 1
                FROM missing_columns
            )
            AND NOT EXISTS (
                SELECT 1
                FROM excess_columns
            )
        ),
        (
            'MGB030_F6_NO_UNEXPECTED_ROLE_MEMBERSHIPS',
            TRUE,
            NOT EXISTS (
                SELECT 1
                FROM mgb030_memberships
            )
        ),
        (
            'MGB030_F6_NO_UNEXPECTED_PUBLIC_AUTHORITY',
            TRUE,
            NOT EXISTS (
                SELECT 1
                FROM public_authority
            )
        )
), assertions(
    name,
    expected,
    actual
) AS (
    SELECT name, expected, actual
    FROM checks

    UNION ALL

    SELECT name, expected, actual
    FROM boundary_checks
)
SELECT
    COALESCE(
        bool_and(
            actual IS NOT DISTINCT FROM expected
        ),
        FALSE
    ) AS f6_mgb030_runtime_read_verifier_all_pass,
    string_agg(
        format(
            '%s | %s | %s | %s',
            name,
            CASE
                WHEN actual IS NOT DISTINCT FROM expected
                    THEN 'PASS'
                ELSE 'FAIL'
            END,
            expected,
            actual
        ),
        E'\n'
        ORDER BY name
    ) AS f6_mgb030_runtime_read_verifier_report
FROM assertions
\gset

\echo :f6_mgb030_runtime_read_verifier_report

\if :f6_mgb030_runtime_read_verifier_all_pass
\else
    \quit 3
\endif
