from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app import categories, database, main, r2, reels
from app.database import DatabaseConfigurationError, DatabaseSettings
from app.main import PAGE_SIZE, app


def test_health_does_not_require_database_configuration(monkeypatch) -> None:
    for name in (
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_DB",
        "WEB_DB_USER",
        "WEB_DB_PASSWORD",
    ):
        monkeypatch.delenv(name, raising=False)

    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "version": "0.1.0"}


def test_database_settings_report_missing_configuration(monkeypatch) -> None:
    for name in (
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_DB",
        "WEB_DB_USER",
        "WEB_DB_PASSWORD",
    ):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(DatabaseConfigurationError) as error:
        DatabaseSettings.from_environment()

    assert str(error.value) == (
        "Missing required PostgreSQL configuration: POSTGRES_HOST, POSTGRES_PORT, "
        "POSTGRES_DB, WEB_DB_USER, WEB_DB_PASSWORD"
    )


def test_connect_uses_environment_configuration(monkeypatch) -> None:
    configured = {
        "POSTGRES_HOST": "postgres",
        "POSTGRES_PORT": "5432",
        "POSTGRES_DB": "megabrain",
        "WEB_DB_USER": "web-test-user",
        "WEB_DB_PASSWORD": "fake-test-password",
    }
    for name, value in configured.items():
        monkeypatch.setenv(name, value)

    connection = object()
    calls = []

    def fake_connect(**kwargs):
        calls.append(kwargs)
        return connection

    monkeypatch.setattr(database.psycopg, "connect", fake_connect)

    assert database.connect() is connection
    assert calls == [
        {
            "host": "postgres",
            "port": 5432,
            "dbname": "megabrain",
            "user": "web-test-user",
            "password": "fake-test-password",
        }
    ]


