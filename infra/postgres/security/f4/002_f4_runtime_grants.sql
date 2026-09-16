-- F4 final runtime grants. Execute only after migration 005 has committed and
-- the incompatible Reel readers and writers are quiesced. Run as megabrain (or
-- another separately authorized role administrator), never as a runtime role.
--
-- This script deliberately does not modify PUBLIC privileges or role memberships.
-- The read-only verifier must pass after execution; a failure caused by inherited
-- or PUBLIC authority is human remediation, not permission to broaden this file.

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

    IF (
        SELECT count(*)
        FROM pg_roles
        WHERE rolname IN ('megabrain_mgb020', 'megabrain_mgb030')
    ) <> 2 THEN
        RAISE EXCEPTION 'both dedicated F4 runtime roles are required';
    END IF;

    IF to_regclass('app.reels') IS NULL
       OR to_regclass('app.reel_enrichment_attempts') IS NULL
       OR to_regclass('app.reel_enrichments') IS NULL
       OR to_regclass('app.categories') IS NULL
       OR to_regclass('app.reel_categories') IS NULL
       OR to_regclass('app.auth_transactions') IS NULL
       OR to_regclass('app.auth_users') IS NULL
       OR to_regclass('app.auth_sessions') IS NULL
       OR to_regclass('app.reels_id_seq') IS NULL
       OR to_regclass('app.categories_id_seq') IS NULL
       OR to_regclass('app.auth_users_id_seq') IS NULL
       OR to_regclass('app.reel_enrichments_id_seq') IS NULL THEN
        RAISE EXCEPTION 'required F4 relations or identity sequences are missing';
    END IF;

    IF (
        SELECT count(*)
        FROM information_schema.columns
        WHERE table_schema = 'app'
          AND table_name = 'reels'
          AND column_name IN (
              'download_status',
              'curation_status',
              'transcription_status',
              'transcription_attempt_id'
          )
    ) <> 4 THEN
        RAISE EXCEPTION 'migration 005 final Reel lifecycle columns are required';
    END IF;
END
$$;

-- Remove only direct grants to the three F4 runtime principals, then restore the
-- exact source-derived grants below. This cannot counter PUBLIC or inherited
-- privileges; the verifier detects either as a failed authority boundary.
REVOKE ALL PRIVILEGES ON SCHEMA app
    FROM megabrain_web, megabrain_mgb020, megabrain_mgb030;
REVOKE CREATE ON SCHEMA app FROM megabrain_mgb020;
REVOKE CREATE ON SCHEMA app FROM megabrain_mgb030;

REVOKE ALL PRIVILEGES ON TABLE
    app.reels,
    app.reel_enrichment_attempts,
    app.reel_enrichments,
    app.categories,
    app.reel_categories,
    app.auth_transactions,
    app.auth_users,
    app.auth_sessions
FROM megabrain_web, megabrain_mgb020, megabrain_mgb030;

REVOKE ALL PRIVILEGES ON SEQUENCE
    app.reels_id_seq,
    app.categories_id_seq,
    app.auth_users_id_seq,
    app.reel_enrichments_id_seq
FROM megabrain_web, megabrain_mgb020, megabrain_mgb030;

GRANT USAGE ON SCHEMA app TO megabrain_web;
GRANT USAGE ON SCHEMA app TO megabrain_mgb020, megabrain_mgb030;

-- Web: registration, library/detail reads, owner curation, categories, and auth.
GRANT SELECT (
    id, shortcode, original_url, source, download_status, curation_status,
    transcription_status, telegram_chat_id, telegram_user_id,
    telegram_message_id, raw_message, received_at, title, creator, caption,
    duration_seconds, filename, mime_type, file_size_bytes, storage_provider,
    storage_bucket, object_key, downloaded_at
) ON TABLE app.reels TO megabrain_web;
GRANT INSERT (
    shortcode, original_url, source, download_status, telegram_chat_id,
    telegram_user_id, telegram_message_id, raw_message, received_at
) ON TABLE app.reels TO megabrain_web;
GRANT UPDATE (curation_status) ON TABLE app.reels TO megabrain_web;
GRANT USAGE ON SEQUENCE app.reels_id_seq TO megabrain_web;

GRANT SELECT (
    id, reel_id, completed_at, media_duration_seconds, outcome, transcript_text,
    transcript_language
) ON TABLE app.reel_enrichments TO megabrain_web;

