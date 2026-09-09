from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from app import main
from app.auth import config, repository, routes
from app.csrf import CSRF_COOKIE_NAME


@dataclass
class FakeCursor:
    row: object | None
    calls: list[tuple[str, tuple[object, ...]]]

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, query: str, parameters: tuple[object, ...]) -> None:
        self.calls.append((query, parameters))

    def fetchone(self) -> object | None:
        return self.row


@dataclass
class FakeConnection:
    cursor_instance: FakeCursor

    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def cursor(self) -> FakeCursor:
        return self.cursor_instance


def test_session_lookup_queries_only_active_enabled_local_identity(monkeypatch) -> None:
    calls: list[tuple[str, tuple[object, ...]]] = []
    monkeypatch.setattr(
        repository.database,
        "connect",
        lambda: FakeConnection(FakeCursor((7, "owner@example.com"), calls)),
    )

    identity = repository.resolve_session(b"x" * 32)

    assert identity == repository.SessionIdentity(user_id=7, email="owner@example.com")
    query, parameters = calls[0]
    assert "JOIN app.auth_users AS u" in query
    assert "s.revoked_at IS NULL" in query
    assert "s.expires_at > CURRENT_TIMESTAMP" in query
    assert "u.disabled_at IS NULL" in query
    assert parameters == (b"x" * 32,)


def test_revoke_session_is_parameterized_and_idempotent(monkeypatch) -> None:
    calls: list[tuple[str, tuple[object, ...]]] = []
    monkeypatch.setattr(
        repository.database,
        "connect",
        lambda: FakeConnection(FakeCursor(None, calls)),
    )

    repository.revoke_session(b"x" * 32)

    query, parameters = calls[0]
    assert "UPDATE app.auth_sessions" in query
    assert "COALESCE(revoked_at, CURRENT_TIMESTAMP)" in query
    assert "WHERE token_hash = %s" in query
    assert parameters == (b"x" * 32,)


def test_missing_session_cookie_is_unauthenticated_without_repository_call(monkeypatch) -> None:
    monkeypatch.setattr(
        routes.repository,
        "resolve_session",
        lambda *_: pytest.fail("missing cookie must not query persistence"),
    )

    response = TestClient(main.app, base_url="https://testserver").get("/api/auth/session")

    assert response.status_code == 401
    assert response.json() == {"authenticated": False}
    assert response.headers["cache-control"] == "no-store, private"
    assert response.headers["vary"] == "Cookie"


@pytest.mark.parametrize("state", ("unknown", "expired", "revoked", "disabled"))
def test_invalid_session_states_are_indistinguishable_and_never_expose_token(
    monkeypatch, state: str
) -> None:
    received: list[bytes] = []
    raw_token = f"raw-{state}-session"

    def unavailable(token_hash: bytes):
        received.append(token_hash)
        return None

    monkeypatch.setattr(routes.repository, "resolve_session", unavailable)
    client = TestClient(main.app, base_url="https://testserver")
    client.cookies.set(config.SESSION_COOKIE_NAME, raw_token)

    response = client.get("/api/auth/session")

    assert response.status_code == 401
    assert response.json() == {"authenticated": False}
    assert received == [config.sha256_token(raw_token)]
    assert raw_token not in response.text


def test_valid_session_returns_only_safe_identity_and_hashes_cookie(monkeypatch) -> None:
    received: list[bytes] = []
    raw_token = "raw-opaque-session"

    def resolved(token_hash: bytes):
        received.append(token_hash)
        return repository.SessionIdentity(user_id=12, email="owner@example.com")

    monkeypatch.setattr(routes.repository, "resolve_session", resolved)
    client = TestClient(main.app, base_url="https://testserver")
    client.cookies.set(config.SESSION_COOKIE_NAME, raw_token)

    response = client.get("/api/auth/session")

    assert response.status_code == 200
    assert response.json() == {
        "authenticated": True,
        "user": {"id": 12, "email": "owner@example.com"},
    }
    assert received == [config.sha256_token(raw_token)]
    serialized = repr((response.json(), received)).lower()
    for private_field in ("provider", "subject", "token_hash", "expires", "revoked"):
        assert private_field not in serialized
    assert response.headers["cache-control"] == "no-store, private"
    assert response.headers["vary"] == "Cookie"


