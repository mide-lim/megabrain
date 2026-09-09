from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from app import main
from app.auth import config, routes
from app.auth.oidc import ValidatedIdentity
from app.auth.repository import ConsumedAuthTransaction, OwnerAuthorizationError


@dataclass
class FakeAdapter:
    exchanges: list[tuple[str, str]]

    def authorization_url(self, *, state: str, nonce: str, pkce_verifier: str) -> str:
        assert state and nonce and pkce_verifier
        return "https://accounts.google.com/authorize?state=fake"

    def exchange_and_validate(self, *, code: str, pkce_verifier: str, expected_nonce: str) -> ValidatedIdentity:
        self.exchanges.append((code, pkce_verifier))
        return ValidatedIdentity(
            "https://accounts.google.com", "google-subject", "owner@example.com", True
        )


@pytest.fixture
def configured_auth(monkeypatch):
    settings = config.AuthSettings(
        client_id="client-id",
        client_secret="client-secret",
        owner_email="owner@example.com",
        public_base_url="https://testserver",
        session_ttl_seconds=604800,
    )
    adapter = FakeAdapter([])
    monkeypatch.setattr(routes, "load_auth_settings", lambda: settings)
    monkeypatch.setattr(routes, "build_oidc_adapter", lambda _: adapter)
    return adapter


def test_login_creates_server_transaction_and_sets_only_opaque_cookie(
    monkeypatch, configured_auth
) -> None:
    created: list[dict[str, object]] = []
    monkeypatch.setattr(routes.repository, "create_auth_transaction", lambda **kwargs: created.append(kwargs))

    response = TestClient(main.app, base_url="https://testserver").get(
        "/auth/login?return_to=/library", follow_redirects=False
    )

    assert response.status_code == 303
    assert response.headers["location"].startswith("https://accounts.google.com/")
    assert response.headers["cache-control"] == "no-store, private"
    cookie = response.headers["set-cookie"]
    assert "__Host-mb_oidc=" in cookie
    assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert "Path=/" in cookie and "Domain=" not in cookie and "Max-Age=600" in cookie
    assert len(created) == 1
    assert len(created[0]["transaction_hash"]) == 32
    assert len(created[0]["state_hash"]) == 32
    assert created[0]["return_path"] == "/library"
    assert "access_token" not in repr(created[0]).lower()


def test_login_rejects_invalid_return_path_without_cookie(monkeypatch, configured_auth) -> None:
    monkeypatch.setattr(routes.repository, "create_auth_transaction", lambda **kwargs: pytest.fail("no transaction"))

    response = TestClient(main.app, base_url="https://testserver").get(
        "/auth/login?return_to=https://evil.example", follow_redirects=False
    )

    assert response.status_code == 400
    assert "set-cookie" not in response.headers
    assert response.headers["cache-control"] == "no-store, private"


def test_callback_success_consumes_before_exchange_and_sets_local_session(
    monkeypatch, configured_auth
) -> None:
    events: list[str] = []
    consumed = ConsumedAuthTransaction("nonce", "verifier", "/library")
    monkeypatch.setattr(
        routes.repository,
        "consume_auth_transaction",
        lambda *_: events.append("consume") or consumed,
    )
    monkeypatch.setattr(
        routes.repository,
        "resolve_or_bootstrap_owner",
        lambda *_: events.append("owner") or 7,
    )
    monkeypatch.setattr(
        routes.repository,
        "create_session",
        lambda **kwargs: events.append("session"),
    )
    adapter = configured_auth
    original_exchange = adapter.exchange_and_validate
    adapter.exchange_and_validate = lambda **kwargs: (events.append("exchange") or original_exchange(**kwargs))
    client = TestClient(main.app, base_url="https://testserver")
    client.cookies.set(config.OIDC_TRANSACTION_COOKIE_NAME, "raw-transaction")

    response = client.get("/auth/callback?code=secret-code&state=raw-state", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/library"
    assert events == ["consume", "exchange", "owner", "session"]
    assert response.headers["cache-control"] == "no-store, private"
    assert response.headers["referrer-policy"] == "no-referrer"
    cookies = response.headers.get_list("set-cookie")
    assert any("__Host-mb_oidc=" in cookie and "Max-Age=0" in cookie for cookie in cookies)
    assert any("__Host-mb_session=" in cookie and "Max-Age=604800" in cookie for cookie in cookies)
    assert "secret-code" not in response.text


def test_replayed_transaction_fails_without_provider_exchange(monkeypatch, configured_auth) -> None:
    monkeypatch.setattr(routes.repository, "consume_auth_transaction", lambda *_: None)
    client = TestClient(main.app, base_url="https://testserver")
    client.cookies.set(config.OIDC_TRANSACTION_COOKIE_NAME, "raw-transaction")

    response = client.get("/auth/callback?code=secret-code&state=raw-state", follow_redirects=False)

    assert response.status_code == 400
    assert configured_auth.exchanges == []
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "secret-code" not in response.text and "raw-state" not in response.text


def test_provider_error_consumes_transaction_but_never_exchanges(monkeypatch, configured_auth) -> None:
    monkeypatch.setattr(
        routes.repository,
        "consume_auth_transaction",
        lambda *_: ConsumedAuthTransaction("nonce", "verifier", "/"),
    )
    client = TestClient(main.app, base_url="https://testserver")
    client.cookies.set(config.OIDC_TRANSACTION_COOKIE_NAME, "raw-transaction")

    response = client.get(
        "/auth/callback?error=access_denied&error_description=secret-detail&state=raw-state",
        follow_redirects=False,
    )

    assert response.status_code == 401
    assert configured_auth.exchanges == []
    assert "secret-detail" not in response.text and "access_denied" not in response.text
    assert "Max-Age=0" in response.headers["set-cookie"]


@pytest.mark.parametrize(
    "query",
    ("", "?code=only", "?error=only", "?code=x&error=y&state=state"),
)
def test_callback_rejects_malformed_shapes_without_consuming(monkeypatch, configured_auth, query) -> None:
    monkeypatch.setattr(routes.repository, "consume_auth_transaction", lambda *_: pytest.fail("no consume"))

    response = TestClient(main.app, base_url="https://testserver").get(
        f"/auth/callback{query}", follow_redirects=False
    )

    assert response.status_code == 400
    assert response.headers["cache-control"] == "no-store, private"
    assert response.headers["referrer-policy"] == "no-referrer"


def test_callback_owner_rejection_is_forbidden(monkeypatch, configured_auth) -> None:
    monkeypatch.setattr(
        routes.repository,
        "consume_auth_transaction",
        lambda *_: ConsumedAuthTransaction("nonce", "verifier", "/"),
    )
    monkeypatch.setattr(
        routes.repository,
        "resolve_or_bootstrap_owner",
        lambda *_: (_ for _ in ()).throw(OwnerAuthorizationError("denied")),
    )
    client = TestClient(main.app, base_url="https://testserver")
    client.cookies.set(config.OIDC_TRANSACTION_COOKIE_NAME, "raw-transaction")

    assert client.get("/auth/callback?code=code&state=state", follow_redirects=False).status_code == 403
