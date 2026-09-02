from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app import categories, database, main, r2, reels
from app.database import DatabaseConfigurationError, DatabaseSettings
from app.main import PAGE_SIZE, app

CSRF_COOKIE_NAME = main.CSRF_COOKIE_NAME
CSRF_TOKEN = "test-csrf-token"


def csrf_client() -> TestClient:
    client = TestClient(app, base_url="https://testserver")
    client.cookies.set(CSRF_COOKIE_NAME, CSRF_TOKEN)
    return client


def csrf_form(**fields: str) -> dict[str, str]:
    return {"csrf_token": CSRF_TOKEN, **fields}


@pytest.fixture(autouse=True)
def empty_categories(monkeypatch) -> None:
    monkeypatch.setattr(main, "fetch_categories_for_reel", lambda reel_id: ([], []))


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


def test_library_renders_available_reel_data(monkeypatch) -> None:
    long_caption = "A source caption that should be shortened in the preview. " * 8
    reel = {
        "id": 42,
        "creator": "maker",
        "shortcode": "abc123",
        "caption": long_caption,
        "categories": ["Hands-on", "Tech"],
        "status": "downloaded",
        "received_at": datetime(2026, 8, 25, tzinfo=UTC),
        "downloaded_at": datetime(2026, 8, 26, tzinfo=UTC),
    }
    monkeypatch.setattr(main, "fetch_reels", lambda page, q: ([reel], False))

    response = TestClient(app).get("/")

    assert response.status_code == 200
    assert "maker" in response.text
    assert "Reel ID: 42" in response.text
    assert "abc123" in response.text
    assert "2026-08-25" in response.text
    assert "2026-08-26" in response.text
    assert long_caption not in response.text
    assert "…" in response.text
    assert "Hands-on" in response.text
    assert "Tech" in response.text
    assert 'href="/reels/42"' in response.text


def test_library_renders_empty_state(monkeypatch) -> None:
    monkeypatch.setattr(main, "fetch_reels", lambda page, q: ([], False))

    response = TestClient(app).get("/")

    assert response.status_code == 200
    assert "Your library is empty" in response.text


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

    reels, has_next = main.fetch_reels(page=3, search_term="Tech")

    assert len(reels) == PAGE_SIZE
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

def test_library_normalizes_search_and_preserves_it_in_pagination(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        main,
        "fetch_reels",
        lambda page, q: (calls.append((page, q)) or ([{"id": 42}], True)),
    )

    response = TestClient(app).get("/?page=2&q=%20%20maker%20ideas%20%20")

    assert response.status_code == 200
    assert calls == [(2, "maker ideas")]
    assert 'value="maker ideas"' in response.text
    assert 'href="/?page=1&amp;q=maker%20ideas"' in response.text
    assert 'href="/?page=3&amp;q=maker%20ideas"' in response.text
    assert 'href="/">Clear</a>' in response.text


def test_empty_search_is_unfiltered(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        main,
        "fetch_reels",
        lambda page, q: (calls.append((page, q)) or ([], False)),
    )

    response = TestClient(app).get("/?q=%20%20%20")

    assert response.status_code == 200
    assert calls == [(1, None)]
    assert "Your library is empty" in response.text
    assert "No reels found" not in response.text


def test_search_no_results_safely_displays_term(monkeypatch) -> None:
    monkeypatch.setattr(main, "fetch_reels", lambda page, q: ([], False))

    response = TestClient(app).get("/?q=%3Cscript%3Ealert(1)%3C/script%3E")

    assert response.status_code == 200
    assert "No reels found" in response.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in response.text
    assert "<script>alert(1)</script>" not in response.text
    assert "Your library is empty" not in response.text


def test_library_hides_database_error_details(monkeypatch) -> None:
    def fail(_page, _q):
        raise RuntimeError("postgres://user:secret@database/internal")

    monkeypatch.setattr(main, "fetch_reels", fail)

    response = TestClient(app).get("/")

    assert response.status_code == 503
    assert "Library temporarily unavailable" in response.text
    assert "secret" not in response.text
    assert "database" not in response.text


