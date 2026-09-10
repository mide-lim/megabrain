from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app import main
from app.auth.dependencies import require_owner_session
from app.auth.repository import SessionIdentity


@pytest.fixture(autouse=True)
def authenticated_owner_api() -> None:
    main.app.dependency_overrides[require_owner_session] = lambda: SessionIdentity(7, "owner@example.com")
    yield
    main.app.dependency_overrides.clear()


def library_row(**overrides):
    row = {
        "id": 42,
        "title": "Build a useful thing",
        "creator": "maker",
        "shortcode": "abc123",
        "caption": "A public caption",
        "categories": ["Hands-on", "Tech"],
        "duration_seconds": 12.5,
        "received_at": datetime(2026, 8, 25, tzinfo=UTC),
        "has_transcript": True,
        "status": "downloaded",
        "object_key": "original/instagram/reels/abc123/video.mp4",
        "storage_bucket": "private-reels",
        "transcript_text": "Private transcript text",
        "file_size_bytes": 2048,
    }
    row.update(overrides)
    return row


def test_reels_api_defaults_to_first_page_and_projects_public_fields(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        main,
        "fetch_reels",
        lambda page, q: (calls.append((page, q)) or ([library_row()], True)),
    )

    response = TestClient(main.app).get("/api/reels")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert calls == [(1, None)]
    assert response.json() == {
        "items": [
            {
                "id": 42,
                "title": "Build a useful thing",
                "creator": "maker",
                "shortcode": "abc123",
                "caption": "A public caption",
                "categories": ["Hands-on", "Tech"],
                "duration_seconds": 12.5,
                "received_at": "2026-08-25T00:00:00Z",
                "has_transcript": True,
            }
        ],
        "query": {"q": ""},
        "pagination": {
            "page": 1,
            "page_size": 12,
            "has_previous": False,
            "has_next": True,
        },
    }


def test_reels_api_trims_query_and_reports_explicit_page(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        main,
        "fetch_reels",
        lambda page, q: (calls.append((page, q)) or ([library_row()], False)),
    )

    response = TestClient(main.app).get("/api/reels?page=2&q=%20%20maker%20%20")

    assert response.status_code == 200
    assert calls == [(2, "maker")]
    assert response.json()["query"] == {"q": "maker"}
    assert response.json()["pagination"] == {
        "page": 2,
        "page_size": 12,
        "has_previous": True,
        "has_next": False,
    }


def test_reels_api_normalizes_blank_query_to_unfiltered(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        main,
        "fetch_reels",
        lambda page, q: (calls.append((page, q)) or ([], False)),
    )

    response = TestClient(main.app).get("/api/reels?q=%20%20%20")

    assert response.status_code == 200
    assert calls == [(1, None)]
    assert response.json()["items"] == []
    assert response.json()["query"] == {"q": ""}


def test_reels_api_rejects_pages_below_one() -> None:
    response = TestClient(main.app).get("/api/reels?page=0")

    assert response.status_code == 422


def test_library_query_preserves_search_fields_newest_order_and_page_window() -> None:
    assert "r.creator ILIKE %s" in main.LIBRARY_QUERY
    assert "r.caption ILIKE %s" in main.LIBRARY_QUERY
    assert "enrichment.transcript_text ILIKE %s" in main.LIBRARY_QUERY
    assert "search_category.name ILIKE %s" in main.LIBRARY_QUERY
    assert "enrichment.outcome = 'transcribed'" in main.LIBRARY_QUERY
    assert "ORDER BY r.received_at DESC NULLS LAST, r.id DESC" in main.LIBRARY_QUERY
    assert "LIMIT %s OFFSET %s" in main.LIBRARY_QUERY
    assert "COUNT(" not in main.LIBRARY_QUERY.upper()


def test_reels_api_returns_empty_list_for_valid_no_results(monkeypatch) -> None:
    monkeypatch.setattr(main, "fetch_reels", lambda page, q: ([], False))

    response = TestClient(main.app).get("/api/reels?q=missing")

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["pagination"]["has_next"] is False


def test_reels_api_sanitizes_listing_errors(monkeypatch) -> None:
    def fail(_page, _q):
        raise RuntimeError("postgres://internal-user:secret@database/internal")

    monkeypatch.setattr(main, "fetch_reels", fail)

    response = TestClient(main.app).get("/api/reels")

    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"detail": "Library temporarily unavailable"}
    assert "postgres" not in response.text
    assert "secret" not in response.text
    assert "database" not in response.text


def test_legacy_library_route_continues_using_shared_listing_behavior(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        main,
        "fetch_reels",
        lambda page, q: (calls.append((page, q)) or ([library_row()], False)),
    )

    response = TestClient(main.app).get("/?page=2&q=%20maker%20")

    assert response.status_code == 200
    assert calls == [(2, "maker")]
    assert 'href="/reels/42"' in response.text
