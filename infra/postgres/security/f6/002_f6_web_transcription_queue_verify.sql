-- Read-only F6 Web transcription-request queue authority verifier.
--
-- SOURCE ARTIFACT ONLY. Run only during the separately human-authorized
-- TC4-WEB-QUEUE-AUTHORITY gate. This script reads PostgreSQL catalogs only,
-- returns PASS/FAIL assertions, and exits non-zero if any assertion fails.

\set ON_ERROR_STOP on

WITH checks(name, expected, actual) AS (
    VALUES
        ('WEB_SCHEMA_USAGE', TRUE, has_schema_privilege('megabrain_web', 'app', 'USAGE')),
        ('WEB_SCHEMA_CREATE', FALSE, has_schema_privilege('megabrain_web', 'app', 'CREATE')),
        (
            'WEB_F6_CAN_SELECT_TRANSCRIPTION_ATTEMPT',
            TRUE,
            has_column_privilege(
                'megabrain_web',
                'app.reels',
                'transcription_attempt_id',
                'SELECT'
            )
        ),
        (
            'WEB_F6_CAN_QUEUE_TRANSCRIPTION',
            TRUE,
            has_column_privilege(
                'megabrain_web',
                'app.reels',
                'transcription_status',
                'UPDATE'
            )
            AND has_column_privilege(
                'megabrain_web',
                'app.reels',
                'transcription_attempt_id',
                'UPDATE'
            )
            AND has_column_privilege(
                'megabrain_web',
                'app.reels',
                'updated_at',
                'UPDATE'
            )
        ),
        (
            'WEB_CAN_WRITE_CURATION',
            TRUE,
            has_column_privilege('megabrain_web', 'app.reels', 'curation_status', 'UPDATE')
        ),
        (
            'WEB_CANNOT_WRITE_DOWNLOAD',
            FALSE,
            has_column_privilege('megabrain_web', 'app.reels', 'download_status', 'UPDATE')
        ),
        (
            'WEB_REELS_TABLE_WIDE_UPDATE',
            FALSE,
            has_table_privilege('megabrain_web', 'app.reels', 'UPDATE')
        ),
        (
            'WEB_REELS_TABLE_WIDE_SELECT',
            FALSE,
            has_table_privilege('megabrain_web', 'app.reels', 'SELECT')
        ),
        (
            'WEB_CANNOT_DELETE_REELS',
            FALSE,
            has_table_privilege('megabrain_web', 'app.reels', 'DELETE')
        )
), allowed_columns(role_name, relation_name, privilege, columns) AS (
    VALUES
        (
            'megabrain_web',
            'app.reels',
            'SELECT',
            ARRAY[
                'id', 'shortcode', 'original_url', 'source', 'download_status',
                'curation_status', 'transcription_status', 'telegram_chat_id',
                'telegram_user_id', 'telegram_message_id', 'raw_message',
                'received_at', 'title', 'creator', 'caption', 'duration_seconds',
                'filename', 'mime_type', 'file_size_bytes', 'storage_provider',
                'storage_bucket', 'object_key', 'downloaded_at',
                'transcription_attempt_id'
            ]
        ),
        (
            'megabrain_web',
            'app.reels',
            'UPDATE',
            ARRAY[
                'curation_status',
                'transcription_status',
                'transcription_attempt_id',
                'updated_at'
            ]
        )
), missing_columns AS (
    SELECT allowed.privilege
    FROM allowed_columns AS allowed
    CROSS JOIN LATERAL unnest(allowed.columns) AS required(column_name)
    WHERE NOT has_column_privilege(
        allowed.role_name,
        allowed.relation_name,
        required.column_name,
        allowed.privilege
    )
), excess_columns AS (
    SELECT action.privilege
    FROM pg_attribute AS attribute
    CROSS JOIN unnest(ARRAY['SELECT', 'UPDATE']) AS action(privilege)
    LEFT JOIN allowed_columns AS allowed
      ON allowed.role_name = 'megabrain_web'
     AND allowed.relation_name = 'app.reels'
     AND allowed.privilege = action.privilege
    WHERE attribute.attrelid = 'app.reels'::regclass
      AND attribute.attnum > 0
      AND NOT attribute.attisdropped
      AND (allowed.columns IS NULL OR attribute.attname <> ALL (allowed.columns))
      AND has_column_privilege(
          'megabrain_web',
          'app.reels',
          attribute.attname,
          action.privilege
      )
), web_memberships AS (
    SELECT 1
    FROM pg_auth_members AS membership
    JOIN pg_roles AS member_role ON member_role.oid = membership.member
    WHERE member_role.rolname = 'megabrain_web'
), enrichment_attempt_access AS (
    SELECT 1
    FROM pg_attribute AS attribute
    CROSS JOIN unnest(ARRAY['SELECT', 'INSERT', 'UPDATE', 'REFERENCES']) AS action(privilege)
    WHERE attribute.attrelid = 'app.reel_enrichment_attempts'::regclass
      AND attribute.attnum > 0
      AND NOT attribute.attisdropped
      AND has_column_privilege(
          'megabrain_web',
          'app.reel_enrichment_attempts',
          attribute.attname,
          action.privilege
      )
    UNION ALL
    SELECT 1
    FROM unnest(ARRAY[
        'SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER'
    ]) AS action(privilege)
    WHERE has_table_privilege(
        'megabrain_web',
        'app.reel_enrichment_attempts',
        action.privilege
    )
), enrichment_result_write AS (
    SELECT 1
    FROM pg_attribute AS attribute
    CROSS JOIN unnest(ARRAY['INSERT', 'UPDATE', 'REFERENCES']) AS action(privilege)
    WHERE attribute.attrelid = 'app.reel_enrichments'::regclass
      AND attribute.attnum > 0
      AND NOT attribute.attisdropped
      AND has_column_privilege(
          'megabrain_web',
          'app.reel_enrichments',
          attribute.attname,
          action.privilege
      )
    UNION ALL
    SELECT 1
    FROM unnest(ARRAY[
        'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER'
    ]) AS action(privilege)
    WHERE has_table_privilege(
        'megabrain_web',
        'app.reel_enrichments',
        action.privilege
    )
), enrichment_result_sequence_access AS (
    SELECT 1
    FROM unnest(ARRAY['USAGE', 'SELECT', 'UPDATE']) AS action(privilege)
    WHERE has_sequence_privilege(
        'megabrain_web',
        'app.reel_enrichments_id_seq',
        action.privilege
    )
), public_f6_authority AS (
    SELECT 1
    FROM pg_namespace AS namespace
    CROSS JOIN LATERAL aclexplode(
        COALESCE(namespace.nspacl, acldefault('n', namespace.nspowner))
    ) AS privilege
    WHERE namespace.nspname = 'app'
      AND privilege.grantee = 0
    UNION ALL
    SELECT 1
    FROM pg_class AS relation
    CROSS JOIN LATERAL aclexplode(
        COALESCE(relation.relacl, acldefault('r', relation.relowner))
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
    JOIN pg_class AS relation ON relation.oid = attribute.attrelid
    CROSS JOIN LATERAL aclexplode(
        COALESCE(attribute.attacl, acldefault('c', relation.relowner))
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
        COALESCE(sequence.relacl, acldefault('s', sequence.relowner))
    ) AS privilege
    WHERE sequence.oid = 'app.reel_enrichments_id_seq'::regclass
      AND privilege.grantee = 0
), boundary_checks(name, expected, actual) AS (
    VALUES
        (
            'WEB_F6_EFFECTIVE_SELECT_ALLOWLIST',
            TRUE,
            NOT EXISTS (
                SELECT 1 FROM missing_columns WHERE privilege = 'SELECT'
            )
            AND NOT EXISTS (
                SELECT 1 FROM excess_columns WHERE privilege = 'SELECT'
            )
        ),
        (
            'WEB_F6_EFFECTIVE_UPDATE_ALLOWLIST',
            TRUE,
            NOT EXISTS (
                SELECT 1 FROM missing_columns WHERE privilege = 'UPDATE'
            )
            AND NOT EXISTS (
                SELECT 1 FROM excess_columns WHERE privilege = 'UPDATE'
            )
        ),
        (
            'WEB_CANNOT_ACCESS_ENRICHMENT_ATTEMPTS',
            TRUE,
            NOT EXISTS (SELECT 1 FROM enrichment_attempt_access)
        ),
        (
            'WEB_CANNOT_WRITE_ENRICHMENT_RESULTS',
            TRUE,
            NOT EXISTS (SELECT 1 FROM enrichment_result_write)
        ),
        (
            'WEB_CANNOT_USE_ENRICHMENT_RESULT_SEQUENCE',
            TRUE,
            NOT EXISTS (SELECT 1 FROM enrichment_result_sequence_access)
        ),
        (
            'WEB_F6_NO_UNEXPECTED_ROLE_MEMBERSHIPS',
            TRUE,
            NOT EXISTS (SELECT 1 FROM web_memberships)
        ),
        (
            'WEB_F6_NO_UNEXPECTED_PUBLIC_AUTHORITY',
            TRUE,
            NOT EXISTS (SELECT 1 FROM public_f6_authority)
        )
), assertions(name, expected, actual) AS (
    SELECT name, expected, actual
    FROM checks
    UNION ALL
    SELECT name, expected, actual
    FROM boundary_checks
)
SELECT
    COALESCE(bool_and(actual IS NOT DISTINCT FROM expected), FALSE)
        AS f6_web_transcription_queue_verifier_all_pass,
    string_agg(
        format(
            '%s | %s | %s | %s',
            name,
            CASE WHEN actual IS NOT DISTINCT FROM expected THEN 'PASS' ELSE 'FAIL' END,
            expected,
            actual
        ),
        E'\n'
        ORDER BY name
    ) AS f6_web_transcription_queue_verifier_report
FROM assertions
\gset
\echo :f6_web_transcription_queue_verifier_report
\if :f6_web_transcription_queue_verifier_all_pass
\else
\quit 3
\endif
