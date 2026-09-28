from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import categories, main
from app.auth import config, dependencies, repository
from app.csrf import CSRF_COOKIE_NAME

CSRF_TOKEN = "valid-category-csrf-token"


def owner_client(monkeypatch) -> TestClient:
    monkeypatch.setattr(
        dependencies.repository,
        "resolve_session",
        lambda *_: repository.SessionIdentity(7, "owner@example.com"),
    )
    client = TestClient(main.app, base_url="https://testserver")
    client.cookies.set(config.SESSION_COOKIE_NAME, "valid-owner-session")
    client.cookies.set(CSRF_COOKIE_NAME, CSRF_TOKEN)
    return client


def csrf_headers() -> dict[str, str]:
    return {"X-CSRF-Token": CSRF_TOKEN}


def reel_row(reel_id: int) -> dict[str, object]:
    return {
        "id": reel_id,
        "title": "Reel",
        "creator": "maker",
        "shortcode": "abc",
        "caption": "caption",
        "categories": ["IoT"],
        "duration_seconds": 12.5,
        "received_at": None,
        "has_transcript": True,
        "download_status": "downloaded",
        "curation_status": "organized",
        "transcription_status": "completed",
    }


def test_category_list_is_owner_only_and_preserves_repository_order(monkeypatch) -> None:
    client = owner_client(monkeypatch)
    monkeypatch.setattr(
        main,
        "fetch_categories",
        lambda: [
            {"id": 2, "name": "Arduino", "reel_count": 0},
            {"id": 1, "name": "IoT", "reel_count": 9},
        ],
    )

    response = client.get("/api/categories")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "items": [
            {"id": 2, "name": "Arduino", "reel_count": 0},
            {"id": 1, "name": "IoT", "reel_count": 9},
        ]
    }


def test_category_detail_uses_exact_id_and_library_projection(monkeypatch) -> None:
    client = owner_client(monkeypatch)
    calls: list[tuple[int, int, int]] = []
    monkeypatch.setattr(
        main,
        "fetch_category",
        lambda category_id: {"id": category_id, "name": "IoT", "reel_count": 13},
    )
    monkeypatch.setattr(
        main,
        "fetch_category_reels",
        lambda category_id, page, page_size: calls.append((category_id, page, page_size))
        or ([reel_row(42)], True),
    )

    response = client.get("/api/categories/7?page=2")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["category"] == {"id": 7, "name": "IoT", "reel_count": 13}
    assert response.json()["items"][0]["id"] == 42
    assert response.json()["pagination"] == {
        "page": 2,
        "page_size": main.PAGE_SIZE,
        "has_previous": True,
        "has_next": True,
    }
    assert calls == [(7, 2, main.PAGE_SIZE)]


def test_unknown_category_detail_returns_404_before_reel_query(monkeypatch) -> None:
    client = owner_client(monkeypatch)
    monkeypatch.setattr(main, "fetch_category", lambda *_: None)
    monkeypatch.setattr(
        main,
        "fetch_category_reels",
        lambda *_: pytest.fail("missing category must not fetch reels"),
    )

    response = client.get("/api/categories/999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Category not found"}


