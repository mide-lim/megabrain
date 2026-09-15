from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import main
from app import internal_ingestion
from app import reel_dispatch
from app import reel_ingestion
from app.auth.dependencies import require_owner_session
from app.csrf import require_api_csrf
from app.reel_ingestion import (
    InvalidReelUrl,
    ReelIdentityConflict,
    ReelRegistrationUnavailable,
    RegisteredReel,
)


VALID_URL = "https://www.instagram.com/reel/abc_123/"


def registered_reel(**overrides: object) -> RegisteredReel:
    values: dict[str, Any] = {
        "id": 42,
        "shortcode": "abc_123",
        "original_url": VALID_URL,
        "source": "instagram",
        "download_status": "received",
        "telegram_chat_id": None,
        "telegram_user_id": None,
        "telegram_message_id": None,
        "raw_message": None,
        "received_at": datetime(2026, 9, 14, tzinfo=UTC),
        "created": True,
    }
    values.update(overrides)
    return RegisteredReel(**values)


def client_with_owner_and_csrf() -> TestClient:
    main.app.dependency_overrides[require_owner_session] = lambda: object()
    main.app.dependency_overrides[require_api_csrf] = lambda: None
    return TestClient(main.app)


def configure_dispatch(monkeypatch, state: str = "accepted") -> None:
    monkeypatch.setattr(main, "load_dispatch_settings", lambda: object())

    async def fake_dispatch(reel, settings):
        return main.DispatchState(state)

    monkeypatch.setattr(main, "dispatch_reel", fake_dispatch)


def test_reel_creation_requires_owner_before_registration(monkeypatch) -> None:
    monkeypatch.setattr(
        main,
        "register_reel",
        lambda *_args, **_kwargs: pytest.fail("owner check must precede registration"),
    )

    response = TestClient(main.app).post("/api/reels", json={"url": VALID_URL})

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}


def test_reel_creation_requires_csrf_before_registration(monkeypatch) -> None:
    main.app.dependency_overrides[require_owner_session] = lambda: object()
    monkeypatch.setattr(
        main,
        "register_reel",
        lambda *_args, **_kwargs: pytest.fail("CSRF check must precede registration"),
    )
    try:
        response = TestClient(main.app).post("/api/reels", json={"url": VALID_URL})
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 403
    assert response.json() == {"detail": "CSRF token validation failed"}


@pytest.mark.parametrize(
    "body",
    [
        b"{",
        b"[]",
        b"{}",
        b'{"url": 42}',
        b'{"url":"https://www.instagram.com/reel/abc_123/","telegram":{}}',
        b'{"url":"https://www.instagram.com/reel/abc_123/","source":"instagram"}',
        b'{"url":"https://www.instagram.com/reel/abc_123/","status":"received"}',
        b'{"url":"https://www.instagram.com/reel/abc_123/","download_status":"received"}',
        b'{"url":"https://www.instagram.com/reel/abc_123/","transcription_status":"queued"}',
        b'{"url":"https://www.instagram.com/reel/abc_123/","curation_status":"organized"}',
        b'{"url":"https://www.instagram.com/reel/abc_123/","shortcode":"abc_123"}',
        b'{"url":"https://www.instagram.com/reel/abc_123/","original_url":"x"}',
    ],
)
def test_reel_creation_rejects_non_strict_request_before_registration(monkeypatch, body: bytes) -> None:
    client = client_with_owner_and_csrf()
    monkeypatch.setattr(
        main,
        "register_reel",
        lambda *_args, **_kwargs: pytest.fail("invalid body must not register"),
    )
    try:
        response = client.post(
            "/api/reels",
            content=body,
            headers={"Content-Type": "application/json"},
        )
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "error": {"code": "invalid_request", "message": "Invalid reel request"}
    }


def test_reel_creation_rejects_text_plain_json_before_registration_or_dispatch_configuration(
    monkeypatch,
) -> None:
    client = client_with_owner_and_csrf()
    monkeypatch.setattr(
        main,
        "register_reel",
        lambda *_args, **_kwargs: pytest.fail("invalid media type must not register"),
    )
    monkeypatch.setattr(
        main,
        "load_dispatch_settings",
        lambda: pytest.fail("invalid media type must not load dispatch configuration"),
    )
    try:
        response = client.post(
            "/api/reels",
            content=b'{"url":"https://www.instagram.com/reel/abc_123/"}',
            headers={"Content-Type": "text/plain"},
        )
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "error": {"code": "invalid_request", "message": "Invalid reel request"}
    }