def test_database_settings_do_not_fall_back_to_postgres_owner_credentials(
    monkeypatch,
) -> None:
    for name, value in {
        "POSTGRES_HOST": "postgres",
        "POSTGRES_PORT": "5432",
        "POSTGRES_DB": "megabrain",
        "POSTGRES_USER": "owner",
        "POSTGRES_PASSWORD": "owner-password",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("WEB_DB_USER", raising=False)
    monkeypatch.delenv("WEB_DB_PASSWORD", raising=False)

    with pytest.raises(DatabaseConfigurationError) as error:
        DatabaseSettings.from_environment()

    assert str(error.value) == (
        "Missing required PostgreSQL configuration: WEB_DB_USER, WEB_DB_PASSWORD"
    )


def test_fetch_reels_uses_parameterized_pagination(monkeypatch) -> None:
    rows = [{"id": reel_id} for reel_id in range(PAGE_SIZE + 1)]
    calls = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execute(self, query, parameters):
            calls.append((query, parameters))

        def fetchall(self):
            return rows

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def cursor(self, *, row_factory):
            return FakeCursor()

    monkeypatch.setattr(database, "connect", lambda: FakeConnection())

    reel_rows, has_next = main.fetch_reels(page=3, search_term="Tech")

    assert len(reel_rows) == PAGE_SIZE
    assert has_next is True
    assert calls == [
        (
            main.LIBRARY_QUERY,
            (
                "Tech",
                "%Tech%",
                "%Tech%",
                "%Tech%",
                "%Tech%",
                PAGE_SIZE + 1,
                PAGE_SIZE * 2,
            ),
        )
    ]
    assert "FROM app.reels" in main.LIBRARY_QUERY
    assert "ORDER BY r.received_at DESC NULLS LAST, r.id DESC" in main.LIBRARY_QUERY
    assert "LIMIT %s OFFSET %s" in main.LIBRARY_QUERY
    assert "array_agg" in main.LIBRARY_QUERY
    assert "app.reel_categories" in main.LIBRARY_QUERY
    assert "app.reel_enrichments" in main.LIBRARY_QUERY
    assert "ORDER BY completed_at DESC, id DESC" in main.LIBRARY_QUERY
    assert "r.creator ILIKE %s" in main.LIBRARY_QUERY
    assert "r.caption ILIKE %s" in main.LIBRARY_QUERY
    assert "enrichment.transcript_text ILIKE %s" in main.LIBRARY_QUERY
    assert "search_category.name ILIKE %s" in main.LIBRARY_QUERY
    assert "Tech" not in main.LIBRARY_QUERY
    assert "EXISTS" in main.LIBRARY_QUERY
    assert "COUNT(" not in main.LIBRARY_QUERY.upper()
    assert "captured_at" not in main.LIBRARY_QUERY
    assert "%s::text IS NULL" in main.LIBRARY_QUERY


def test_create_and_associate_reuses_category_case_insensitively(monkeypatch) -> None:
    calls = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execute(self, query, parameters):
            calls.append((query, parameters))

        def fetchone(self):
            return (7,)

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(database, "connect", lambda: FakeConnection())

    categories.create_and_associate_category(42, "Tech")

    assert calls == [
        (categories.INSERT_CATEGORY_QUERY, ("Tech",)),
        (categories.FIND_CATEGORY_QUERY, ("Tech",)),
        (categories.ASSOCIATE_CATEGORY_QUERY, (42, 7)),
    ]
    assert "ON CONFLICT (lower(name)) DO NOTHING" in categories.INSERT_CATEGORY_QUERY
    assert "ON CONFLICT (reel_id, category_id) DO NOTHING" in (
        categories.ASSOCIATE_CATEGORY_QUERY
    )


def detail_reel(**overrides):
    reel = {
        "id": 42,
        "shortcode": "abc123",
        "storage_bucket": "private-reels",
        "object_key": "original/instagram/reels/abc123/video.mp4",
        "received_at": datetime(2026, 8, 25, tzinfo=UTC),
    }
    reel.update(overrides)
    return reel


def test_presigned_video_url_uses_canonical_r2_configuration(monkeypatch) -> None:
    configured = {
        "R2_ENDPOINT": "https://account.r2.example.invalid",
        "R2_ACCESS_KEY_ID": "access-key-id",
        "R2_SECRET_ACCESS_KEY": "secret-access-key",
        "R2_BUCKET": "private-reels",
    }
    for name, value in configured.items():
        monkeypatch.setenv(name, value)

    client_calls = []
    signing_calls = []

    class FakeClient:
        def generate_presigned_url(self, operation, *, Params, ExpiresIn):
            signing_calls.append((operation, Params, ExpiresIn))
            return "https://signed.example/video.mp4"

    def fake_client(endpoint, access_key_id, secret_access_key):
        client_calls.append((endpoint, access_key_id, secret_access_key))
        return FakeClient()

    monkeypatch.setattr(r2, "_client", fake_client)

    assert r2.presigned_video_url(detail_reel()) == "https://signed.example/video.mp4"
    assert client_calls == [
        (
            "https://account.r2.example.invalid",
            "access-key-id",
            "secret-access-key",
        )
    ]
    assert signing_calls == [
        (
            "get_object",
            {
                "Bucket": "private-reels",
                "Key": "original/instagram/reels/abc123/video.mp4",
            },
            300,
        )
    ]


def test_fetch_reel_uses_parameterized_detail_query(monkeypatch) -> None:
    calls = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execute(self, query, parameters):
            calls.append((query, parameters))

        def fetchone(self):
            return {"id": 42}

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def cursor(self, *, row_factory):
            return FakeCursor()

    monkeypatch.setattr(database, "connect", lambda: FakeConnection())

    assert reels.fetch_reel(42) == {"id": 42}
    assert calls == [(reels.REEL_DETAIL_QUERY, (42,))]
    assert "WHERE r.id = %s" in reels.REEL_DETAIL_QUERY
    assert "app.reel_enrichments" in reels.REEL_DETAIL_QUERY


@pytest.mark.parametrize(
    ("method", "path", "request_kwargs"),
    [
        ("get", "/", {}),
        ("get", "/reels/42", {}),
        ("post", "/reels/42/categories", {"data": {"category_id": "7"}}),
        ("post", "/reels/42/categories/new", {"data": {"name": "Tech"}}),
        ("post", "/reels/42/categories/7/remove", {"data": {"remove": "1"}}),
    ],
)
def test_retired_presentation_routes_return_json_404_without_domain_work(
    monkeypatch, method: str, path: str, request_kwargs: dict
) -> None:
    calls: list[str] = []
    for name in (
        "fetch_reel",
        "reel_exists",
        "associate_category",
        "create_and_associate_category",
        "remove_category",
        "presigned_video_url",
    ):
        monkeypatch.setattr(main, name, lambda *_, name=name: calls.append(name))

    response = getattr(TestClient(app), method)(path, **request_kwargs)

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"detail": "Not Found"}
    assert calls == []


def test_openapi_excludes_retired_presentation_routes_and_preserves_active_contracts() -> None:
    paths = app.openapi()["paths"]

    retired_paths = {
        "/",
        "/reels/{reel_id}",
        "/reels/{reel_id}/categories",
        "/reels/{reel_id}/categories/new",
        "/reels/{reel_id}/categories/{category_id}/remove",
    }
    active_paths = {
        "/health",
        "/api/auth/session",
        "/api/auth/csrf",
        "/api/reels",
        "/api/reels/{reel_id}",
        "/api/reels/{reel_id}/video",
        "/api/reels/{reel_id}/categories",
        "/api/reels/{reel_id}/categories/new",
        "/api/reels/{reel_id}/categories/{category_id}",
        "/auth/login",
        "/auth/callback",
        "/auth/logout",
    }

    assert retired_paths.isdisjoint(paths)
    assert active_paths <= set(paths)
