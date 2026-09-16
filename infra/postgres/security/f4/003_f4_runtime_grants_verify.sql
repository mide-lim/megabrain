-- Read-only F4 post-rollout authority verifier.
--
-- Run with psql after 001 and 002, migration 005, and the human credential
-- switch. It reads PostgreSQL catalogs only and returns PASS/FAIL rows; it never
-- reads application rows or changes database state. Every row must be PASS.

WITH checks(name, expected, actual) AS (
    VALUES
        (
            'WEB_ROLE_ATTRIBUTES_RESTRICTIVE',
            TRUE,
            EXISTS (
                SELECT 1
                FROM pg_roles
                WHERE rolname = 'megabrain_web'
                  AND rolcanlogin
                  AND NOT rolsuper
                  AND NOT rolcreatedb
                  AND NOT rolcreaterole
                  AND NOT rolreplication
                  AND NOT rolbypassrls
            )
        ),
        (
            'MGB020_ROLE_ATTRIBUTES_RESTRICTIVE',
            TRUE,
            EXISTS (
                SELECT 1
                FROM pg_roles
                WHERE rolname = 'megabrain_mgb020'
                  AND NOT rolsuper
                  AND NOT rolcreatedb
                  AND NOT rolcreaterole
                  AND NOT rolreplication
                  AND NOT rolbypassrls
                  AND NOT rolinherit
            )
        ),
        (
            'MGB030_ROLE_ATTRIBUTES_RESTRICTIVE',
            TRUE,
            EXISTS (
                SELECT 1
                FROM pg_roles
                WHERE rolname = 'megabrain_mgb030'
                  AND NOT rolsuper
                  AND NOT rolcreatedb
                  AND NOT rolcreaterole
                  AND NOT rolreplication
                  AND NOT rolbypassrls
                  AND NOT rolinherit
            )
        ),
        (
            'ALL_RUNTIME_ROLES_HAVE_NO_MEMBERSHIPS',
            TRUE,
            NOT EXISTS (
                SELECT 1
                FROM pg_auth_members membership
                JOIN pg_roles member_role ON member_role.oid = membership.member
                WHERE member_role.rolname IN (
                    'megabrain_web', 'megabrain_mgb020', 'megabrain_mgb030'
                )
            )
        ),
        (
            'RUNTIME_ROLES_OWN_NO_F4_OBJECTS',
            TRUE,
            NOT EXISTS (
                SELECT 1
                FROM pg_class relation
                JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
                JOIN pg_roles owner_role ON owner_role.oid = relation.relowner
                WHERE namespace.nspname = 'app'
                  AND relation.relname IN (
                      'reels',
                      'reel_enrichment_attempts',
                      'reel_enrichments',
                      'reels_id_seq',
                      'reel_enrichments_id_seq'
                  )
                  AND owner_role.rolname IN ('megabrain_mgb020', 'megabrain_mgb030')
            )
        ),
        ('WEB_SCHEMA_USAGE', TRUE, has_schema_privilege('megabrain_web', 'app', 'USAGE')),
        ('WEB_SCHEMA_CREATE', FALSE, has_schema_privilege('megabrain_web', 'app', 'CREATE')),
        (
            'WEB_REELS_SELECT_SOURCE_COLUMNS',
            TRUE,
            NOT EXISTS (
                SELECT 1
                FROM unnest(ARRAY[
                    'id', 'shortcode', 'original_url', 'source', 'download_status',
                    'curation_status', 'transcription_status', 'telegram_chat_id',
                    'telegram_user_id', 'telegram_message_id', 'raw_message',
                    'received_at', 'title', 'creator', 'caption', 'duration_seconds',
                    'filename', 'mime_type', 'file_size_bytes', 'storage_provider',
                    'storage_bucket', 'object_key', 'downloaded_at'
                ]) AS required(column_name)
                WHERE NOT has_column_privilege(
                    'megabrain_web', 'app.reels', required.column_name, 'SELECT'
                )
            )
        ),
        (
            'WEB_REELS_INSERT_REGISTRATION_COLUMNS',
            TRUE,
            NOT EXISTS (
                SELECT 1
                FROM unnest(ARRAY[
                    'shortcode', 'original_url', 'source', 'download_status',
                    'telegram_chat_id', 'telegram_user_id', 'telegram_message_id',
                    'raw_message', 'received_at'
                ]) AS required(column_name)
                WHERE NOT has_column_privilege(
                    'megabrain_web', 'app.reels', required.column_name, 'INSERT'
                )
            )
        ),
        ('WEB_CAN_WRITE_CURATION', TRUE, has_column_privilege('megabrain_web', 'app.reels', 'curation_status', 'UPDATE')),
        ('WEB_CAN_WRITE_DOWNLOAD', FALSE, has_column_privilege('megabrain_web', 'app.reels', 'download_status', 'UPDATE')),
        ('WEB_CAN_WRITE_TRANSCRIPTION', FALSE, has_column_privilege('megabrain_web', 'app.reels', 'transcription_status', 'UPDATE')),
        ('WEB_CAN_WRITE_TRANSCRIPTION_ATTEMPT', FALSE, has_column_privilege('megabrain_web', 'app.reels', 'transcription_attempt_id', 'UPDATE')),
        ('WEB_REELS_TABLE_WIDE_UPDATE', FALSE, has_table_privilege('megabrain_web', 'app.reels', 'UPDATE')),
        ('WEB_REELS_DELETE', FALSE, has_table_privilege('megabrain_web', 'app.reels', 'DELETE')),
        ('WEB_REELS_ID_SEQUENCE_USAGE', TRUE, has_sequence_privilege('megabrain_web', 'app.reels_id_seq', 'USAGE')),
        (
            'WEB_ENRICHMENT_ATTEMPTS_ACCESS',
            FALSE,
            has_table_privilege('megabrain_web', 'app.reel_enrichment_attempts', 'SELECT')
        ),
        (
            'WEB_CATEGORY_MUTATION_CAPABILITY',
            TRUE,
            has_table_privilege('megabrain_web', 'app.reel_categories', 'DELETE')
                AND has_column_privilege('megabrain_web', 'app.categories', 'name', 'INSERT')
        ),
        (
            'WEB_REELS_TABLE_WIDE_SELECT',
            FALSE,
            has_table_privilege('megabrain_web', 'app.reels', 'SELECT')
        ),
        (
            'WEB_REELS_TABLE_WIDE_INSERT',
            FALSE,
            has_table_privilege('megabrain_web', 'app.reels', 'INSERT')
        ),
        ('WEB_REELS_TABLE_WIDE_UPDATE', FALSE, has_table_privilege('megabrain_web', 'app.reels', 'UPDATE')),
        (
            'WEB_REELS_EXCESS_SELECT',
            FALSE,
            EXISTS (
                SELECT 1
                FROM pg_attribute attribute
                WHERE attribute.attrelid = 'app.reels'::regclass
                  AND attribute.attnum > 0
                  AND NOT attribute.attisdropped
                  AND attribute.attname <> ALL (ARRAY[
                      'id', 'shortcode', 'original_url', 'source', 'download_status',
                      'curation_status', 'transcription_status', 'telegram_chat_id',
                      'telegram_user_id', 'telegram_message_id', 'raw_message',
                      'received_at', 'title', 'creator', 'caption', 'duration_seconds',
                      'filename', 'mime_type', 'file_size_bytes', 'storage_provider',
                      'storage_bucket', 'object_key', 'downloaded_at'
                  ])
                  AND has_column_privilege(
                      'megabrain_web', 'app.reels', attribute.attname, 'SELECT'
                  )
            )
        ),
        (
            'WEB_REELS_EXCESS_INSERT',
            FALSE,
            EXISTS (
                SELECT 1
                FROM pg_attribute attribute
                WHERE attribute.attrelid = 'app.reels'::regclass
                  AND attribute.attnum > 0
                  AND NOT attribute.attisdropped
                  AND attribute.attname <> ALL (ARRAY[
                      'shortcode', 'original_url', 'source', 'download_status',
                      'telegram_chat_id', 'telegram_user_id', 'telegram_message_id',
                      'raw_message', 'received_at'
                  ])
                  AND has_column_privilege(
                      'megabrain_web', 'app.reels', attribute.attname, 'INSERT'
                  )
            )
        ),
        (
            'WEB_REELS_EXCESS_UPDATE',
            FALSE,
            EXISTS (
                SELECT 1
                FROM pg_attribute attribute
                WHERE attribute.attrelid = 'app.reels'::regclass
                  AND attribute.attnum > 0
                  AND NOT attribute.attisdropped
                  AND attribute.attname <> 'curation_status'
                  AND has_column_privilege(
                      'megabrain_web', 'app.reels', attribute.attname, 'UPDATE'
                  )
            )
        ),
        ('MGB020_SCHEMA_USAGE', TRUE, has_schema_privilege('megabrain_mgb020', 'app', 'USAGE')),
        ('MGB020_SCHEMA_CREATE', FALSE, has_schema_privilege('megabrain_mgb020', 'app', 'CREATE')),
        (
            'MGB020_REELS_SELECT_SOURCE_COLUMNS',
            TRUE,
            NOT EXISTS (
                SELECT 1
                FROM unnest(ARRAY[
                    'id', 'shortcode', 'original_url', 'telegram_chat_id',
                    'download_status', 'filename', 'file_size_bytes',
                    'storage_bucket', 'object_key', 'downloaded_at', 'error_message',
                    'retry_count'
                ]) AS required(column_name)
                WHERE NOT has_column_privilege(
                    'megabrain_mgb020', 'app.reels', required.column_name, 'SELECT'
                )
            )
        ),
        (
            'MGB020_REELS_TABLE_WIDE_SELECT',
            FALSE,
            has_table_privilege('megabrain_mgb020', 'app.reels', 'SELECT')
        ),
        (
            'MGB020_REELS_TABLE_WIDE_UPDATE',
            FALSE,
            has_table_privilege('megabrain_mgb020', 'app.reels', 'UPDATE')
        ),
        (
            'MGB020_REELS_EXCESS_SELECT',
            FALSE,
            EXISTS (
                SELECT 1
                FROM pg_attribute attribute
                WHERE attribute.attrelid = 'app.reels'::regclass
                  AND attribute.attnum > 0
                  AND NOT attribute.attisdropped
                  AND attribute.attname <> ALL (ARRAY[
                      'id', 'shortcode', 'original_url', 'telegram_chat_id',
                      'download_status', 'filename', 'file_size_bytes',
                      'storage_bucket', 'object_key', 'downloaded_at',
                      'error_message', 'retry_count'
                  ])
                  AND has_column_privilege(
                      'megabrain_mgb020', 'app.reels', attribute.attname, 'SELECT'
                  )
            )
        ),
        (
            'MGB020_REELS_EXCESS_UPDATE',
            FALSE,
            EXISTS (
                SELECT 1
                FROM pg_attribute attribute
                WHERE attribute.attrelid = 'app.reels'::regclass
                  AND attribute.attnum > 0
                  AND NOT attribute.attisdropped
                  AND attribute.attname <> ALL (ARRAY[
                      'download_status', 'download_started_at', 'error_message',
                      'updated_at', 'title', 'creator', 'caption',
                      'duration_seconds', 'filename', 'mime_type',
                      'file_size_bytes', 'sha256', 'storage_provider',
                      'storage_bucket', 'object_key', 'downloaded_at',
                      'retry_count', 'last_error_at'
                  ])
                  AND has_column_privilege(
                      'megabrain_mgb020', 'app.reels', attribute.attname, 'UPDATE'
                  )
            )
        ),
        (
            'MGB020_DOWNLOAD_UPDATE_COLUMNS',
            TRUE,
            NOT EXISTS (
                SELECT 1
                FROM unnest(ARRAY[
                    'download_status', 'download_started_at', 'error_message',
                    'updated_at', 'title', 'creator', 'caption', 'duration_seconds',
                    'filename', 'mime_type', 'file_size_bytes', 'sha256',
                    'storage_provider', 'storage_bucket', 'object_key', 'downloaded_at',
                    'retry_count', 'last_error_at'
                ]) AS required(column_name)
                WHERE NOT has_column_privilege(
                    'megabrain_mgb020', 'app.reels', required.column_name, 'UPDATE'
                )
            )
        ),
        ('MGB020_CAN_WRITE_DOWNLOAD', TRUE, has_column_privilege('megabrain_mgb020', 'app.reels', 'download_status', 'UPDATE')),
        ('MGB020_CAN_WRITE_TRANSCRIPTION', FALSE, has_column_privilege('megabrain_mgb020', 'app.reels', 'transcription_status', 'UPDATE')),
        ('MGB020_CAN_WRITE_TRANSCRIPTION_ATTEMPT', FALSE, has_column_privilege('megabrain_mgb020', 'app.reels', 'transcription_attempt_id', 'UPDATE')),
        ('MGB020_CAN_WRITE_CURATION', FALSE, has_column_privilege('megabrain_mgb020', 'app.reels', 'curation_status', 'UPDATE')),
        ('MGB020_REELS_INSERT', FALSE, has_table_privilege('megabrain_mgb020', 'app.reels', 'INSERT')),
        ('MGB020_REELS_DELETE', FALSE, has_table_privilege('megabrain_mgb020', 'app.reels', 'DELETE')),
        (
            'MGB020_AUTH_ACCESS',
            FALSE,
            EXISTS (
                SELECT 1
                FROM pg_attribute attribute
                WHERE attribute.attrelid = 'app.auth_users'::regclass
                  AND attribute.attnum > 0
                  AND NOT attribute.attisdropped
                  AND (
                      has_column_privilege('megabrain_mgb020', 'app.auth_users', attribute.attname, 'SELECT')
                      OR has_column_privilege('megabrain_mgb020', 'app.auth_users', attribute.attname, 'INSERT')
                      OR has_column_privilege('megabrain_mgb020', 'app.auth_users', attribute.attname, 'UPDATE')
                  )
            ) OR has_table_privilege('megabrain_mgb020', 'app.auth_users', 'DELETE')
        ),
        (
            'MGB020_AUTH_TRANSACTION_ACCESS',
            FALSE,
            EXISTS (
                SELECT 1
                FROM pg_attribute attribute
                WHERE attribute.attrelid = 'app.auth_transactions'::regclass
                  AND attribute.attnum > 0
                  AND NOT attribute.attisdropped
                  AND (
                      has_column_privilege('megabrain_mgb020', 'app.auth_transactions', attribute.attname, 'SELECT')
                      OR has_column_privilege('megabrain_mgb020', 'app.auth_transactions', attribute.attname, 'INSERT')
                      OR has_column_privilege('megabrain_mgb020', 'app.auth_transactions', attribute.attname, 'UPDATE')
                  )
            ) OR has_table_privilege('megabrain_mgb020', 'app.auth_transactions', 'DELETE')
        ),
        (
            'MGB020_AUTH_SESSION_ACCESS',
            FALSE,
            EXISTS (
                SELECT 1
                FROM pg_attribute attribute
                WHERE attribute.attrelid = 'app.auth_sessions'::regclass
                  AND attribute.attnum > 0
                  AND NOT attribute.attisdropped
                  AND (
                      has_column_privilege('megabrain_mgb020', 'app.auth_sessions', attribute.attname, 'SELECT')
                      OR has_column_privilege('megabrain_mgb020', 'app.auth_sessions', attribute.attname, 'INSERT')
                      OR has_column_privilege('megabrain_mgb020', 'app.auth_sessions', attribute.attname, 'UPDATE')
                  )
            ) OR has_table_privilege('megabrain_mgb020', 'app.auth_sessions', 'DELETE')
        ),
        ('MGB020_CATEGORY_ACCESS', FALSE, has_table_privilege('megabrain_mgb020', 'app.categories', 'SELECT')),
        ('MGB030_SCHEMA_USAGE', TRUE, has_schema_privilege('megabrain_mgb030', 'app', 'USAGE')),
        ('MGB030_SCHEMA_CREATE', FALSE, has_schema_privilege('megabrain_mgb030', 'app', 'CREATE')),
        (
            'MGB030_REELS_SELECT_SOURCE_COLUMNS',
            TRUE,
            NOT EXISTS (
                SELECT 1
                FROM unnest(ARRAY[
                    'id', 'shortcode', 'object_key', 'sha256', 'file_size_bytes',
                    'download_status', 'transcription_status', 'transcription_attempt_id'
                ]) AS required(column_name)
                WHERE NOT has_column_privilege(
                    'megabrain_mgb030', 'app.reels', required.column_name, 'SELECT'
                )
            )
        ),
        (
            'MGB030_REELS_TABLE_WIDE_SELECT',
            FALSE,
            has_table_privilege('megabrain_mgb030', 'app.reels', 'SELECT')
        ),
        (
            'MGB030_REELS_TABLE_WIDE_UPDATE',
            FALSE,
            has_table_privilege('megabrain_mgb030', 'app.reels', 'UPDATE')
        ),
        (
            'MGB030_REELS_EXCESS_SELECT',
            FALSE,
            EXISTS (
                SELECT 1
                FROM pg_attribute attribute
                WHERE attribute.attrelid = 'app.reels'::regclass
                  AND attribute.attnum > 0
                  AND NOT attribute.attisdropped
                  AND attribute.attname <> ALL (ARRAY[
                      'id', 'shortcode', 'object_key', 'sha256',
                      'file_size_bytes', 'download_status',
                      'transcription_status', 'transcription_attempt_id'
                  ])
                  AND has_column_privilege(
                      'megabrain_mgb030', 'app.reels', attribute.attname, 'SELECT'
                  )
            )
        ),
        (
            'MGB030_REELS_EXCESS_UPDATE',
            FALSE,
            EXISTS (
                SELECT 1
                FROM pg_attribute attribute
                WHERE attribute.attrelid = 'app.reels'::regclass
                  AND attribute.attnum > 0
                  AND NOT attribute.attisdropped
                  AND attribute.attname <> ALL (ARRAY[
                      'transcription_status', 'transcription_attempt_id', 'updated_at'
                  ])
                  AND has_column_privilege(
                      'megabrain_mgb030', 'app.reels', attribute.attname, 'UPDATE'
                  )
            )
        ),
        (
            'MGB030_CAN_WRITE_TRANSCRIPTION',
            TRUE,
            has_column_privilege('megabrain_mgb030', 'app.reels', 'transcription_status', 'UPDATE')
                AND has_column_privilege('megabrain_mgb030', 'app.reels', 'transcription_attempt_id', 'UPDATE')
                AND has_column_privilege('megabrain_mgb030', 'app.reels', 'updated_at', 'UPDATE')
        ),
        ('MGB030_CAN_WRITE_DOWNLOAD', FALSE, has_column_privilege('megabrain_mgb030', 'app.reels', 'download_status', 'UPDATE')),
        ('MGB030_CAN_WRITE_CURATION', FALSE, has_column_privilege('megabrain_mgb030', 'app.reels', 'curation_status', 'UPDATE')),
        ('MGB030_REELS_DELETE', FALSE, has_table_privilege('megabrain_mgb030', 'app.reels', 'DELETE')),
        (
            'MGB030_ATTEMPT_INSERT_AND_TERMINAL_UPDATE',
            TRUE,
            has_column_privilege('megabrain_mgb030', 'app.reel_enrichment_attempts', 'attempt_id', 'INSERT')
                AND has_column_privilege('megabrain_mgb030', 'app.reel_enrichment_attempts', 'status', 'UPDATE')
                AND has_column_privilege('megabrain_mgb030', 'app.reel_enrichment_attempts', 'error_message', 'UPDATE')
        ),
        (
            'MGB030_ENRICHMENT_RESULT_INSERT_AND_SEQUENCE',
            TRUE,
            has_column_privilege('megabrain_mgb030', 'app.reel_enrichments', 'outcome', 'INSERT')
                AND has_column_privilege('megabrain_mgb030', 'app.reel_enrichments', 'transcript_text', 'INSERT')
                AND has_sequence_privilege('megabrain_mgb030', 'app.reel_enrichments_id_seq', 'USAGE')
        ),
        (
            'MGB030_AUTH_ACCESS',
            FALSE,
            EXISTS (
                SELECT 1
                FROM pg_attribute attribute
                WHERE attribute.attrelid = 'app.auth_users'::regclass
                  AND attribute.attnum > 0
                  AND NOT attribute.attisdropped
                  AND (
                      has_column_privilege('megabrain_mgb030', 'app.auth_users', attribute.attname, 'SELECT')
                      OR has_column_privilege('megabrain_mgb030', 'app.auth_users', attribute.attname, 'INSERT')
                      OR has_column_privilege('megabrain_mgb030', 'app.auth_users', attribute.attname, 'UPDATE')
                  )
            ) OR has_table_privilege('megabrain_mgb030', 'app.auth_users', 'DELETE')
        ),
        (
            'MGB030_AUTH_TRANSACTION_ACCESS',
            FALSE,
            EXISTS (
                SELECT 1
                FROM pg_attribute attribute
                WHERE attribute.attrelid = 'app.auth_transactions'::regclass
                  AND attribute.attnum > 0
                  AND NOT attribute.attisdropped
                  AND (
                      has_column_privilege('megabrain_mgb030', 'app.auth_transactions', attribute.attname, 'SELECT')
                      OR has_column_privilege('megabrain_mgb030', 'app.auth_transactions', attribute.attname, 'INSERT')
                      OR has_column_privilege('megabrain_mgb030', 'app.auth_transactions', attribute.attname, 'UPDATE')
                  )
            ) OR has_table_privilege('megabrain_mgb030', 'app.auth_transactions', 'DELETE')
        ),
        (
            'MGB030_AUTH_SESSION_ACCESS',
            FALSE,
            EXISTS (
                SELECT 1
                FROM pg_attribute attribute
                WHERE attribute.attrelid = 'app.auth_sessions'::regclass
                  AND attribute.attnum > 0
                  AND NOT attribute.attisdropped
                  AND (
                      has_column_privilege('megabrain_mgb030', 'app.auth_sessions', attribute.attname, 'SELECT')
                      OR has_column_privilege('megabrain_mgb030', 'app.auth_sessions', attribute.attname, 'INSERT')
                      OR has_column_privilege('megabrain_mgb030', 'app.auth_sessions', attribute.attname, 'UPDATE')
                  )
            ) OR has_table_privilege('megabrain_mgb030', 'app.auth_sessions', 'DELETE')
        ),
        ('MGB030_CATEGORY_ACCESS', FALSE, has_table_privilege('megabrain_mgb030', 'app.categories', 'SELECT'))
)
SELECT
    name,
    CASE WHEN actual IS NOT DISTINCT FROM expected THEN 'PASS' ELSE 'FAIL' END AS result,
    expected,
    actual
