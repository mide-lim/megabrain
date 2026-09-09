-- F1 authentication foundation persistence.
-- This migration is additive and creates only application authentication objects.

CREATE TABLE app.auth_users (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    provider TEXT NOT NULL CHECK (provider = 'google'),
    provider_issuer TEXT NOT NULL CHECK (provider_issuer <> ''),
    provider_subject TEXT NOT NULL CHECK (provider_subject <> ''),
    email TEXT NOT NULL CHECK (email <> ''),
    email_normalized TEXT NOT NULL CHECK (email_normalized <> ''),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_login_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    disabled_at TIMESTAMPTZ,

    CONSTRAINT auth_users_provider_issuer_subject_unique
        UNIQUE (provider_issuer, provider_subject),
    CONSTRAINT auth_users_provider_unique UNIQUE (provider)
);

CREATE TABLE app.auth_sessions (
    token_hash BYTEA PRIMARY KEY CHECK (octet_length(token_hash) = 32),
    user_id BIGINT NOT NULL REFERENCES app.auth_users(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,

    CONSTRAINT auth_sessions_expiry_after_creation
        CHECK (expires_at > created_at),
    CONSTRAINT auth_sessions_revocation_after_creation
        CHECK (revoked_at IS NULL OR revoked_at >= created_at)
);

CREATE TABLE app.auth_transactions (
    transaction_hash BYTEA PRIMARY KEY CHECK (octet_length(transaction_hash) = 32),
    provider TEXT NOT NULL CHECK (provider = 'google'),
    state_hash BYTEA NOT NULL CHECK (octet_length(state_hash) = 32),
    nonce TEXT NOT NULL CHECK (nonce <> ''),
    pkce_verifier TEXT NOT NULL CHECK (pkce_verifier <> ''),
    return_path TEXT NOT NULL CHECK (return_path <> ''),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,

    CONSTRAINT auth_transactions_expiry_after_creation
        CHECK (expires_at > created_at),
    CONSTRAINT auth_transactions_consumption_after_creation
        CHECK (consumed_at IS NULL OR consumed_at >= created_at)
);
