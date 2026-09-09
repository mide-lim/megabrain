from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from psycopg import IntegrityError

from app import database
from app.auth.oidc import ValidatedIdentity

CREATE_AUTH_TRANSACTION_QUERY = """
INSERT INTO app.auth_transactions (
    transaction_hash, provider, state_hash, nonce, pkce_verifier, return_path,
    created_at, expires_at, consumed_at
)
VALUES (
    %s, %s, %s, %s, %s, %s,
    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP + INTERVAL '600 seconds', NULL
)
"""

CONSUME_AUTH_TRANSACTION_QUERY = """
UPDATE app.auth_transactions
SET consumed_at = CURRENT_TIMESTAMP
WHERE transaction_hash = %s
  AND state_hash = %s
  AND consumed_at IS NULL
  AND expires_at > CURRENT_TIMESTAMP
RETURNING nonce, pkce_verifier, return_path
"""

RESOLVE_OR_BOOTSTRAP_OWNER_QUERY = """
WITH existing_subject AS (
    SELECT id, disabled_at
    FROM app.auth_users
    WHERE provider_issuer = %s AND provider_subject = %s
    FOR UPDATE
), updated_subject AS (
    UPDATE app.auth_users
    SET email = %s,
        email_normalized = %s,
        updated_at = CURRENT_TIMESTAMP,
        last_login_at = CURRENT_TIMESTAMP
    WHERE id IN (SELECT id FROM existing_subject)
      AND disabled_at IS NULL
    RETURNING id
), created_owner AS (
    INSERT INTO app.auth_users (
        provider, provider_issuer, provider_subject, email, email_normalized,
        created_at, updated_at, last_login_at, disabled_at
    )
    SELECT
        'google', %s, %s, %s, %s,
        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL
    WHERE NOT EXISTS (SELECT 1 FROM existing_subject)
      AND %s = %s
    ON CONFLICT (provider_issuer, provider_subject) DO NOTHING
    RETURNING id
)
SELECT id FROM updated_subject
UNION ALL
SELECT id FROM created_owner
"""

CREATE_SESSION_QUERY = """
INSERT INTO app.auth_sessions (token_hash, user_id, created_at, expires_at, revoked_at)
VALUES (
    %s, %s, CURRENT_TIMESTAMP,
    CURRENT_TIMESTAMP + INTERVAL '604800 seconds', NULL
)
"""


class OwnerAuthorizationError(RuntimeError):
    """Raised when a validated Google identity is not the configured owner."""


@dataclass(frozen=True)
class ConsumedAuthTransaction:
    nonce: str
    pkce_verifier: str
    return_path: str


def _field(row: Any, name: str, position: int) -> Any:
    return row[name] if isinstance(row, dict) else row[position]


def create_auth_transaction(
    *,
    transaction_hash: bytes,
    state_hash: bytes,
    nonce: str,
    pkce_verifier: str,
    return_path: str,
) -> None:
    with database.connect() as connection, connection.cursor() as cursor:
        cursor.execute(
            CREATE_AUTH_TRANSACTION_QUERY,
            (
                transaction_hash,
                "google",
                state_hash,
                nonce,
                pkce_verifier,
                return_path,
            ),
        )


def consume_auth_transaction(
    transaction_hash: bytes, state_hash: bytes
) -> ConsumedAuthTransaction | None:
    with database.connect() as connection, connection.cursor() as cursor:
        cursor.execute(CONSUME_AUTH_TRANSACTION_QUERY, (transaction_hash, state_hash))
        row = cursor.fetchone()
    if row is None:
        return None
    return ConsumedAuthTransaction(
        nonce=_field(row, "nonce", 0),
        pkce_verifier=_field(row, "pkce_verifier", 1),
        return_path=_field(row, "return_path", 2),
    )


def resolve_or_bootstrap_owner(
    identity: ValidatedIdentity, configured_owner_email: str
) -> int:
    email_normalized = identity.email.strip().casefold()
    try:
        with database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                RESOLVE_OR_BOOTSTRAP_OWNER_QUERY,
                (
                    identity.provider_issuer,
                    identity.provider_subject,
                    identity.email,
                    email_normalized,
                    identity.provider_issuer,
                    identity.provider_subject,
                    identity.email,
                    email_normalized,
                    email_normalized,
                    configured_owner_email,
                ),
            )
            row = cursor.fetchone()
    except IntegrityError as error:
        # The database's single-owner uniqueness invariant is the final race guard.
        raise OwnerAuthorizationError("owner identity is already bound") from error

    if row is None:
        raise OwnerAuthorizationError("identity is not an enabled configured owner")
    return int(_field(row, "id", 0))


def create_session(*, user_id: int, token_hash: bytes) -> None:
    with database.connect() as connection, connection.cursor() as cursor:
        cursor.execute(CREATE_SESSION_QUERY, (token_hash, user_id))
