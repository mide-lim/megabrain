from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import main
from app.auth import config, dependencies, repository


CSRF_TOKEN = "valid-api-csrf-token"


def owner_client(monkeypatch) -> TestClient:
    monkeypatch.setattr(
        dependencies.repository,
        "resolve_session",
        lambda *_: repository.SessionIdentity(7, "owner@example.com"),
    )
    client = TestClient(main.app, base_url="https://testserver")
    client.cookies.set(config.SESSION_COOKIE_NAME, "valid-owner-session")
    return client


def csrf_headers(token: str = CSRF_TOKEN) -> dict[str, str]:
    return {"X-CSRF-Token": token}


def set_csrf_cookie(client: TestClient, token: str = CSRF_TOKEN) -> None:
    client.cookies.set(main.CSRF_COOKIE_NAME, token)


def test_csrf_bootstrap_rejects_missing_owner_session() -> None:
    response = TestClient(main.app, base_url="https://testserver").get("/api/auth/csrf")

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}
    assert "set-cookie" not in response.headers


def test_csrf_bootstrap_returns_and_sets_secure_httponly_cookie_for_owner(monkeypatch) -> None:
    client = owner_client(monkeypatch)

    response = client.get("/api/auth/csrf")

    assert response.status_code == 200
    token = response.json()["csrf_token"]
    assert token and token == client.cookies.get(main.CSRF_COOKIE_NAME)
    assert response.headers["cache-control"] == "no-store, private"
    assert response.headers["vary"] == "Cookie"
    cookie = response.headers["set-cookie"]
    assert "__Host-csrf_token=" in cookie
    assert "Secure" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Path=/" in cookie
    assert "Domain=" not in cookie


def test_csrf_bootstrap_reuses_existing_owner_cookie_without_reset(monkeypatch) -> None:
    client = owner_client(monkeypatch)
    set_csrf_cookie(client, "existing-token")

    response = client.get("/api/auth/csrf")

    assert response.status_code == 200
    assert response.json() == {"csrf_token": "existing-token"}
    assert "set-cookie" not in response.headers
    assert response.headers["cache-control"] == "no-store, private"
    assert response.headers["vary"] == "Cookie"