def test_create_category_returns_201_and_normalizes_name(monkeypatch) -> None:
    client = owner_client(monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(
        main,
        "create_category",
        lambda name: calls.append(name) or {"id": 4, "name": name},
    )

    response = client.post(
        "/api/categories",
        json={"name": "  Hardware  "},
        headers=csrf_headers(),
    )

    assert response.status_code == 201
    assert response.json() == {"category": {"id": 4, "name": "Hardware"}}
    assert calls == ["Hardware"]


def test_create_and_rename_surface_case_insensitive_conflict(monkeypatch) -> None:
    client = owner_client(monkeypatch)

    def conflict(*_args):
        raise categories.CategoryNameConflict("IoT")

    monkeypatch.setattr(main, "create_category", conflict)
    created = client.post(
        "/api/categories",
        json={"name": "IoT"},
        headers=csrf_headers(),
    )
    assert created.status_code == 409

    monkeypatch.setattr(main, "rename_category", conflict)
    renamed = client.patch(
        "/api/categories/4",
        json={"name": "IoT"},
        headers=csrf_headers(),
    )
    assert renamed.status_code == 409


def test_rename_and_delete_do_not_receive_lifecycle_fields(monkeypatch) -> None:
    client = owner_client(monkeypatch)
    monkeypatch.setattr(
        main,
        "rename_category",
        lambda category_id, name: {"id": category_id, "name": name},
    )
    monkeypatch.setattr(
        main,
        "delete_category",
        lambda category_id: {"id": category_id, "name": "IoT"},
    )

    renamed = client.patch(
        "/api/categories/4",
        json={"name": "Internet das Coisas"},
        headers=csrf_headers(),
    )
    assert renamed.status_code == 200
    assert renamed.json()["category"]["name"] == "Internet das Coisas"

    deleted = client.delete("/api/categories/4", headers=csrf_headers())
    assert deleted.status_code == 204


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("post", "/api/categories", {}),
        ("post", "/api/categories", {"name": "IoT", "curation_status": "organized"}),
        ("patch", "/api/categories/4", {"name": "IoT", "download_status": "failed"}),
        ("patch", "/api/categories/4", {"name": "IoT", "transcription_status": "completed"}),
    ],
)
def test_category_mutations_reject_invalid_or_authority_smuggling_payloads(
    monkeypatch,
    method: str,
    path: str,
    payload: dict[str, object],
) -> None:
    client = owner_client(monkeypatch)
    monkeypatch.setattr(
        main,
        "create_category",
        lambda *_: pytest.fail("invalid request must not mutate"),
    )
    monkeypatch.setattr(
        main,
        "rename_category",
        lambda *_: pytest.fail("invalid request must not mutate"),
    )

    response = getattr(client, method)(path, json=payload, headers=csrf_headers())
    assert response.status_code == 422


def test_category_mutations_require_owner_and_csrf(monkeypatch) -> None:
    client = TestClient(main.app, base_url="https://testserver")
    client.cookies.set(CSRF_COOKIE_NAME, CSRF_TOKEN)
    anonymous = client.post(
        "/api/categories",
        json={"name": "IoT"},
        headers=csrf_headers(),
    )
    assert anonymous.status_code == 401

    owner = owner_client(monkeypatch)
    monkeypatch.setattr(
        main,
        "create_category",
        lambda *_: pytest.fail("missing CSRF must not mutate"),
    )
    missing_csrf = owner.post("/api/categories", json={"name": "IoT"})
    assert missing_csrf.status_code == 403


def test_category_repository_queries_cover_zero_counts_exact_membership_and_pagination(monkeypatch) -> None:
    assert "LEFT JOIN app.reel_categories" in categories.CATEGORIES_QUERY
    assert "ORDER BY lower(c.name), c.id" in categories.CATEGORIES_QUERY
    assert "filter_rc.category_id = %s" in categories.CATEGORY_REELS_QUERY
    assert "LIMIT %s OFFSET %s" in categories.CATEGORY_REELS_QUERY
    assert "curation_status" not in categories.ASSOCIATE_CATEGORY_QUERY
    assert "curation_status" not in categories.REMOVE_CATEGORY_QUERY

    calls: list[tuple[str, tuple[int, int, int]]] = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execute(self, query, parameters):
            calls.append((query, parameters))

        def fetchall(self):
            return [reel_row(reel_id) for reel_id in range(13)]

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def cursor(self, *, row_factory):
            return FakeCursor()

    monkeypatch.setattr(categories.database, "connect", lambda: FakeConnection())

    rows, has_next = categories.fetch_category_reels(7, page=2, page_size=12)

    assert len(rows) == 12
    assert has_next is True
    assert calls == [(categories.CATEGORY_REELS_QUERY, (7, 13, 12))]


def test_f5_category_grant_delta_is_narrow() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    grant_sql = (
        repo_root / "infra/postgres/security/f5/001_f5_categories_grants.sql"
    ).read_text(encoding="utf-8")

    assert "GRANT UPDATE (name) ON TABLE app.categories TO megabrain_web;" in grant_sql
    assert "GRANT DELETE ON TABLE app.categories TO megabrain_web;" in grant_sql
    assert "GRANT UPDATE ON TABLE app.categories" not in grant_sql
    assert "TRUNCATE" not in grant_sql
    assert "CREATE ON SCHEMA" not in grant_sql
