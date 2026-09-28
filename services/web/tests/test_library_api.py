from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import main
from app.auth import config, dependencies, repository


def owner_client(monkeypatch) -> TestClient:
    monkeypatch.setattr(
        dependencies.repository,
        "resolve_session",
        lambda *_: repository.SessionIdentity(7, "owner@example.com"),
    )
    client = TestClient(main.app, base_url="https://testserver")
    client.cookies.set(config.SESSION_COOKIE_NAME, "valid-owner-session")
    return client


def test_fetch_reels_applies_exact_optional_curation_filter(monkeypatch) -> None:
    calls = []

    class FakeCursor:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return None
        def execute(self, query, parameters):
            calls.append((query, parameters))
        def fetchall(self):
            return [{"id": 1}]

    class FakeConnection:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return None
        def cursor(self, *, row_factory):
            return FakeCursor()

    monkeypatch.setattr(main.database, "connect", lambda: FakeConnection())

    rows, has_next = main.fetch_reels(
        page=2,
        search_term="maker",
        curation_status="inbox",
    )

    assert rows == [{"id": 1}]
    assert has_next is False
    assert calls == [(
        main.LIBRARY_QUERY,
        (
            "inbox",
            "inbox",
            "maker",
            "%maker%",
            "%maker%",
            "%maker%",
            "%maker%",
            main.PAGE_SIZE + 1,
            main.PAGE_SIZE,
        ),
    )]
    assert "r.curation_status = %s" in main.LIBRARY_QUERY
    assert "ORDER BY r.received_at DESC NULLS LAST, r.id DESC" in main.LIBRARY_QUERY
    assert "UPDATE " not in main.LIBRARY_QUERY.upper()
    assert "DELETE " not in main.LIBRARY_QUERY.upper()


def test_reels_api_rejects_unknown_curation_status(monkeypatch) -> None:
    client = owner_client(monkeypatch)
    response = client.get("/api/reels?curation_status=unexpected")
    assert response.status_code == 422


def test_reels_api_passes_curation_filter_without_changing_payload(monkeypatch) -> None:
    client = owner_client(monkeypatch)
    calls = []

    monkeypatch.setattr(
        main,
        "fetch_library_page",
        lambda page, q, curation_status=None: calls.append((page, q, curation_status))
        or ([], False, ""),
    )

    response = client.get("/api/reels?page=3&curation_status=inbox")

    assert response.status_code == 200
    assert response.json() == {
        "items": [],
        "query": {"q": ""},
        "pagination": {
            "page": 3,
            "page_size": main.PAGE_SIZE,
            "has_previous": True,
            "has_next": False,
        },
    }
    assert calls == [(3, None, "inbox")]
