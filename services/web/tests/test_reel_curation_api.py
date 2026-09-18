from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app import main
from app.auth import config, dependencies, repository
from app.csrf import CSRF_COOKIE_NAME
from app.reel_lifecycle import LifecycleStatusError

CSRF_TOKEN = "valid-api-csrf-token"


def lifecycle_reel(**overrides: object) -> dict[str, object]:
    reel: dict[str, object] = {
        "id": 42,
        "download_status": "downloaded",
        "curation_status": "inbox",
        "transcription_status": "completed",
        "transcription_attempt_id": "internal-attempt-id",
        "categories": ["Tech"],
        "source": "instagram",
        "telegram_chat_id": None,
        "received_at": datetime(2026, 9, 14, tzinfo=UTC),
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
    client.cookies.set(CSRF_COOKIE_NAME, CSRF_TOKEN)
    return client


def csrf_headers(token: str = CSRF_TOKEN) -> dict[str, str]:
    return {"X-CSRF-Token": token}


def test_owner_curation_patch_returns_only_explicit_lifecycle_projection(monkeypatch) -> None:
    calls: list[tuple[int, str]] = []
    client = owner_client(monkeypatch)
    before = lifecycle_reel()
    after = lifecycle_reel(curation_status="organized")
    monkeypatch.setattr(main, "set_curation_status", lambda reel_id, curation_status: calls.append((reel_id, curation_status)) or after)

    response = client.patch(
        "/api/reels/42/curation",
        json={"curation_status": "organized"},
        headers=csrf_headers(),
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "id": 42,
        "download_status": "downloaded",
        "curation_status": "organized",
        "transcription_status": "completed",
    }
    assert calls == [(42, "organized")]
    assert before["download_status"] == after["download_status"]
    assert before["transcription_status"] == after["transcription_status"]
    assert before["categories"] == after["categories"]
    assert "transcription_attempt_id" not in response.json()


@pytest.mark.parametrize(
    "initial_status,target_status",
    [("inbox", "organized"), ("organized", "inbox"), ("organized", "organized")],
)
def test_curation_patch_supports_both_transitions_and_same_state_idempotently(
    monkeypatch, initial_status: str, target_status: str
) -> None:
    client = owner_client(monkeypatch)
    calls: list[tuple[int, str]] = []
    monkeypatch.setattr(
        main,
        "set_curation_status",
        lambda reel_id, curation_status: calls.append((reel_id, curation_status))
        or lifecycle_reel(curation_status=curation_status),
    )

    first = client.patch(
        "/api/reels/42/curation", json={"curation_status": target_status}, headers=csrf_headers()
    )
    second = client.patch(
        "/api/reels/42/curation", json={"curation_status": target_status}, headers=csrf_headers()
    )

    assert first.status_code == second.status_code == 200
    assert first.json()["curation_status"] == second.json()["curation_status"] == target_status
    assert calls == [(42, target_status), (42, target_status)]


def test_curation_patch_rejects_anonymous_before_csrf_or_domain_access(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(main, "set_curation_status", lambda *_: calls.append("mutation"))
    client = TestClient(main.app, base_url="https://testserver")
    client.cookies.set(CSRF_COOKIE_NAME, CSRF_TOKEN)

    response = client.patch(
        "/api/reels/42/curation", json={"curation_status": "organized"}, headers=csrf_headers()
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}
    assert calls == []


@pytest.mark.parametrize("header_token", [None, "invalid-api-csrf-token"])
def test_curation_patch_rejects_missing_or_invalid_csrf_before_domain_access(monkeypatch, header_token: str | None) -> None:
    client = owner_client(monkeypatch)
    monkeypatch.setattr(main, "set_curation_status", lambda *_: pytest.fail("invalid CSRF must not mutate"))

    response = client.patch(
        "/api/reels/42/curation",
        json={"curation_status": "organized"},
        headers=csrf_headers(header_token) if header_token else {},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "CSRF token validation failed"}


def test_curation_patch_returns_existing_404_for_unknown_reel_after_owner_and_csrf(monkeypatch) -> None:
    client = owner_client(monkeypatch)
    monkeypatch.setattr(main, "set_curation_status", lambda *_: None)

    response = client.patch(
        "/api/reels/999/curation", json={"curation_status": "organized"}, headers=csrf_headers()
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Reel not found"}


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"curation_status": "invalid"},
        {"curation_status": "organized", "download_status": "failed"},
        {"curation_status": "organized", "transcription_status": "completed"},
        {"curation_status": "organized", "transcription_attempt_id": "attempt"},
        {"curation_status": "organized", "other": "forbidden"},
    ],
)
def test_curation_patch_rejects_invalid_or_authority_smuggling_body_before_domain_access(monkeypatch, payload: dict[str, object]) -> None:
    client = owner_client(monkeypatch)
    monkeypatch.setattr(main, "set_curation_status", lambda *_: pytest.fail("invalid body must not mutate"))

    response = client.patch("/api/reels/42/curation", json=payload, headers=csrf_headers())

    assert response.status_code == 422


