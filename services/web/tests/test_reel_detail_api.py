from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app import main
from app.auth import config, dependencies, repository


def detail_reel(**overrides):
    reel = {
        "id": 42,
        "title": "Build a useful thing",
        "creator": "maker",
        "shortcode": "abc123",
        "original_url": "https://www.instagram.com/reel/abc123/",
        "status": "downloaded",
        "caption": "The original caption",
        "duration_seconds": 12.0,
        "filename": "video.mp4",
        "mime_type": "video/mp4",
        "file_size_bytes": 2048,
        "storage_bucket": "private-reels",
        "object_key": "original/instagram/reels/abc123/video.mp4",
        "received_at": datetime(2026, 8, 25, tzinfo=UTC),
        "downloaded_at": datetime(2026, 8, 26, tzinfo=UTC),
        "enrichment_completed_at": datetime(2026, 8, 27, tzinfo=UTC),
        "media_duration_seconds": 12.5,
        "enrichment_outcome": "transcribed",
        "transcript_text": "Accepted transcript text",
        "transcript_language": "pt-BR",
    }
    reel.update(overrides)
    return reel


def owner_client(monkeypatch) -> TestClient:
    monkeypatch.setattr(
        dependencies.repository,
        "resolve_session",
        lambda *_: repository.SessionIdentity(7, "owner@example.com"),
    )
    client = TestClient(main.app, base_url="https://testserver")
    client.cookies.set(config.SESSION_COOKIE_NAME, "valid-owner-session")
    return client


def test_detail_api_rejects_missing_owner_before_all_domain_work(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(main, "fetch_reel", lambda *_: calls.append("fetch_reel"))
    monkeypatch.setattr(main, "fetch_categories_for_reel", lambda *_: calls.append("categories"))
    monkeypatch.setattr(main, "presigned_video_url", lambda *_: calls.append("presign"))

    response = TestClient(main.app).get("/api/reels/42")

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}
    assert calls == []


def test_detail_api_projects_safe_typed_data_and_preserves_presentation_rules(monkeypatch) -> None:
    monkeypatch.setattr(main, "fetch_reel", lambda reel_id: detail_reel(id=reel_id))
    monkeypatch.setattr(
        main,
        "fetch_categories_for_reel",
        lambda _: ([{"id": 1, "name": "Tecnologia"}], [{"id": 2, "name": "Maker"}]),
    )

    response = owner_client(monkeypatch).get("/api/reels/42")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "id": 42,
        "title": "Build a useful thing",
        "creator": "maker",
        "shortcode": "abc123",
        "original_url": "https://www.instagram.com/reel/abc123/",
        "status": "downloaded",
        "caption": "The original caption",
        "duration_seconds": 12.5,
        "received_at": "2026-08-25T00:00:00Z",
        "downloaded_at": "2026-08-26T00:00:00Z",
        "filename": "video.mp4",
        "mime_type": "video/mp4",
        "file_size_bytes": 2048,
        "transcript": {
            "available": True,
            "text": "Accepted transcript text",
            "language": "pt-BR",
            "completed_at": "2026-08-27T00:00:00Z",
        },
        "categories": {
            "assigned": [{"id": 1, "name": "Tecnologia"}],
            "available": [{"id": 2, "name": "Maker"}],
        },
        "video": {"available": True, "src": "/api/reels/42/video"},
    }
    forbidden = {"storage_bucket", "object_key", "storage_provider", "secret", "access_key"}
    assert not (forbidden & set(response.json()))


@pytest.mark.parametrize(
    ("outcome", "text"),
    [("no_audio", "arbitrary text"), ("transcribed", "  ")],
)
def test_detail_api_withholds_nonaccepted_transcripts(monkeypatch, outcome: str, text: str) -> None:
    monkeypatch.setattr(main, "fetch_reel", lambda _: detail_reel(enrichment_outcome=outcome, transcript_text=text))
    monkeypatch.setattr(main, "fetch_categories_for_reel", lambda _: ([], []))

    response = owner_client(monkeypatch).get("/api/reels/42")

    assert response.status_code == 200
    assert response.json()["transcript"] == {
        "available": False,
        "text": None,
        "language": None,
        "completed_at": None,
    }


def test_detail_api_returns_404_for_missing_reel_without_category_work(monkeypatch) -> None:
    monkeypatch.setattr(main, "fetch_reel", lambda _: None)
    monkeypatch.setattr(main, "fetch_categories_for_reel", lambda _: pytest.fail("missing reel must not load categories"))

    response = owner_client(monkeypatch).get("/api/reels/999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Reel not found"}


def test_detail_api_hides_backend_failure(monkeypatch) -> None:
    monkeypatch.setattr(main, "fetch_reel", lambda _: (_ for _ in ()).throw(RuntimeError("postgres://secret")))

    response = owner_client(monkeypatch).get("/api/reels/42")

    assert response.status_code == 503
    assert response.json() == {"detail": "Reel detail temporarily unavailable"}
    assert "postgres" not in response.text
    assert "secret" not in response.text


def test_video_api_rejects_missing_owner_without_signing(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(main, "fetch_reel", lambda *_: calls.append("fetch_reel"))
    monkeypatch.setattr(main, "presigned_video_url", lambda *_: calls.append("presign"))

    response = TestClient(main.app).get("/api/reels/42/video", follow_redirects=False)

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}
    assert calls == []


def test_video_api_returns_404_for_missing_reel_without_signing(monkeypatch) -> None:
    monkeypatch.setattr(main, "fetch_reel", lambda _: None)
    monkeypatch.setattr(main, "presigned_video_url", lambda *_: pytest.fail("missing reel must not sign"))

    response = owner_client(monkeypatch).get("/api/reels/999/video", follow_redirects=False)

    assert response.status_code == 404
    assert response.json() == {"detail": "Reel not found"}


def test_video_api_redirects_only_after_owner_and_reel_lookup(monkeypatch) -> None:
    signed_url = "https://signed.example/video.mp4?temporary=yes"
    monkeypatch.setattr(main, "fetch_reel", lambda _: detail_reel())
    monkeypatch.setattr(main, "presigned_video_url", lambda _: signed_url)

    response = owner_client(monkeypatch).get("/api/reels/42/video", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == signed_url
    assert signed_url not in response.text


def test_video_api_hides_signer_failure_without_logging_url(monkeypatch) -> None:
    monkeypatch.setattr(main, "fetch_reel", lambda _: detail_reel())
    monkeypatch.setattr(main, "presigned_video_url", lambda _: None)

    response = owner_client(monkeypatch).get("/api/reels/42/video", follow_redirects=False)

    assert response.status_code == 503
    assert response.json() == {"detail": "Video temporarily unavailable"}
    assert "signed" not in response.text


def test_detail_and_video_apis_are_described_in_openapi() -> None:
    schema = TestClient(main.app).get("/openapi.json").json()
    detail = schema["paths"]["/api/reels/{reel_id}"]["get"]
    video = schema["paths"]["/api/reels/{reel_id}/video"]["get"]

    assert detail["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ReelDetailResponse"
    }
    assert "307" in video["responses"]
    assert "503" in video["responses"]
