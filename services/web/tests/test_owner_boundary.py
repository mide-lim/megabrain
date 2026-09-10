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


def test_legacy_root_rejects_missing_owner_before_library_query(monkeypatch) -> None:
    monkeypatch.setattr(
        main,
        "fetch_reels",
        lambda *_: pytest.fail("unauthenticated request must not query reels"),
    )

    response = TestClient(main.app).get("/")

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}


def test_legacy_detail_rejects_missing_owner_before_fetch_or_presign(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(main, "fetch_reel", lambda *_: calls.append("fetch_reel"))
    monkeypatch.setattr(
        main,
        "fetch_categories_for_reel",
        lambda *_: calls.append("fetch_categories_for_reel"),
    )
    monkeypatch.setattr(
        main,
        "presigned_video_url",
        lambda *_: calls.append("presigned_video_url"),
    )

    response = TestClient(main.app).get("/reels/42")

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}
    assert calls == []


@pytest.mark.parametrize(
    ("path", "data", "mutation_name"),
    [
        ("/reels/42/categories", {"category_id": "7"}, "associate_category"),
        ("/reels/42/categories/new", {"name": "Tech"}, "create_and_associate_category"),
        ("/reels/42/categories/7/remove", {}, "remove_category"),
    ],
)
def test_legacy_category_mutations_reject_missing_owner_before_mutation(
    monkeypatch, path: str, data: dict[str, str], mutation_name: str
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(main, "reel_exists", lambda *_: calls.append("reel_exists"))
    monkeypatch.setattr(
        main,
        mutation_name,
        lambda *_: calls.append(mutation_name),
    )
    client = TestClient(main.app, base_url="https://testserver")
    client.cookies.set(main.CSRF_COOKIE_NAME, "valid-token")

    response = client.post(
        path,
        data={"csrf_token": "valid-token", **data},
        follow_redirects=False,
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}
    assert calls == []


def test_legacy_category_mutation_requires_valid_owner_session_and_csrf(monkeypatch) -> None:
    calls: list[tuple[int, int]] = []
    monkeypatch.setattr(
        dependencies.repository,
        "resolve_session",
        lambda *_: repository.SessionIdentity(7, "owner@example.com"),
    )
    monkeypatch.setattr(main, "reel_exists", lambda *_: True)
    monkeypatch.setattr(
        main,
        "associate_category",
        lambda reel_id, category_id: calls.append((reel_id, category_id)),
    )
    client = TestClient(main.app, base_url="https://testserver")
    client.cookies.set(config.SESSION_COOKIE_NAME, "valid-owner-session")
    client.cookies.set(main.CSRF_COOKIE_NAME, "valid-token")

    response = client.post(
        "/reels/42/categories",
        data={"category_id": "7", "csrf_token": "valid-token"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert calls == [(42, 7)]


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
