from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.auth import repository
from app.auth.oidc import ValidatedIdentity


@dataclass
class FakeCursor:
    rows: list[object]
    calls: list[tuple[str, tuple[object, ...]]]

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, query: str, parameters: tuple[object, ...]) -> None:
        self.calls.append((query, parameters))

    def fetchone(self) -> object | None:
        return self.rows.pop(0) if self.rows else None


@dataclass
class FakeConnection:
    cursor_instance: FakeCursor

    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def cursor(self) -> FakeCursor:
        return self.cursor_instance


def fake_connection(monkeypatch, *rows: object) -> list[tuple[str, tuple[object, ...]]]:
    calls: list[tuple[str, tuple[object, ...]]] = []
    cursor = FakeCursor(list(rows), calls)
    monkeypatch.setattr(
        repository.database,
        "connect",
        lambda: FakeConnection(cursor),
    )
    return calls


def test_create_transaction_persists_only_hashes_and_server_side_values(monkeypatch) -> None:
    calls = fake_connection(monkeypatch)
    transaction_hash = b"t" * 32
    state_hash = b"s" * 32

    repository.create_auth_transaction(
        transaction_hash=transaction_hash,
        state_hash=state_hash,
        nonce="nonce-value",
        pkce_verifier="verifier-value",
        return_path="/library",
    )

    query, parameters = calls[0]
    assert "INSERT INTO app.auth_transactions" in query
    assert "CURRENT_TIMESTAMP + INTERVAL '600 seconds'" in query
    assert parameters == (transaction_hash, "google", state_hash, "nonce-value", "verifier-value", "/library")
    assert b"raw-transaction" not in parameters
    assert b"raw-state" not in parameters


def test_consume_transaction_is_atomic_and_replay_returns_none(monkeypatch) -> None:
    calls = fake_connection(monkeypatch, ("nonce", "verifier", "/library"), None)

    first = repository.consume_auth_transaction(b"t" * 32, b"s" * 32)
    replay = repository.consume_auth_transaction(b"t" * 32, b"s" * 32)

    assert first == repository.ConsumedAuthTransaction("nonce", "verifier", "/library")
    assert replay is None
    query, parameters = calls[0]
    assert "UPDATE app.auth_transactions" in query
    assert "consumed_at IS NULL" in query
    assert "expires_at > CURRENT_TIMESTAMP" in query
    assert "RETURNING" in query
    assert parameters == (b"t" * 32, b"s" * 32)


def test_owner_bootstrap_updates_only_matching_durable_subject(monkeypatch) -> None:
    calls = fake_connection(monkeypatch, (42,))
    identity = ValidatedIdentity(
        provider_issuer="https://accounts.google.com",
        provider_subject="google-subject",
        email="Changed@Example.com",
        email_verified=True,
    )

    user_id = repository.resolve_or_bootstrap_owner(identity, "owner@example.com")

    assert user_id == 42
    query, parameters = calls[0]
    assert "WITH existing_subject AS" in query
    assert "updated_subject AS" in query
    assert "created_owner AS" in query
    assert "WHERE NOT EXISTS (SELECT 1 FROM existing_subject)" in query
    assert "email_normalized" in query
    assert parameters[-2:] == ("changed@example.com", "owner@example.com")


def test_different_subject_or_disabled_owner_fails_closed(monkeypatch) -> None:
    identity = ValidatedIdentity(
        provider_issuer="https://accounts.google.com",
        provider_subject="new-subject",
        email="owner@example.com",
        email_verified=True,
    )
    fake_connection(monkeypatch, None)

    with pytest.raises(repository.OwnerAuthorizationError):
        repository.resolve_or_bootstrap_owner(identity, "owner@example.com")


def test_concurrent_bootstrap_relies_on_database_conflict_without_rebinding(monkeypatch) -> None:
    calls = fake_connection(monkeypatch, (1,), None)
    first = ValidatedIdentity(GOOGLE_ISSUER, "subject-one", "owner@example.com", True)
    second = ValidatedIdentity(GOOGLE_ISSUER, "subject-two", "owner@example.com", True)

    assert repository.resolve_or_bootstrap_owner(first, "owner@example.com") == 1
    with pytest.raises(repository.OwnerAuthorizationError):
        repository.resolve_or_bootstrap_owner(second, "owner@example.com")

    assert all("provider_subject" in query for query, _ in calls)


def test_create_session_persists_only_the_opaque_token_hash(monkeypatch) -> None:
    calls = fake_connection(monkeypatch)
    repository.create_session(user_id=9, token_hash=b"x" * 32)

    query, parameters = calls[0]
    assert "INSERT INTO app.auth_sessions" in query
    assert "CURRENT_TIMESTAMP + INTERVAL '604800 seconds'" in query
    assert parameters == (b"x" * 32, 9)
    serialized = repr((query, parameters)).lower()
    for forbidden in ("access_token", "refresh_token", "id_token", "authorization_code"):
        assert forbidden not in serialized


GOOGLE_ISSUER = "https://accounts.google.com"