def test_malformed_session_cookie_fails_without_repository_call(monkeypatch) -> None:
    monkeypatch.setattr(
        routes.repository,
        "resolve_session",
        lambda *_: pytest.fail("malformed cookie must not reach persistence"),
    )
    client = TestClient(main.app, base_url="https://testserver")
    client.cookies.set(config.SESSION_COOKIE_NAME, "malformed*cookie")

    response = client.get("/api/auth/session")

    assert response.status_code == 401
    assert response.json() == {"authenticated": False}


def test_logout_revokes_only_presented_session_after_valid_csrf(monkeypatch) -> None:
    revoked: list[bytes] = []
    raw_token = "session-a"
    monkeypatch.setattr(routes.repository, "revoke_session", lambda token_hash: revoked.append(token_hash))
    client = TestClient(main.app, base_url="https://testserver")
    client.cookies.set(CSRF_COOKIE_NAME, "csrf-token")
    client.cookies.set(config.SESSION_COOKIE_NAME, raw_token)

    response = client.post("/auth/logout", data={"csrf_token": "csrf-token"}, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert response.headers["cache-control"] == "no-store, private"
    assert revoked == [config.sha256_token(raw_token)]
    cookie = response.headers["set-cookie"]
    assert "__Host-mb_session=" in cookie and "Max-Age=0" in cookie
    assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert "Path=/" in cookie and "Domain=" not in cookie


@pytest.mark.parametrize("submitted", (None, "wrong-token"))
def test_logout_rejects_missing_or_invalid_csrf_before_revocation(monkeypatch, submitted: str | None) -> None:
    monkeypatch.setattr(
        routes.repository,
        "revoke_session",
        lambda *_: pytest.fail("CSRF failure must precede session mutation"),
    )
    client = TestClient(main.app, base_url="https://testserver")
    client.cookies.set(config.SESSION_COOKIE_NAME, "session-a")
    client.cookies.set(CSRF_COOKIE_NAME, "csrf-token")
    data = {} if submitted is None else {"csrf_token": submitted}

    response = client.post("/auth/logout", data=data, follow_redirects=False)

    assert response.status_code == 403


def test_logout_without_session_is_idempotent_cleanup(monkeypatch) -> None:
    monkeypatch.setattr(
        routes.repository,
        "revoke_session",
        lambda *_: pytest.fail("missing session must not invoke revocation"),
    )
    client = TestClient(main.app, base_url="https://testserver")
    client.cookies.set(CSRF_COOKIE_NAME, "csrf-token")

    response = client.post("/auth/logout", data={"csrf_token": "csrf-token"}, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert "__Host-mb_session=" in response.headers["set-cookie"]


@pytest.mark.parametrize("raw_token", ("unknown-session", "already-revoked-session"))
def test_logout_with_unknown_or_revoked_session_remains_idempotent(
    monkeypatch, raw_token: str
) -> None:
    revoked: list[bytes] = []
    monkeypatch.setattr(routes.repository, "revoke_session", lambda token_hash: revoked.append(token_hash))
    client = TestClient(main.app, base_url="https://testserver")
    client.cookies.set(CSRF_COOKIE_NAME, "csrf-token")
    client.cookies.set(config.SESSION_COOKIE_NAME, raw_token)

    response = client.post("/auth/logout", data={"csrf_token": "csrf-token"}, follow_redirects=False)

    assert response.status_code == 303
    assert revoked == [config.sha256_token(raw_token)]
    assert "__Host-mb_session=" in response.headers["set-cookie"]


def test_concurrent_sessions_remain_independent_after_logout(monkeypatch) -> None:
    active = {
        config.sha256_token("session-a"): repository.SessionIdentity(7, "owner@example.com"),
        config.sha256_token("session-b"): repository.SessionIdentity(7, "owner@example.com"),
    }

    monkeypatch.setattr(routes.repository, "resolve_session", lambda token_hash: active.get(token_hash))
    monkeypatch.setattr(routes.repository, "revoke_session", lambda token_hash: active.pop(token_hash, None))
    client_a = TestClient(main.app, base_url="https://testserver")
    client_b = TestClient(main.app, base_url="https://testserver")
    client_a.cookies.set(config.SESSION_COOKIE_NAME, "session-a")
    client_a.cookies.set(CSRF_COOKIE_NAME, "csrf-token")
    client_b.cookies.set(config.SESSION_COOKIE_NAME, "session-b")

    assert client_a.get("/api/auth/session").status_code == 200
    assert client_b.get("/api/auth/session").status_code == 200
    assert client_a.post("/auth/logout", data={"csrf_token": "csrf-token"}, follow_redirects=False).status_code == 303
    assert client_a.get("/api/auth/session").status_code == 401
    assert client_b.get("/api/auth/session").status_code == 200