def test_reel_creation_rejects_missing_content_type_before_registration_or_dispatch_configuration(
    monkeypatch,
) -> None:
    client = client_with_owner_and_csrf()
    monkeypatch.setattr(
        main,
        "register_reel",
        lambda *_args, **_kwargs: pytest.fail("missing media type must not register"),
    )
    monkeypatch.setattr(
        main,
        "load_dispatch_settings",
        lambda: pytest.fail("missing media type must not load dispatch configuration"),
    )
    try:
        response = client.post(
            "/api/reels",
            content=b'{"url":"https://www.instagram.com/reel/abc_123/"}',
        )
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "error": {"code": "invalid_request", "message": "Invalid reel request"}
    }


@pytest.mark.parametrize("content_type", ["application/json", "application/json; charset=utf-8"])
def test_reel_creation_accepts_json_media_type_with_optional_charset(monkeypatch, content_type: str) -> None:
    client = client_with_owner_and_csrf()
    registrations: list[tuple[str, object]] = []
    monkeypatch.setattr(
        main,
        "register_reel",
        lambda raw_url, telegram_metadata: registrations.append((raw_url, telegram_metadata))
        or registered_reel(),
    )
    configure_dispatch(monkeypatch)
    try:
        response = client.post(
            "/api/reels",
            content=b'{"url":"https://www.instagram.com/reel/abc_123/"}',
            headers={"Content-Type": content_type},
        )
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 201
    assert response.json()["dispatch"] == {"state": "accepted"}
    assert registrations == [(VALID_URL, None)]


def test_reel_creation_rejects_invalid_instagram_url_before_dispatch(monkeypatch) -> None:
    client = client_with_owner_and_csrf()
    monkeypatch.setattr(main, "register_reel", reel_ingestion.register_reel)
    monkeypatch.setattr(
        main,
        "load_dispatch_settings",
        lambda: pytest.fail("invalid URL must not load outbound dispatch configuration"),
    )
    try:
        response = client.post("/api/reels", json={"url": "https://example.test/reel/abc_123/"})
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 422
    assert response.json() == {
        "error": {"code": "invalid_request", "message": "Invalid reel request"}
    }


@pytest.mark.parametrize(
    ("created", "dispatch_state", "expected_status"),
    [(True, "accepted", 201), (True, "unconfirmed", 201)],
)
def test_new_reel_returns_durable_response_and_dispatch_state(
    monkeypatch, created: bool, dispatch_state: str, expected_status: int
) -> None:
    client = client_with_owner_and_csrf()
    registrations: list[tuple[str, object]] = []
    monkeypatch.setattr(
        main,
        "register_reel",
        lambda raw_url, telegram_metadata: registrations.append((raw_url, telegram_metadata))
        or registered_reel(created=created),
    )
    configure_dispatch(monkeypatch, dispatch_state)
    try:
        response = client.post("/api/reels", json={"url": VALID_URL})
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == expected_status
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "reel": {
            "id": 42,
            "shortcode": "abc_123",
            "original_url": VALID_URL,
            "download_status": "received",
            "created": created,
        },
        "dispatch": {"state": dispatch_state},
    }
    assert registrations == [(VALID_URL, None)]


@pytest.mark.parametrize(
    ("persisted_status", "dispatch_state", "expected_calls"),
    [
        ("received", "accepted", [42]),
        ("failed", "unconfirmed", [42]),
        ("downloading", "not_required", []),
        ("downloaded", "not_required", []),
    ],
)
def test_existing_reel_uses_shared_persisted_status_dispatch_decision(
    monkeypatch, persisted_status: str, dispatch_state: str, expected_calls: list[int]
) -> None:
    client = client_with_owner_and_csrf()
    dispatch_calls: list[int] = []
    monkeypatch.setattr(
        main,
        "register_reel",
        lambda *_args, **_kwargs: registered_reel(download_status=persisted_status, created=False),
    )
    monkeypatch.setattr(
        main,
        "load_dispatch_settings",
        lambda: reel_dispatch.WebToN8nDispatchSettings("outbound-key", reel_dispatch.DISPATCH_URL),
    )

    async def fake_request_dispatch(reel_id, settings):
        dispatch_calls.append(reel_id)
        return reel_dispatch.DispatchState(dispatch_state)

    monkeypatch.setattr(reel_dispatch, "request_internal_dispatch", fake_request_dispatch)
    try:
        response = client.post("/api/reels", json={"url": VALID_URL})
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["reel"]["download_status"] == persisted_status
    assert response.json()["reel"]["created"] is False
    assert response.json()["dispatch"] == {"state": dispatch_state}
    assert dispatch_calls == expected_calls