FROM checks
ORDER BY name;

-- Effective authority allowlist. This second result set catches direct, PUBLIC,
-- and otherwise effective grants outside the exact reviewed source contract.
WITH roles(role_name) AS (
    VALUES ('megabrain_web'), ('megabrain_mgb020'), ('megabrain_mgb030')
), relations(relation_name) AS (
    VALUES ('app.reels'), ('app.reel_enrichment_attempts'), ('app.reel_enrichments'), ('app.categories'), ('app.reel_categories'), ('app.auth_transactions'), ('app.auth_users'), ('app.auth_sessions')
), allowed_columns(role_name, relation_name, privilege, columns) AS (
    VALUES
        ('megabrain_web','app.reels','SELECT',ARRAY['id','shortcode','original_url','source','download_status','curation_status','transcription_status','telegram_chat_id','telegram_user_id','telegram_message_id','raw_message','received_at','title','creator','caption','duration_seconds','filename','mime_type','file_size_bytes','storage_provider','storage_bucket','object_key','downloaded_at']),
        ('megabrain_web','app.reels','INSERT',ARRAY['shortcode','original_url','source','download_status','telegram_chat_id','telegram_user_id','telegram_message_id','raw_message','received_at']),
        ('megabrain_web','app.reels','UPDATE',ARRAY['curation_status']),
        ('megabrain_web','app.reel_enrichments','SELECT',ARRAY['id','reel_id','completed_at','media_duration_seconds','outcome','transcript_text','transcript_language']),
        ('megabrain_web','app.categories','SELECT',ARRAY['id','name']),
        ('megabrain_web','app.categories','INSERT',ARRAY['name']),
        ('megabrain_web','app.reel_categories','SELECT',ARRAY['reel_id','category_id']),
        ('megabrain_web','app.reel_categories','INSERT',ARRAY['reel_id','category_id']),
        ('megabrain_web','app.auth_transactions','SELECT',ARRAY['transaction_hash','state_hash','nonce','pkce_verifier','return_path','expires_at','consumed_at']),
        ('megabrain_web','app.auth_transactions','INSERT',ARRAY['transaction_hash','provider','state_hash','nonce','pkce_verifier','return_path','created_at','expires_at','consumed_at']),
        ('megabrain_web','app.auth_transactions','UPDATE',ARRAY['consumed_at']),
        ('megabrain_web','app.auth_users','SELECT',ARRAY['id','provider_issuer','provider_subject','disabled_at','email']),
        ('megabrain_web','app.auth_users','INSERT',ARRAY['provider','provider_issuer','provider_subject','email','email_normalized','created_at','updated_at','last_login_at','disabled_at']),
        ('megabrain_web','app.auth_users','UPDATE',ARRAY['email','email_normalized','updated_at','last_login_at']),
        ('megabrain_web','app.auth_sessions','SELECT',ARRAY['token_hash','user_id','expires_at','revoked_at']),
        ('megabrain_web','app.auth_sessions','INSERT',ARRAY['token_hash','user_id','created_at','expires_at','revoked_at']),
        ('megabrain_web','app.auth_sessions','UPDATE',ARRAY['revoked_at']),
        ('megabrain_mgb020','app.reels','SELECT',ARRAY['id','shortcode','original_url','telegram_chat_id','download_status','filename','file_size_bytes','storage_bucket','object_key','downloaded_at','error_message','retry_count']),
        ('megabrain_mgb020','app.reels','UPDATE',ARRAY['download_status','download_started_at','error_message','updated_at','title','creator','caption','duration_seconds','filename','mime_type','file_size_bytes','sha256','storage_provider','storage_bucket','object_key','downloaded_at','retry_count','last_error_at']),
        ('megabrain_mgb030','app.reels','SELECT',ARRAY['id','shortcode','object_key','sha256','file_size_bytes','download_status','transcription_status','transcription_attempt_id']),
        ('megabrain_mgb030','app.reels','UPDATE',ARRAY['transcription_status','transcription_attempt_id','updated_at']),
        ('megabrain_mgb030','app.reel_enrichment_attempts','SELECT',ARRAY['attempt_id','reel_id','source_object_key','expected_sha256','expected_size_bytes','pipeline_version','contract_version','language_hint','status','retryable','error_code','error_stage']),
        ('megabrain_mgb030','app.reel_enrichment_attempts','INSERT',ARRAY['attempt_id','reel_id','source_object_key','expected_sha256','expected_size_bytes','pipeline_version','contract_version','language_hint','retry_of_attempt_id','status','started_at']),
        ('megabrain_mgb030','app.reel_enrichment_attempts','UPDATE',ARRAY['status','finished_at','enricher_version','stt_provider','stt_model','provider_request_id','error_code','error_stage','error_message','retryable']),
        ('megabrain_mgb030','app.reel_enrichments','SELECT',ARRAY['id','reel_id','source_attempt_id','source_object_key','source_sha256','pipeline_version','outcome']),
        ('megabrain_mgb030','app.reel_enrichments','INSERT',ARRAY['reel_id','source_attempt_id','source_object_key','source_sha256','source_size_bytes','pipeline_version','completed_at','container_format','media_duration_seconds','video_codec','video_width','video_height','audio_present','audio_codec','audio_sample_rate_hz','audio_channels','audio_duration_seconds','transcription_audio_format','transcription_audio_sample_rate_hz','transcription_audio_channels','transcription_audio_duration_seconds','outcome','transcript_text','transcript_language'])
), allowed_table(role_name, relation_name, privilege) AS (
    VALUES ('megabrain_web','app.reel_categories','DELETE')
), sequences(sequence_name) AS (
    VALUES ('app.reels_id_seq'), ('app.categories_id_seq'), ('app.auth_users_id_seq'), ('app.reel_enrichments_id_seq')
), allowed_sequence(role_name, sequence_name, privilege) AS (
    VALUES ('megabrain_web','app.reels_id_seq','USAGE'), ('megabrain_web','app.categories_id_seq','USAGE'), ('megabrain_web','app.auth_users_id_seq','USAGE'), ('megabrain_mgb030','app.reel_enrichments_id_seq','USAGE')
), missing_columns AS (
    SELECT 1 FROM allowed_columns allowed CROSS JOIN LATERAL unnest(allowed.columns) required(column_name)
    WHERE NOT has_column_privilege(allowed.role_name, allowed.relation_name, required.column_name, allowed.privilege)
), excess_columns AS (
    SELECT 1 FROM roles role CROSS JOIN relations relation
    JOIN pg_attribute attribute ON attribute.attrelid = relation.relation_name::regclass
    CROSS JOIN unnest(ARRAY['SELECT','INSERT','UPDATE']) action(privilege)
    LEFT JOIN allowed_columns allowed ON allowed.role_name = role.role_name AND allowed.relation_name = relation.relation_name AND allowed.privilege = action.privilege
    WHERE attribute.attnum > 0 AND NOT attribute.attisdropped
      AND (allowed.columns IS NULL OR attribute.attname <> ALL (allowed.columns))
      AND has_column_privilege(role.role_name, relation.relation_name, attribute.attname, action.privilege)
), excess_table AS (
    SELECT 1 FROM roles role CROSS JOIN relations relation
    CROSS JOIN unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER','MAINTAIN']) action(privilege)
    LEFT JOIN allowed_table allowed ON allowed.role_name = role.role_name AND allowed.relation_name = relation.relation_name AND allowed.privilege = action.privilege
    WHERE allowed.role_name IS NULL
      AND CASE
          WHEN action.privilege = 'MAINTAIN'
               AND current_setting('server_version_num')::integer < 140000
              THEN FALSE
          ELSE has_table_privilege(role.role_name, relation.relation_name, action.privilege)
      END
), missing_sequence AS (
    SELECT 1 FROM allowed_sequence allowed
    WHERE NOT has_sequence_privilege(allowed.role_name, allowed.sequence_name, allowed.privilege)
), excess_sequence AS (
    SELECT 1 FROM roles role CROSS JOIN sequences sequence
    CROSS JOIN unnest(ARRAY['USAGE','SELECT','UPDATE']) action(privilege)
    LEFT JOIN allowed_sequence allowed ON allowed.role_name = role.role_name AND allowed.sequence_name = sequence.sequence_name AND allowed.privilege = action.privilege
    WHERE allowed.role_name IS NULL AND has_sequence_privilege(role.role_name, sequence.sequence_name, action.privilege)
), runtime_ownership AS (
    SELECT 1 FROM roles role JOIN pg_roles database_role ON database_role.rolname = role.role_name
    WHERE EXISTS (SELECT 1 FROM pg_namespace namespace WHERE namespace.nspname = 'app' AND namespace.nspowner = database_role.oid)
       OR EXISTS (SELECT 1 FROM relations relation JOIN pg_class object ON object.oid = relation.relation_name::regclass WHERE object.relowner = database_role.oid)
       OR EXISTS (SELECT 1 FROM sequences sequence JOIN pg_class object ON object.oid = sequence.sequence_name::regclass WHERE object.relowner = database_role.oid)
)
SELECT name, CASE WHEN actual THEN 'PASS' ELSE 'FAIL' END AS result
FROM (
    SELECT 'EFFECTIVE_COLUMN_ALLOWLIST' AS name, NOT EXISTS (SELECT 1 FROM missing_columns) AND NOT EXISTS (SELECT 1 FROM excess_columns) AS actual
    UNION ALL SELECT 'EFFECTIVE_TABLE_ALLOWLIST', NOT EXISTS (SELECT 1 FROM excess_table)
    UNION ALL SELECT 'EFFECTIVE_SEQUENCE_ALLOWLIST', NOT EXISTS (SELECT 1 FROM missing_sequence) AND NOT EXISTS (SELECT 1 FROM excess_sequence)
    UNION ALL SELECT 'RUNTIME_ROLES_OWN_NO_REVIEWED_OBJECTS', NOT EXISTS (SELECT 1 FROM runtime_ownership)
) AS allowlist_checks
ORDER BY name;
