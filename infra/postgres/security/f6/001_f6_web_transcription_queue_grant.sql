-- F6 Web transcription-request queue authority overlay.
--
-- SOURCE ARTIFACT ONLY. Execute only during a separately human-authorized
-- TC4-WEB-QUEUE-AUTHORITY rollout, as a role administrator. This additive
-- overlay changes neither role attributes, memberships, passwords, nor LOGIN.

\set ON_ERROR_STOP on

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

    IF to_regclass('app.reels') IS NULL THEN
        RAISE EXCEPTION 'app.reels is required';
    END IF;

    IF (
        SELECT count(*)
        FROM information_schema.columns
        WHERE table_schema = 'app'
          AND table_name = 'reels'
          AND column_name IN (
              'transcription_status',
              'transcription_attempt_id',
              'updated_at'
          )
    ) <> 3 THEN
        RAISE EXCEPTION 'F6 Web transcription queue columns are required';
    END IF;
END
$$;

-- The fallback lifecycle read requires this internal attempt identity.
GRANT SELECT (transcription_attempt_id)
ON TABLE app.reels
TO megabrain_web;

-- The owner-authenticated Web API may only request the queue transition.
GRANT UPDATE (
    transcription_status,
    transcription_attempt_id,
    updated_at
)
ON TABLE app.reels
TO megabrain_web;

COMMIT;
