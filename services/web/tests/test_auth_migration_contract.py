from __future__ import annotations

import re
from pathlib import Path


MIGRATION_PATH = (
    Path(__file__).resolve().parents[3]
    / "infra/postgres/migrations/003_f1_authentication_foundation.sql"
)
FORBIDDEN_PERSISTED_COLUMNS = (
    "access_token",
    "refresh_token",
    "id_token",
    "authorization_code",
    "password",
)


def _migration_text() -> str:
    assert MIGRATION_PATH.is_file(), f"missing migration: {MIGRATION_PATH}"
    return MIGRATION_PATH.read_text(encoding="utf-8")


def _table_definition(sql: str, table_name: str) -> str:
    match = re.search(
        rf"CREATE\s+TABLE\s+app\.{re.escape(table_name)}\s*\((.*?)\n\);",
        sql,
        flags=re.IGNORECASE | re.DOTALL,
    )
    assert match, f"missing app.{table_name} table definition"
    return match.group(1)


def _has_column(definition: str, column_name: str) -> bool:
    return bool(
        re.search(
            rf"(?mi)^\s*{re.escape(column_name)}\s+",
            definition,
        )
    )


def test_authentication_migration_defines_only_the_required_additive_schema() -> None:
    sql = _migration_text()
    created_tables = re.findall(
        r"CREATE\s+TABLE\s+app\.([a-z_]+)", sql, flags=re.IGNORECASE
    )

    assert created_tables == ["auth_users", "auth_sessions", "auth_transactions"]
    assert not re.search(r"\b(?:DROP|TRUNCATE|ALTER)\b", sql, flags=re.IGNORECASE)
    assert not re.search(r"CREATE\s+(?:UNIQUE\s+)?INDEX\b", sql, flags=re.IGNORECASE)


def test_auth_users_enforce_google_identity_and_single_owner() -> None:
    definition = _table_definition(_migration_text(), "auth_users")

    for column_name in (
        "id",
        "provider",
        "provider_issuer",
        "provider_subject",
        "email",
        "email_normalized",
        "created_at",
        "updated_at",
        "last_login_at",
        "disabled_at",
    ):
        assert _has_column(definition, column_name)

    assert re.search(r"provider\s*=\s*'google'", definition, flags=re.IGNORECASE)
    assert re.search(
        r"UNIQUE\s*\(\s*provider_issuer\s*,\s*provider_subject\s*\)",
        definition,
        flags=re.IGNORECASE,
    )
    assert re.search(
        r"UNIQUE\s*\(\s*provider\s*\)", definition, flags=re.IGNORECASE
    )
    assert not re.search(
        r"email_normalized\s*=\s*(?:lower|btrim)", definition, flags=re.IGNORECASE
    )


def test_auth_sessions_store_only_fixed_length_hashes_and_validate_lifecycle() -> None:
    definition = _table_definition(_migration_text(), "auth_sessions")

    assert re.search(r"token_hash\s+BYTEA\s+PRIMARY\s+KEY", definition, re.IGNORECASE)
    assert re.search(
        r"octet_length\s*\(\s*token_hash\s*\)\s*=\s*32",
        definition,
        flags=re.IGNORECASE,
    )
    assert re.search(
        r"user_id\s+BIGINT\s+NOT\s+NULL\s+REFERENCES\s+app\.auth_users\s*\(\s*id\s*\)\s+ON\s+DELETE\s+RESTRICT",
        definition,
        flags=re.IGNORECASE,
    )
    assert re.search(r"expires_at\s*>\s*created_at", definition, re.IGNORECASE)
    assert re.search(
        r"revoked_at\s+IS\s+NULL\s+OR\s+revoked_at\s*>=\s*created_at",
        definition,
        flags=re.IGNORECASE,
    )


def test_auth_transactions_match_atomic_consume_storage_contract() -> None:
    definition = _table_definition(_migration_text(), "auth_transactions")

    for hash_column in ("transaction_hash", "state_hash"):
        assert re.search(
            rf"{hash_column}\s+BYTEA", definition, flags=re.IGNORECASE
        )
        assert re.search(
            rf"octet_length\s*\(\s*{hash_column}\s*\)\s*=\s*32",
            definition,
            flags=re.IGNORECASE,
        )
    assert re.search(
        r"transaction_hash\s+BYTEA\s+PRIMARY\s+KEY",
        definition,
        flags=re.IGNORECASE,
    )
    for column_name in (
        "provider",
        "nonce",
        "pkce_verifier",
        "return_path",
        "created_at",
        "expires_at",
        "consumed_at",
    ):
        assert _has_column(definition, column_name)

    assert re.search(r"provider\s*=\s*'google'", definition, flags=re.IGNORECASE)
    assert re.search(r"expires_at\s*>\s*created_at", definition, re.IGNORECASE)
    assert re.search(
        r"consumed_at\s+IS\s+NULL\s+OR\s+consumed_at\s*>=\s*created_at",
        definition,
        flags=re.IGNORECASE,
    )
    assert not re.search(
        r"UNIQUE\s*\(\s*state_hash\s*\)", definition, flags=re.IGNORECASE
    )


def test_authentication_tables_do_not_persist_provider_tokens_or_passwords() -> None:
    sql = _migration_text()
    definitions = "\n".join(
        _table_definition(sql, table_name)
        for table_name in ("auth_users", "auth_sessions", "auth_transactions")
    )

    for column_name in FORBIDDEN_PERSISTED_COLUMNS:
        assert not _has_column(definitions, column_name)
