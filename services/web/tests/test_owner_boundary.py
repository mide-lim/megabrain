from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app import main
from app.auth import config, dependencies, repository, routes


def _library_row() -> dict[str, object]:
    return {
        "id": 42,
        "title": "Owner Reel",
        "creator": "maker",
        "shortcode": "abc123",
        "caption": "caption",
        "categories": [],
        "duration_seconds": 12.5,
        "received_at": datetime(2026, 8, 25, tzinfo=UTC),
        "has_transcript": True,
    }


def test_reels_api_rejects_missing_owner_session(monkeypatch) -> None:
    monkeypatch.setattr(main, "fetch_reels", lambda *_: pytest.fail("unauthenticated request must not query reels"))

    response = TestClient(main.app).get("/api/reels")

    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"detail": "Authentication required"}


@pytest.mark.parametrize("session_state", ("invalid", "expired", "revoked"))
def test_reels_api_rejects_invalid_expired_and_revoked_sessions(monkeypatch, session_state: str) -> None:
    monkeypatch.setattr(dependencies.repository, "resolve_session", lambda *_: None)
    monkeypatch.setattr(main, "fetch_reels", lambda *_: pytest.fail("invalid session must not query reels"))
    client = TestClient(main.app, base_url="https://testserver")
    client.cookies.set(config.SESSION_COOKIE_NAME, f"{session_state}-owner-session")

    response = client.get("/api/reels")

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}


def test_reels_api_allows_valid_owner_and_keeps_existing_payload(monkeypatch) -> None:
    monkeypatch.setattr(
        dependencies.repository,
        "resolve_session",
        lambda *_: repository.SessionIdentity(7, "owner@example.com"),
    )
    monkeypatch.setattr(main, "fetch_reels", lambda *_: ([_library_row()], False))
    client = TestClient(main.app, base_url="https://testserver")
    client.cookies.set(config.SESSION_COOKIE_NAME, "valid-owner-session")

    response = client.get("/api/reels")

    assert response.status_code == 200
    assert response.json()["items"] == [
        {
            "id": 42,
            "title": "Owner Reel",
            "creator": "maker",
            "shortcode": "abc123",
            "caption": "caption",
            "categories": [],
            "duration_seconds": 12.5,
            "received_at": "2026-08-25T00:00:00Z",
            "has_transcript": True,
        }
    ]


def test_session_bootstrap_contract_remains_distinct_from_protected_api(monkeypatch) -> None:
    client = TestClient(main.app, base_url="https://testserver")
    assert client.get("/api/auth/session").status_code == 401
    assert client.get("/api/auth/session").json() == {"authenticated": False}

    monkeypatch.setattr(
        dependencies.repository,
        "resolve_session",
        lambda *_: repository.SessionIdentity(7, "owner@example.com"),
    )
    client.cookies.set(config.SESSION_COOKIE_NAME, "valid-owner-session")
    response = client.get("/api/auth/session")
    assert response.status_code == 200
    assert response.json() == {"authenticated": True, "user": {"id": 7, "email": "owner@example.com"}}


def test_health_and_auth_routes_remain_public() -> None:
    client = TestClient(main.app)

    assert client.get("/health").status_code == 200
    assert client.get("/auth/login", follow_redirects=False).status_code != 401
    assert client.get("/auth/callback", follow_redirects=False).status_code == 400
    assert client.get("/api/auth/session").status_code == 401


def test_owner_dependency_reuses_hashed_opaque_token_without_exposure(monkeypatch) -> None:
    received: list[bytes] = []
    raw_token = "opaque-owner-session"
    monkeypatch.setattr(
        dependencies.repository,
        "resolve_session",
        lambda token_hash: received.append(token_hash) or repository.SessionIdentity(7, "owner@example.com"),
    )
    client = TestClient(main.app, base_url="https://testserver")
    client.cookies.set(config.SESSION_COOKIE_NAME, raw_token)

    response = client.get("/api/auth/session")

    assert response.status_code == 200
    assert received == [config.sha256_token(raw_token)]
    assert raw_token not in response.text
    assert raw_token not in repr(response.json())