def detail_reel(**overrides):
    reel = {
        "id": 42,
        "shortcode": "abc123",
        "original_url": "https://www.instagram.com/reel/abc123/",
        "status": "downloaded",
        "title": "Build a useful thing",
        "creator": "maker",
        "caption": "The original caption",
        "duration_seconds": 12,
        "filename": "video.mp4",
        "mime_type": "video/mp4",
        "file_size_bytes": 2048,
        "storage_provider": "cloudflare_r2",
        "storage_bucket": "private-reels",
        "object_key": "original/instagram/reels/abc123/video.mp4",
        "received_at": datetime(2026, 8, 25, tzinfo=UTC),
        "downloaded_at": datetime(2026, 8, 26, tzinfo=UTC),
        "enrichment_completed_at": datetime(2026, 8, 26, tzinfo=UTC),
        "media_duration_seconds": 12.5,
        "enrichment_outcome": "transcribed",
        "transcript_text": "Accepted transcript text",
        "transcript_language": "en-US",
    }
    reel.update(overrides)
    return reel


def test_reel_detail_renders_metadata_caption_and_accepted_transcript(
    monkeypatch,
) -> None:
    monkeypatch.setattr(main, "fetch_reel", lambda reel_id: detail_reel(id=reel_id))
    monkeypatch.setattr(main, "presigned_video_url", lambda reel: None)

    response = TestClient(app).get("/reels/42")

    assert response.status_code == 200
    assert "Build a useful thing" in response.text
    assert "maker" in response.text
    assert "12.5 seconds" in response.text
    assert "The original caption" in response.text
    assert "Accepted transcript text" in response.text
    assert "Language: en-US" in response.text
    assert "Back to Library" in response.text


def test_reel_detail_renders_assigned_and_available_category_forms(
    monkeypatch,
) -> None:
    monkeypatch.setattr(main, "fetch_reel", lambda reel_id: detail_reel(id=reel_id))
    monkeypatch.setattr(main, "presigned_video_url", lambda reel: None)
    monkeypatch.setattr(
        main,
        "fetch_categories_for_reel",
        lambda reel_id: (
            [{"id": 7, "name": "Tech", "assigned": True}],
            [{"id": 8, "name": "Hands-on", "assigned": False}],
        ),
    )

    response = TestClient(app).get("/reels/42")

    assert response.status_code == 200
    assert "Tech" in response.text
    assert "Hands-on" in response.text
    assert 'action="/reels/42/categories/7/remove"' in response.text
    assert 'action="/reels/42/categories"' in response.text
    assert 'action="/reels/42/categories/new"' in response.text
    assert "The original caption" in response.text
    assert "Accepted transcript text" in response.text


def test_reel_detail_sets_secure_csrf_cookie_and_embeds_token_in_every_form(
    monkeypatch,
) -> None:
    monkeypatch.setattr(main, "fetch_reel", lambda reel_id: detail_reel(id=reel_id))
    monkeypatch.setattr(main, "presigned_video_url", lambda reel: None)
    monkeypatch.setattr(
        main,
        "fetch_categories_for_reel",
        lambda reel_id: (
            [{"id": 7, "name": "Tech", "assigned": True}],
            [{"id": 8, "name": "Hands-on", "assigned": False}],
        ),
    )

    response = TestClient(app, base_url="https://testserver").get("/reels/42")

    token = response.cookies[CSRF_COOKIE_NAME]
    assert token
    assert response.text.count(
        f'<input type="hidden" name="csrf_token" value="{token}">'
    ) == 3
    set_cookie = response.headers["set-cookie"]
    assert "Secure" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie
    assert "Path=/" in set_cookie
    assert "Domain=" not in set_cookie