@pytest.mark.parametrize(
    ("path", "method", "payload", "mutation_name"),
    [
        ("/api/reels/42/categories", "post", {"category_id": 7}, "associate_category"),
        ("/api/reels/42/categories/new", "post", {"name": "Tech"}, "create_and_associate_category"),
        ("/api/reels/42/categories/7", "delete", None, "remove_category"),
    ],
)
def test_api_mutations_reject_missing_owner_before_domain_access(
    monkeypatch, path: str, method: str, payload: dict[str, object] | None, mutation_name: str
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(main, "reel_exists", lambda *_: calls.append("reel_exists"))
    monkeypatch.setattr(main, "category_exists", lambda *_: calls.append("category_exists"))
    monkeypatch.setattr(main, mutation_name, lambda *_: calls.append(mutation_name))

    client = TestClient(main.app, base_url="https://testserver")
    set_csrf_cookie(client)
    response = (
        getattr(client, method)(path, json=payload, headers=csrf_headers())
        if payload is not None
        else getattr(client, method)(path, headers=csrf_headers())
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}
    assert calls == []


@pytest.mark.parametrize(
    ("header_token",),
    [(None,), ("invalid-api-csrf-token",)],
)
def test_assign_api_rejects_missing_or_invalid_csrf_before_domain_access(monkeypatch, header_token: str | None) -> None:
    calls: list[str] = []
    client = owner_client(monkeypatch)
    set_csrf_cookie(client)
    monkeypatch.setattr(main, "reel_exists", lambda *_: calls.append("reel_exists"))
    monkeypatch.setattr(main, "category_exists", lambda *_: calls.append("category_exists"))
    monkeypatch.setattr(main, "associate_category", lambda *_: calls.append("associate_category"))

    response = client.post(
        "/api/reels/42/categories",
        json={"category_id": 7},
        headers=csrf_headers(header_token) if header_token else {},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "CSRF token validation failed"}
    assert calls == []


def test_assign_api_calls_association_once_after_owner_and_csrf(monkeypatch) -> None:
    calls: list[tuple[int, int]] = []
    client = owner_client(monkeypatch)
    set_csrf_cookie(client)
    monkeypatch.setattr(main, "reel_exists", lambda reel_id: reel_id == 42)
    monkeypatch.setattr(main, "category_exists", lambda category_id: category_id == 7)
    monkeypatch.setattr(main, "associate_category", lambda reel_id, category_id: calls.append((reel_id, category_id)))

    response = client.post(
        "/api/reels/42/categories", json={"category_id": 7}, headers=csrf_headers()
    )

    assert response.status_code == 204
    assert response.content == b""
    assert calls == [(42, 7)]


def test_assign_api_returns_404_for_missing_reel_before_category_or_mutation(monkeypatch) -> None:
    calls: list[str] = []
    client = owner_client(monkeypatch)
    set_csrf_cookie(client)
    monkeypatch.setattr(main, "reel_exists", lambda *_: False)
    monkeypatch.setattr(main, "category_exists", lambda *_: calls.append("category_exists"))
    monkeypatch.setattr(main, "associate_category", lambda *_: calls.append("associate_category"))

    response = client.post(
        "/api/reels/999/categories", json={"category_id": 7}, headers=csrf_headers()
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Reel not found"}
    assert calls == []


def test_assign_api_returns_404_for_missing_category_without_mutation(monkeypatch) -> None:
    calls: list[str] = []
    client = owner_client(monkeypatch)
    set_csrf_cookie(client)
    monkeypatch.setattr(main, "reel_exists", lambda *_: True)
    monkeypatch.setattr(main, "category_exists", lambda *_: False)
    monkeypatch.setattr(main, "associate_category", lambda *_: calls.append("associate_category"))

    response = client.post(
        "/api/reels/42/categories", json={"category_id": 999}, headers=csrf_headers()
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Category not found"}
    assert calls == []


def test_assign_api_is_idempotent_for_duplicate_association(monkeypatch) -> None:
    calls: list[tuple[int, int]] = []
    client = owner_client(monkeypatch)
    set_csrf_cookie(client)
    monkeypatch.setattr(main, "reel_exists", lambda *_: True)
    monkeypatch.setattr(main, "category_exists", lambda *_: True)
    monkeypatch.setattr(main, "associate_category", lambda reel_id, category_id: calls.append((reel_id, category_id)))

    responses = [
        client.post("/api/reels/42/categories", json={"category_id": 7}, headers=csrf_headers())
        for _ in range(2)
    ]

    assert [response.status_code for response in responses] == [204, 204]
    assert calls == [(42, 7), (42, 7)]


@pytest.mark.parametrize("header_token", (None, "invalid-api-csrf-token"))
def test_create_category_api_requires_csrf_before_mutation(monkeypatch, header_token: str | None) -> None:
    calls: list[str] = []
    client = owner_client(monkeypatch)
    set_csrf_cookie(client)
    monkeypatch.setattr(main, "reel_exists", lambda *_: calls.append("reel_exists"))
    monkeypatch.setattr(main, "create_and_associate_category", lambda *_: calls.append("create"))

    response = client.post(
        "/api/reels/42/categories/new",
        json={"name": "Tech"},
        headers=csrf_headers(header_token) if header_token else {},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "CSRF token validation failed"}
    assert calls == []


def test_create_category_api_normalizes_and_reuses_existing_category_behavior(monkeypatch) -> None:
    calls: list[tuple[int, str]] = []
    client = owner_client(monkeypatch)
    set_csrf_cookie(client)
    monkeypatch.setattr(main, "reel_exists", lambda *_: True)
    monkeypatch.setattr(
        main,
        "create_and_associate_category",
        lambda reel_id, name: calls.append((reel_id, name)),
    )

    response = client.post(
        "/api/reels/42/categories/new", json={"name": "  tEcH  "}, headers=csrf_headers()
    )

    assert response.status_code == 204
    assert calls == [(42, "tEcH")]


def test_create_category_api_returns_404_for_missing_reel_before_mutation(monkeypatch) -> None:
    client = owner_client(monkeypatch)
    set_csrf_cookie(client)
    monkeypatch.setattr(main, "reel_exists", lambda *_: False)
    monkeypatch.setattr(
        main,
        "create_and_associate_category",
        lambda *_: pytest.fail("missing reels must not create categories"),
    )

    response = client.post(
        "/api/reels/999/categories/new", json={"name": "Tech"}, headers=csrf_headers()
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Reel not found"}


def test_create_category_api_rejects_whitespace_name_without_domain_access(monkeypatch) -> None:
    client = owner_client(monkeypatch)
    set_csrf_cookie(client)
    monkeypatch.setattr(main, "reel_exists", lambda *_: pytest.fail("empty names must not query reels"))
    monkeypatch.setattr(
        main,
        "create_and_associate_category",
        lambda *_: pytest.fail("empty names must not mutate"),
    )

    response = client.post(
        "/api/reels/42/categories/new", json={"name": "   "}, headers=csrf_headers()
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Category name must not be empty"}


def test_remove_category_api_returns_404_for_missing_reel_before_mutation(monkeypatch) -> None:
    client = owner_client(monkeypatch)
    set_csrf_cookie(client)
    monkeypatch.setattr(main, "reel_exists", lambda *_: False)
    monkeypatch.setattr(
        main,
        "remove_category",
        lambda *_: pytest.fail("missing reels must not reach removal"),
    )

    response = client.delete("/api/reels/999/categories/7", headers=csrf_headers())

    assert response.status_code == 404
    assert response.json() == {"detail": "Reel not found"}


def test_remove_category_api_requires_csrf_then_allows_idempotent_removal(monkeypatch) -> None:
    calls: list[tuple[int, int]] = []
    client = owner_client(monkeypatch)
    set_csrf_cookie(client)
    monkeypatch.setattr(main, "reel_exists", lambda *_: True)
    monkeypatch.setattr(main, "remove_category", lambda reel_id, category_id: calls.append((reel_id, category_id)))

    missing_csrf = client.delete("/api/reels/42/categories/7")
    invalid_csrf = client.delete(
        "/api/reels/42/categories/7", headers=csrf_headers("invalid-api-csrf-token")
    )
    first = client.delete("/api/reels/42/categories/7", headers=csrf_headers())
    second = client.delete("/api/reels/42/categories/7", headers=csrf_headers())

    assert missing_csrf.status_code == 403
    assert invalid_csrf.status_code == 403
    assert first.status_code == 204
    assert second.status_code == 204
    assert calls == [(42, 7), (42, 7)]


def test_api_mutation_does_not_accept_csrf_token_from_query(monkeypatch) -> None:
    client = owner_client(monkeypatch)
    set_csrf_cookie(client)
    monkeypatch.setattr(main, "reel_exists", lambda *_: pytest.fail("query token must not reach domain"))

    response = client.post(
        "/api/reels/42/categories?csrf_token=valid-api-csrf-token", json={"category_id": 7}
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "CSRF token validation failed"}


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/reels/42/categories", {}),
        ("/api/reels/42/categories/new", {}),
    ],
)
def test_api_typed_bodies_reject_missing_fields_before_domain_access(monkeypatch, path: str, payload: dict) -> None:
    client = owner_client(monkeypatch)
    set_csrf_cookie(client)
    monkeypatch.setattr(main, "reel_exists", lambda *_: pytest.fail("invalid bodies must not query reels"))
    monkeypatch.setattr(main, "category_exists", lambda *_: pytest.fail("invalid bodies must not query categories"))

    response = client.post(path, json=payload, headers=csrf_headers())

    assert response.status_code == 422


def test_mutation_api_openapi_uses_typed_request_models() -> None:
    schema = TestClient(main.app).get("/openapi.json").json()

    csrf = schema["paths"]["/api/auth/csrf"]["get"]
    assign = schema["paths"]["/api/reels/{reel_id}/categories"]["post"]
    create = schema["paths"]["/api/reels/{reel_id}/categories/new"]["post"]
    remove = schema["paths"]["/api/reels/{reel_id}/categories/{category_id}"]["delete"]
    assert csrf["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/CsrfTokenResponse"
    }
    assert assign["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/AssignCategoryRequest"
    }
    assert create["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/CreateCategoryRequest"
    }
    assert "requestBody" not in remove
    for operation in (assign, create, remove):
        assert any(
            parameter["in"] == "header" and parameter["name"] == "X-CSRF-Token"
            for parameter in operation["parameters"]
        )