def test_unknown_persisted_status_returns_bounded_503_without_dispatch(monkeypatch) -> None:
    client = client_with_owner_and_csrf()
    dispatch_calls: list[int] = []
    monkeypatch.setattr(main, "register_reel", lambda *_args, **_kwargs: registered_reel(download_status="unknown"))
    monkeypatch.setattr(
        main,
        "load_dispatch_settings",
        lambda: reel_dispatch.WebToN8nDispatchSettings("outbound-key", reel_dispatch.DISPATCH_URL),
    )

    async def fake_request_dispatch(reel_id, settings):
        dispatch_calls.append(reel_id)
        return reel_dispatch.DispatchState.ACCEPTED

    monkeypatch.setattr(reel_dispatch, "request_internal_dispatch", fake_request_dispatch)
    try:
        response = client.post("/api/reels", json={"url": VALID_URL})
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "error": {
            "code": "reel_dispatch_unavailable",
            "message": "Reel dispatch temporarily unavailable",
        }
    }
    assert dispatch_calls == []
    assert "unknown" not in response.text


@pytest.mark.parametrize(
    ("exception", "status_code", "code", "message"),
    [
        (ReelIdentityConflict("private conflict"), 409, "reel_identity_conflict", "Reel natural identity conflict"),
        (
            ReelRegistrationUnavailable("private database detail"),
            503,
            "registration_unavailable",
            "Reel registration temporarily unavailable",
        ),
        (InvalidReelUrl("private URL detail"), 422, "invalid_request", "Invalid reel request"),
    ],
)
def test_reel_creation_domain_errors_are_bounded_without_leaks(
    monkeypatch, exception: Exception, status_code: int, code: str, message: str
) -> None:
    client = client_with_owner_and_csrf()
    monkeypatch.setattr(
        main,
        "register_reel",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(exception),
    )
    try:
        response = client.post("/api/reels", json={"url": VALID_URL})
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == status_code
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"error": {"code": code, "message": message}}
    assert "private" not in response.text


def test_reel_creation_does_not_convert_unexpected_registration_value_error_to_422(
    monkeypatch,
) -> None:
    client = client_with_owner_and_csrf()
    monkeypatch.setattr(
        main,
        "register_reel",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ValueError("unexpected registration failure")
        ),
    )
    try:
        response = TestClient(main.app, raise_server_exceptions=False).post(
            "/api/reels", json={"url": VALID_URL}
        )
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 500
    assert response.status_code != 422
    assert response.text != '{"error":{"code":"invalid_request","message":"Invalid reel request"}}'


def test_public_reel_creation_treats_missing_outbound_configuration_as_unconfirmed(monkeypatch) -> None:
    client = client_with_owner_and_csrf()
    monkeypatch.setattr(main, "register_reel", lambda *_args, **_kwargs: registered_reel())
    monkeypatch.setattr(
        main,
        "load_dispatch_settings",
        lambda: (_ for _ in ()).throw(main.ReelDispatchConfigurationError("outbound secret")),
    )
    try:
        response = client.post("/api/reels", json={"url": VALID_URL})
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 201
    assert response.json()["dispatch"] == {"state": "unconfirmed"}
    assert "outbound secret" not in response.text


def test_public_reel_creation_never_requires_the_inbound_machine_configuration(monkeypatch) -> None:
    client = client_with_owner_and_csrf()
    monkeypatch.setattr(main, "register_reel", lambda *_args, **_kwargs: registered_reel())
    monkeypatch.setattr(
        main,
        "load_dispatch_settings",
        lambda: reel_dispatch.WebToN8nDispatchSettings("outbound-key", reel_dispatch.DISPATCH_URL),
    )
    monkeypatch.setattr(
        internal_ingestion,
        "load_settings",
        lambda: pytest.fail("public endpoint must not load the inbound machine configuration"),
    )

    async def fake_dispatch(reel, settings):
        return reel_dispatch.DispatchState.ACCEPTED

    monkeypatch.setattr(main, "dispatch_reel", fake_dispatch)
    try:
        response = client.post("/api/reels", json={"url": VALID_URL})
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 201
    assert response.json()["dispatch"] == {"state": "accepted"}