def test_reel_detail_reuses_csrf_cookie_across_multiple_gets(monkeypatch) -> None:
    monkeypatch.setattr(
        main,
        "fetch_reel",
        lambda reel_id: detail_reel(id=reel_id),
    )
    monkeypatch.setattr(main, "presigned_video_url", lambda reel: None)

    mutations = []

    monkeypatch.setattr(main, "reel_exists", lambda reel_id: True)
    monkeypatch.setattr(
        main,
        "create_and_associate_category",
        lambda reel_id, name: mutations.append((reel_id, name)),
    )

    client = TestClient(app, base_url="https://testserver")

    first_response = client.get("/reels/42")
    first_token = client.cookies.get(CSRF_COOKIE_NAME)

    assert first_response.status_code == 200
    assert first_token
    assert first_token in first_response.text

    second_response = client.get("/reels/43")
    second_token = client.cookies.get(CSRF_COOKIE_NAME)

    assert second_response.status_code == 200
    assert second_token == first_token
    assert first_token in second_response.text

    # The second GET reuses the existing CSRF cookie instead of rotating it.
    assert "set-cookie" not in second_response.headers

    # Simulate submitting a form that remained open in the first browser tab.
    post_response = client.post(
        "/reels/42/categories/new",
        data={
            "csrf_token": first_token,
            "name": "Tech",
        },
        follow_redirects=False,
    )

    assert post_response.status_code == 303
    assert mutations == [(42, "Tech")]


@pytest.mark.parametrize(
    ("path", "data"),
    [
        ("/reels/42/categories", {"category_id": "7"}),
        ("/reels/42/categories/new", {"name": "Tech"}),
        ("/reels/42/categories/7/remove", {}),
    ],
)
@pytest.mark.parametrize(
    ("cookie_token", "submitted_token"),
    [("valid-cookie-token", None), ("valid-cookie-token", "invalid"), (None, "valid")],
)
def test_category_posts_reject_missing_or_invalid_csrf_before_database_access(
    monkeypatch, path, data, cookie_token, submitted_token
) -> None:
    monkeypatch.setattr(
        main, "reel_exists", lambda *args: pytest.fail("CSRF must precede reel lookup")
    )
    monkeypatch.setattr(
        main, "associate_category", lambda *args: pytest.fail("must not mutate")
    )
    monkeypatch.setattr(
        main,
        "create_and_associate_category",
        lambda *args: pytest.fail("must not mutate"),
    )
    monkeypatch.setattr(
        main, "remove_category", lambda *args: pytest.fail("must not mutate")
    )
    client = TestClient(app, base_url="https://testserver")
    if cookie_token is not None:
        client.cookies.set(CSRF_COOKIE_NAME, cookie_token)
    submitted_data = dict(data)
    if submitted_token is not None:
        submitted_data["csrf_token"] = submitted_token

    response = client.post(path, data=submitted_data, follow_redirects=False)

    assert response.status_code == 403


def test_category_post_does_not_accept_csrf_token_from_query(monkeypatch) -> None:
    monkeypatch.setattr(
        main, "reel_exists", lambda *args: pytest.fail("CSRF must precede reel lookup")
    )
    client = TestClient(app, base_url="https://testserver")
    client.cookies.set(CSRF_COOKIE_NAME, "valid-token")

    response = client.post(
        "/reels/42/categories?csrf_token=valid-token",
        data={"category_id": "7"},
        follow_redirects=False,
    )

    assert response.status_code == 403


