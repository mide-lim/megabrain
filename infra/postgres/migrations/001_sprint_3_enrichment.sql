-- Sprint 3 enrichment persistence.
-- This migration intentionally leaves app.reels unchanged. MGB-030 owns
-- orchestration and must create/update these rows transactionally.

CREATE SCHEMA IF NOT EXISTS app;

CREATE TABLE app.reel_enrichment_attempts (
    attempt_id UUID PRIMARY KEY,
    reel_id BIGINT NOT NULL REFERENCES app.reels(id),
    source_object_key TEXT NOT NULL CHECK (source_object_key <> ''),
    expected_sha256 CHAR(64) NOT NULL
        CHECK (expected_sha256 ~ '^[0-9a-f]{64}$'),
    expected_size_bytes BIGINT CHECK (expected_size_bytes > 0),
    pipeline_version TEXT NOT NULL CHECK (pipeline_version <> ''),
    contract_version TEXT NOT NULL CHECK (contract_version <> ''),
    language_hint TEXT,
    status TEXT NOT NULL CHECK (status IN ('processing', 'completed', 'failed')),
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    retry_of_attempt_id UUID,
    enricher_version TEXT,
    stt_provider TEXT,
    stt_model TEXT,
    provider_request_id TEXT,
    error_code TEXT,
    error_stage TEXT,
    error_message TEXT,
    retryable BOOLEAN,

    CONSTRAINT reel_enrichment_attempts_attempt_reel_unique
        UNIQUE (attempt_id, reel_id),
    CONSTRAINT reel_enrichment_attempts_attempt_input_unique
        UNIQUE (
            attempt_id,
            reel_id,
            source_object_key,
            expected_sha256,
            pipeline_version
        ),
    CONSTRAINT reel_enrichment_attempts_retry_same_reel_fk
        FOREIGN KEY (retry_of_attempt_id, reel_id)
        REFERENCES app.reel_enrichment_attempts(attempt_id, reel_id),
    CONSTRAINT reel_enrichment_attempts_retry_not_self
        CHECK (retry_of_attempt_id IS NULL OR retry_of_attempt_id <> attempt_id),
    CONSTRAINT reel_enrichment_attempts_status_fields_check CHECK (
        (status = 'processing'
            AND finished_at IS NULL
            AND error_code IS NULL
            AND error_stage IS NULL
            AND error_message IS NULL
            AND retryable IS NULL)
        OR (status = 'completed'
            AND finished_at IS NOT NULL
            AND error_code IS NULL
            AND error_stage IS NULL
            AND error_message IS NULL
            AND retryable IS NULL)
        OR (status = 'failed'
            AND finished_at IS NOT NULL
            AND error_code IS NOT NULL
            AND error_stage IS NOT NULL
            AND error_message IS NOT NULL
            AND retryable IS NOT NULL)
    )
);

CREATE UNIQUE INDEX reel_enrichment_attempts_one_processing_input_idx
    ON app.reel_enrichment_attempts (
        reel_id,
        source_object_key,
        expected_sha256,
        pipeline_version
    )
    WHERE status = 'processing';

CREATE OR REPLACE FUNCTION app.prevent_terminal_enrichment_attempt_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.status IN ('completed', 'failed') AND NEW IS DISTINCT FROM OLD THEN
        RAISE EXCEPTION 'terminal enrichment attempt % is immutable', OLD.attempt_id;
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER reel_enrichment_attempts_terminal_immutable
BEFORE UPDATE ON app.reel_enrichment_attempts
FOR EACH ROW
EXECUTE FUNCTION app.prevent_terminal_enrichment_attempt_mutation();

CREATE TABLE app.reel_enrichments (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    reel_id BIGINT NOT NULL REFERENCES app.reels(id),
    source_attempt_id UUID NOT NULL UNIQUE,
    source_object_key TEXT NOT NULL CHECK (source_object_key <> ''),
    source_sha256 CHAR(64) NOT NULL
        CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
    source_size_bytes BIGINT NOT NULL CHECK (source_size_bytes > 0),
    pipeline_version TEXT NOT NULL CHECK (pipeline_version <> ''),
    completed_at TIMESTAMPTZ NOT NULL,

    container_format TEXT NOT NULL CHECK (container_format <> ''),
    media_duration_seconds NUMERIC NOT NULL CHECK (media_duration_seconds >= 0),
    video_codec TEXT NOT NULL CHECK (video_codec <> ''),
    video_width INTEGER NOT NULL CHECK (video_width > 0),
    video_height INTEGER NOT NULL CHECK (video_height > 0),
    audio_present BOOLEAN NOT NULL,
    audio_codec TEXT,
    audio_sample_rate_hz INTEGER,
    audio_channels INTEGER,
    audio_duration_seconds NUMERIC,
    transcription_audio_format TEXT,
    transcription_audio_sample_rate_hz INTEGER,
    transcription_audio_channels INTEGER,
    transcription_audio_duration_seconds NUMERIC,

    outcome TEXT NOT NULL,
    transcript_text TEXT,
    transcript_language TEXT,

    CONSTRAINT reel_enrichments_source_attempt_input_fk
        FOREIGN KEY (
            source_attempt_id,
            reel_id,
            source_object_key,
            source_sha256,
            pipeline_version
        ) REFERENCES app.reel_enrichment_attempts (
            attempt_id,
            reel_id,
            source_object_key,
            expected_sha256,
            pipeline_version
        ),
    CONSTRAINT reel_enrichments_semantic_input_unique
        UNIQUE (reel_id, source_object_key, source_sha256, pipeline_version),
    CONSTRAINT reel_enrichments_audio_fields_check CHECK (
        (NOT audio_present
            AND audio_codec IS NULL
            AND audio_sample_rate_hz IS NULL
            AND audio_channels IS NULL
            AND audio_duration_seconds IS NULL
            AND transcription_audio_format IS NULL
            AND transcription_audio_sample_rate_hz IS NULL
            AND transcription_audio_channels IS NULL
            AND transcription_audio_duration_seconds IS NULL)
        OR (audio_present
            AND audio_codec IS NOT NULL
            AND audio_sample_rate_hz > 0
            AND audio_channels > 0
            AND (audio_duration_seconds IS NULL OR audio_duration_seconds >= 0)
            AND transcription_audio_format IS NOT NULL
            AND transcription_audio_sample_rate_hz > 0
            AND transcription_audio_channels > 0
            AND transcription_audio_duration_seconds >= 0)
    ),
    CONSTRAINT reel_enrichments_outcome_check CHECK (
        (outcome = 'no_audio'
            AND NOT audio_present
            AND transcript_text IS NULL
            AND transcript_language IS NULL)
        OR (outcome = 'transcribed'
            AND audio_present
            AND transcript_text IS NOT NULL
            AND btrim(transcript_text) <> '')
        OR (outcome = 'empty_transcript'
            AND audio_present
            AND transcript_text = '')
    )
);

CREATE OR REPLACE FUNCTION app.require_completed_enrichment_source_attempt()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM app.reel_enrichment_attempts AS attempt
        WHERE attempt.attempt_id = NEW.source_attempt_id
          AND attempt.status = 'completed'
    ) THEN
        RAISE EXCEPTION 'source attempt % must be completed', NEW.source_attempt_id;
    END IF;

    RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER reel_enrichments_source_attempt_completed
AFTER INSERT OR UPDATE ON app.reel_enrichments
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW
EXECUTE FUNCTION app.require_completed_enrichment_source_attempt();