@pytest.mark.parametrize("body", [b"{", b"[]", b"null"])
def test_curation_patch_rejects_malformed_json_before_domain_access(monkeypatch, body: bytes) -> None:
    client = owner_client(monkeypatch)
    monkeypatch.setattr(main, "set_curation_status", lambda *_: pytest.fail("malformed body must not mutate"))

    response = client.patch(
        "/api/reels/42/curation",
        content=body,
        headers={"Content-Type": "application/json", **csrf_headers()},
    )

    assert response.status_code == 422


def test_curation_repository_is_targeted_and_source_neutral() -> None:
    from app import reels

    assert "UPDATE app.reels" in reels.SET_CURATION_STATUS_QUERY
    assert "SET curation_status = %s" in reels.SET_CURATION_STATUS_QUERY
    assert "RETURNING" in reels.SET_CURATION_STATUS_QUERY
    assert "download_status" not in reels.SET_CURATION_STATUS_QUERY.split("RETURNING", 1)[0]
    assert "transcription_status" not in reels.SET_CURATION_STATUS_QUERY.split("RETURNING", 1)[0]
    assert "transcription_attempt_id" not in reels.SET_CURATION_STATUS_QUERY
    assert "source" not in reels.SET_CURATION_STATUS_QUERY


def test_curation_repository_validates_approved_vocabulary_before_database_access(monkeypatch) -> None:
    from app import reels

    monkeypatch.setattr(reels.database, "connect", lambda: pytest.fail("invalid curation must not access database"))

    with pytest.raises(LifecycleStatusError):
        reels.set_curation_status(42, "not-approved")


def test_category_operations_remain_independent_from_curation() -> None:
    from app.categories import ASSOCIATE_CATEGORY_QUERY, REMOVE_CATEGORY_QUERY

    assert "curation_status" not in ASSOCIATE_CATEGORY_QUERY
    assert "curation_status" not in REMOVE_CATEGORY_QUERY


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/reels/42/categories", {"category_id": 7, "download_status": "failed"}),
        ("/api/reels/42/categories", {"category_id": 7, "transcription_status": "completed"}),
        ("/api/reels/42/categories/new", {"name": "Tech", "curation_status": "organized"}),
    ],
)
def test_category_requests_reject_lifecycle_authority_smuggling_before_domain_access(
    monkeypatch, path: str, payload: dict[str, object]
) -> None:
    client = owner_client(monkeypatch)
    monkeypatch.setattr(main, "reel_exists", lambda *_: pytest.fail("smuggled field must not query reel"))
    monkeypatch.setattr(main, "associate_category", lambda *_: pytest.fail("smuggled field must not mutate"))
    monkeypatch.setattr(main, "create_and_associate_category", lambda *_: pytest.fail("smuggled field must not mutate"))

    response = client.post(path, json=payload, headers=csrf_headers())

    assert response.status_code == 422


def test_curation_patch_is_described_as_owner_and_csrf_protected_strict_json() -> None:
    operation = main.app.openapi()["paths"]["/api/reels/{reel_id}/curation"]["patch"]

    assert operation["security"] == [{"OwnerSessionCookie": []}]
    assert operation["responses"]["401"] == {"description": "Authentication required"}
    assert operation["responses"]["403"] == {"description": "CSRF token validation failed"}
    assert operation["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/CurationStatusRequest"
    }
    assert any(
        parameter["in"] == "header" and parameter["name"] == "X-CSRF-Token" and parameter["required"]
        for parameter in operation["parameters"]
    )