GRANT SELECT (id, name) ON TABLE app.categories TO megabrain_web;
GRANT INSERT (name) ON TABLE app.categories TO megabrain_web;
GRANT USAGE ON SEQUENCE app.categories_id_seq TO megabrain_web;
GRANT SELECT (reel_id, category_id) ON TABLE app.reel_categories TO megabrain_web;
GRANT INSERT (reel_id, category_id) ON TABLE app.reel_categories TO megabrain_web;
GRANT DELETE ON TABLE app.reel_categories TO megabrain_web;

GRANT SELECT (
    transaction_hash, state_hash, nonce, pkce_verifier, return_path, expires_at,
    consumed_at
) ON TABLE app.auth_transactions TO megabrain_web;
GRANT INSERT (
    transaction_hash, provider, state_hash, nonce, pkce_verifier, return_path,
    created_at, expires_at, consumed_at
) ON TABLE app.auth_transactions TO megabrain_web;
GRANT UPDATE (consumed_at) ON TABLE app.auth_transactions TO megabrain_web;

GRANT SELECT (id, provider_issuer, provider_subject, disabled_at, email)
    ON TABLE app.auth_users TO megabrain_web;
GRANT INSERT (
    provider, provider_issuer, provider_subject, email, email_normalized,
    created_at, updated_at, last_login_at, disabled_at
) ON TABLE app.auth_users TO megabrain_web;
GRANT UPDATE (email, email_normalized, updated_at, last_login_at)
    ON TABLE app.auth_users TO megabrain_web;
GRANT USAGE ON SEQUENCE app.auth_users_id_seq TO megabrain_web;

GRANT SELECT (token_hash, user_id, expires_at, revoked_at)
    ON TABLE app.auth_sessions TO megabrain_web;
GRANT INSERT (token_hash, user_id, created_at, expires_at, revoked_at)
    ON TABLE app.auth_sessions TO megabrain_web;
GRANT UPDATE (revoked_at) ON TABLE app.auth_sessions TO megabrain_web;

-- MGB-020: download claim and terminal download transitions only.
GRANT SELECT (
    id, shortcode, original_url, telegram_chat_id, download_status, filename,
    file_size_bytes, storage_bucket, object_key, downloaded_at, error_message,
    retry_count
) ON TABLE app.reels TO megabrain_mgb020;
GRANT UPDATE (
    download_status, download_started_at, error_message, updated_at, title,
    creator, caption, duration_seconds, filename, mime_type, file_size_bytes,
    sha256, storage_provider, storage_bucket, object_key, downloaded_at,
    retry_count, last_error_at
) ON TABLE app.reels TO megabrain_mgb020;

-- MGB-030: transcription lifecycle and its enrichment attempt/result relations.
GRANT SELECT (
    id, shortcode, object_key, sha256, file_size_bytes, download_status,
    transcription_status, transcription_attempt_id
) ON TABLE app.reels TO megabrain_mgb030;
GRANT UPDATE (transcription_status, transcription_attempt_id, updated_at)
    ON TABLE app.reels TO megabrain_mgb030;

GRANT SELECT (
    attempt_id, reel_id, source_object_key, expected_sha256,
    expected_size_bytes, pipeline_version, contract_version, language_hint,
    status, retryable, error_code, error_stage
) ON TABLE app.reel_enrichment_attempts TO megabrain_mgb030;
GRANT INSERT (
    attempt_id, reel_id, source_object_key, expected_sha256,
    expected_size_bytes, pipeline_version, contract_version, language_hint,
    retry_of_attempt_id, status, started_at
) ON TABLE app.reel_enrichment_attempts TO megabrain_mgb030;
GRANT UPDATE (
    status, finished_at, enricher_version, stt_provider, stt_model,
    provider_request_id, error_code, error_stage, error_message, retryable
) ON TABLE app.reel_enrichment_attempts TO megabrain_mgb030;

GRANT SELECT (
    id, reel_id, source_attempt_id, source_object_key, source_sha256,
    pipeline_version, outcome
) ON TABLE app.reel_enrichments TO megabrain_mgb030;
GRANT INSERT (
    reel_id, source_attempt_id, source_object_key, source_sha256,
    source_size_bytes, pipeline_version, completed_at, container_format,
    media_duration_seconds, video_codec, video_width, video_height,
    audio_present, audio_codec, audio_sample_rate_hz, audio_channels,
    audio_duration_seconds, transcription_audio_format,
    transcription_audio_sample_rate_hz, transcription_audio_channels,
    transcription_audio_duration_seconds, outcome, transcript_text,
    transcript_language
) ON TABLE app.reel_enrichments TO megabrain_mgb030;
GRANT USAGE ON SEQUENCE app.reel_enrichments_id_seq TO megabrain_mgb030;

COMMIT;