def test_create_category_normalizes_name_and_redirects(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(main, "reel_exists", lambda reel_id: True)
    monkeypatch.setattr(
        main,
        "create_and_associate_category",
        lambda reel_id, name: calls.append((reel_id, name)),
    )

    response = csrf_client().post(
        "/reels/42/categories/new",
        data=csrf_form(name="  Tech  "),
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/reels/42"
    assert calls == [(42, "Tech")]


def test_empty_category_name_does_not_mutate(monkeypatch) -> None:
    monkeypatch.setattr(main, "reel_exists", lambda reel_id: True)
    monkeypatch.setattr(
        main,
        "create_and_associate_category",
        lambda *args: pytest.fail("empty names must not mutate"),
    )

    response = csrf_client().post(
        "/reels/42/categories/new",
        data=csrf_form(name="   "),
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/reels/42?curation_error=empty-name"


@pytest.mark.parametrize(
    ("path", "data"),
    [
        ("/reels/999/categories", {"category_id": "7"}),
        ("/reels/999/categories/new", {"name": "Tech"}),
        ("/reels/999/categories/7/remove", {}),
    ],
)
def test_category_posts_keep_missing_reel_as_404(monkeypatch, path, data) -> None:
    monkeypatch.setattr(main, "reel_exists", lambda reel_id: False)

    response = csrf_client().post(
        path, data={**data, "csrf_token": CSRF_TOKEN}, follow_redirects=False
    )

    assert response.status_code == 404
    assert "Reel not found" in response.text


def test_category_database_error_is_hidden_behind_prg(monkeypatch) -> None:
    monkeypatch.setattr(main, "reel_exists", lambda reel_id: True)

    def fail(*args):
        raise RuntimeError("postgres://user:secret@database/internal")

    monkeypatch.setattr(main, "associate_category", fail)

    response = csrf_client().post(
        "/reels/42/categories",
        data=csrf_form(category_id="7"),
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/reels/42?curation_error=database"
    assert "secret" not in response.text


def test_existing_category_association_is_duplicate_safe(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(main, "reel_exists", lambda reel_id: True)
    monkeypatch.setattr(
        main,
        "associate_category",
        lambda reel_id, category_id: calls.append((reel_id, category_id)),
    )

    client = csrf_client()
    responses = [
        client.post(
            "/reels/42/categories",
            data=csrf_form(category_id="7"),
            follow_redirects=False,
        )
        for _ in range(2)
    ]

    assert [response.status_code for response in responses] == [303, 303]
    assert [response.headers["location"] for response in responses] == [
        "/reels/42",
        "/reels/42",
    ]
    assert calls == [(42, 7), (42, 7)]
    assert "ON CONFLICT (reel_id, category_id) DO NOTHING" in (
        categories.ASSOCIATE_CATEGORY_QUERY
    )


def test_category_removal_redirects_after_success(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(main, "reel_exists", lambda reel_id: True)
    monkeypatch.setattr(
        main,
        "remove_category",
        lambda reel_id, category_id: calls.append((reel_id, category_id)),
    )

    response = csrf_client().post(
        "/reels/42/categories/7/remove",
        data=csrf_form(),
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/reels/42"
    assert calls == [(42, 7)]


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


def test_reel_detail_returns_404_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(main, "fetch_reel", lambda reel_id: None)

    response = TestClient(app).get("/reels/999")

    assert response.status_code == 404
    assert "Reel not found" in response.text


@pytest.mark.parametrize(
    ("outcome", "transcript"),
    [("no_audio", None), ("empty_transcript", ""), ("transcribed", "   ")],
)
def test_reel_detail_marks_nonaccepted_transcript_unavailable(
    monkeypatch, outcome, transcript
) -> None:
    monkeypatch.setattr(
        main,
        "fetch_reel",
        lambda reel_id: detail_reel(
            enrichment_outcome=outcome, transcript_text=transcript
        ),
    )
    monkeypatch.setattr(main, "presigned_video_url", lambda reel: None)

    response = TestClient(app).get("/reels/42")

    assert response.status_code == 200
    assert "Transcript unavailable." in response.text
    assert "Language: en-US" not in response.text


def test_reel_detail_uses_signed_video_url(monkeypatch) -> None:
    signed_url = "https://signed.example/video.mp4?temporary=yes"
    monkeypatch.setattr(main, "fetch_reel", lambda reel_id: detail_reel())
    monkeypatch.setattr(main, "presigned_video_url", lambda reel: signed_url)

    response = TestClient(app).get("/reels/42")

    assert response.status_code == 200
    assert 'src="https://signed.example/video.mp4?temporary=yes"' in response.text
    assert "Video temporarily unavailable." not in response.text


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


def test_reel_detail_hides_signer_failure(monkeypatch) -> None:
    for name, value in {
        "R2_ENDPOINT": "https://account.r2.example.invalid",
        "R2_ACCESS_KEY_ID": "secret-id",
        "R2_SECRET_ACCESS_KEY": "secret-key",
        "R2_BUCKET": "private-reels",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(main, "fetch_reel", lambda reel_id: detail_reel())

    def fail_client(*args):
        raise RuntimeError("https://leaked.example/signed?credential=secret-key")

    monkeypatch.setattr(r2, "_client", fail_client)

    response = TestClient(app).get("/reels/42")

    assert response.status_code == 200
    assert "Video temporarily unavailable." in response.text
    assert "secret-key" not in response.text
    assert "leaked.example" not in response.text


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
