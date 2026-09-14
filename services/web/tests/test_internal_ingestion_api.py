from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient

from app import internal_ingestion
from app.auth.dependencies import require_owner_session
from app.csrf import require_api_csrf
from app.main import app
from app import main as main_module
from app.reel_ingestion import RegisteredReel


def registered_reel(**overrides) -> RegisteredReel:
    values = {
        "id": 42,
        "shortcode": "abc_123",
        "original_url": "https://www.instagram.com/reel/abc_123/",
        "source": "instagram",
        "status": "received",
        "telegram_chat_id": -1001234567890,
        "telegram_user_id": 123456789,
        "telegram_message_id": 987,
        "raw_message": "https://www.instagram.com/reel/abc_123/",
        "received_at": datetime(2026, 9, 14, tzinfo=UTC),
        "created": True,
    }
    values.update(overrides)
    return RegisteredReel(**values)


def settings() -> internal_ingestion.InternalIngestionSettings:
    return internal_ingestion.InternalIngestionSettings(
        n8n_to_web_ingestion_key="test-inbound-key",
        web_to_n8n_dispatch_key="test-outbound-key",
        web_to_n8n_dispatch_url=(
            "http://n8n:5678/webhook/megabrain-internal-dispatch"
        ),
    )


def valid_payload() -> dict:
    return {
        "url": "https://www.instagram.com/reel/abc_123/",
        "telegram": {
            "chat_id": -1001234567890,
            "user_id": 123456789,
            "message_id": 987,
            "raw_message": "https://www.instagram.com/reel/abc_123/",
        },
    }


async def accepted_dispatch(reel_id, config) -> internal_ingestion.DispatchState:
    return internal_ingestion.DispatchState.ACCEPTED


def configure_happy_path(monkeypatch) -> None:
    monkeypatch.setattr(internal_ingestion, "load_settings", settings)
    monkeypatch.setattr(
        internal_ingestion,
        "register_reel",
        lambda raw_url, telegram_metadata: registered_reel(),
    )
    monkeypatch.setattr(
        internal_ingestion,
        "request_internal_dispatch",
        accepted_dispatch,
    )


def test_new_reel_returns_created_after_accepted_dispatch(monkeypatch) -> None:
    configure_happy_path(monkeypatch)

    response = TestClient(app).post(
        "/internal/reels",
        headers={"X-MegaBrain-Key": "test-inbound-key"},
        json=valid_payload(),
    )

    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "reel": {
            "id": 42,
            "shortcode": "abc_123",
            "original_url": "https://www.instagram.com/reel/abc_123/",
            "status": "received",
            "created": True,
        },
        "dispatch": {"state": "accepted"},
    }


def test_missing_and_wrong_keys_have_the_same_unauthorized_response(monkeypatch) -> None:
    configure_happy_path(monkeypatch)
    client = TestClient(app)

    missing = client.post("/internal/reels", json=valid_payload())
    wrong = client.post(
        "/internal/reels",
        headers={"X-MegaBrain-Key": "wrong-key"},
        json=valid_payload(),
    )

    assert missing.status_code == wrong.status_code == 401
    assert missing.json() == wrong.json() == {
        "error": {"code": "unauthorized", "message": "Unauthorized"}
    }


@pytest.mark.parametrize(
    "body",
    [
        b"{",
        b'{"url":"https://instagram.com/reel/abc_123","extra":true}',
        b'{"url":"https://instagram.com/reel/abc_123","telegram":{}}',
        b'{"url":"https://instagram.com/reel/abc_123","telegram":{"chat_id":true,"user_id":2,"message_id":3,"raw_message":"x"}}',
    ],
)
def test_invalid_local_request_contract_returns_bounded_422(monkeypatch, body: bytes) -> None:
    configure_happy_path(monkeypatch)

    response = TestClient(app).post(
        "/internal/reels",
        headers={
            "X-MegaBrain-Key": "test-inbound-key",
            "Content-Type": "application/json",
        },
        content=body,
    )

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "invalid_request",
            "message": "Invalid ingestion request",
        }
    }


def test_invalid_reel_url_returns_bounded_422(monkeypatch) -> None:
    configure_happy_path(monkeypatch)
    monkeypatch.setattr(
        internal_ingestion,
        "register_reel",
        lambda raw_url, telegram_metadata: (_ for _ in ()).throw(
            internal_ingestion.InvalidReelUrl("invalid URL")
        ),
    )

    response = TestClient(app).post(
        "/internal/reels",
        headers={"X-MegaBrain-Key": "test-inbound-key"},
        json=valid_payload(),
    )

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "invalid_request",
            "message": "Invalid ingestion request",
        }
    }


@pytest.mark.parametrize(
    ("status", "expected_dispatch"),
    [
        ("received", "accepted"),
        ("download_failed", "accepted"),
        ("downloading", "not_required"),
        ("downloaded", "not_required"),
    ],
)
def test_existing_reel_uses_persisted_status_for_dispatch_eligibility(
    monkeypatch, status: str, expected_dispatch: str
) -> None:
    calls: list[int] = []
    monkeypatch.setattr(internal_ingestion, "load_settings", settings)
    monkeypatch.setattr(
        internal_ingestion,
        "register_reel",
        lambda raw_url, telegram_metadata: registered_reel(status=status, created=False),
    )
    async def fake_dispatch(reel_id, config) -> internal_ingestion.DispatchState:
        calls.append(reel_id)
        return internal_ingestion.DispatchState.ACCEPTED

    monkeypatch.setattr(
        internal_ingestion,
        "request_internal_dispatch",
        fake_dispatch,
    )

    response = TestClient(app).post(
        "/internal/reels",
        headers={"X-MegaBrain-Key": "test-inbound-key"},
        json=valid_payload(),
    )

    assert response.status_code == 200
    assert response.json()["reel"] == {
        "id": 42,
        "shortcode": "abc_123",
        "original_url": "https://www.instagram.com/reel/abc_123/",
        "status": status,
        "created": False,
    }
    assert response.json()["dispatch"] == {"state": expected_dispatch}
    assert calls == ([42] if expected_dispatch == "accepted" else [])


def test_unexpected_persisted_status_returns_bounded_503_without_dispatch(monkeypatch) -> None:
    dispatch_calls: list[int] = []
    registrations: list[tuple[str, object]] = []
    monkeypatch.setattr(internal_ingestion, "load_settings", settings)

    def fake_register_reel(raw_url, telegram_metadata) -> RegisteredReel:
        registrations.append((raw_url, telegram_metadata))
        return registered_reel(status="unexpected_state", created=False)

    async def fake_dispatch(reel_id, config) -> internal_ingestion.DispatchState:
        dispatch_calls.append(reel_id)
        return internal_ingestion.DispatchState.ACCEPTED

    monkeypatch.setattr(internal_ingestion, "register_reel", fake_register_reel)
    monkeypatch.setattr(internal_ingestion, "request_internal_dispatch", fake_dispatch)

    response = TestClient(app).post(
        "/internal/reels",
        headers={"X-MegaBrain-Key": "test-inbound-key"},
        json=valid_payload(),
    )

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "internal_ingestion_unavailable",
            "message": "Internal ingestion temporarily unavailable",
        }
    }
    assert "unexpected_state" not in response.text
    assert dispatch_calls == []
    assert len(registrations) == 1


def test_durable_registration_returns_unconfirmed_when_dispatch_is_uncertain(monkeypatch) -> None:
    configure_happy_path(monkeypatch)
    async def unconfirmed_dispatch(reel_id, config) -> internal_ingestion.DispatchState:
        return internal_ingestion.DispatchState.UNCONFIRMED

    monkeypatch.setattr(
        internal_ingestion,
        "request_internal_dispatch",
        unconfirmed_dispatch,
    )

    response = TestClient(app).post(
        "/internal/reels",
        headers={"X-MegaBrain-Key": "test-inbound-key"},
        json=valid_payload(),
    )

    assert response.status_code == 201
    assert response.json()["dispatch"] == {"state": "unconfirmed"}


def test_unconfirmed_dispatch_response_does_not_leak_raw_message_or_upstream_body(
    monkeypatch,
) -> None:
    monkeypatch.setattr(internal_ingestion, "load_settings", settings)
    monkeypatch.setattr(
        internal_ingestion,
        "register_reel",
        lambda raw_url, telegram_metadata: registered_reel(
            raw_message="private Telegram message"
        ),
    )
    class FakeAsyncClient:
        def __init__(self, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            return None

        async def post(self, *args, **kwargs):
            return httpx.Response(500, json={"detail": "secret upstream response"})

    monkeypatch.setattr(internal_ingestion.httpx, "AsyncClient", FakeAsyncClient)

    response = TestClient(app).post(
        "/internal/reels",
        headers={"X-MegaBrain-Key": "test-inbound-key"},
        json=valid_payload(),
    )

    assert response.status_code == 201
    assert response.json()["dispatch"] == {"state": "unconfirmed"}
    assert "private Telegram message" not in response.text
    assert "secret upstream response" not in response.text


@pytest.mark.parametrize(
    "outcome",
    [
        httpx.ConnectError("secret-upstream-url"),
        httpx.ReadTimeout("secret-upstream-body"),
        httpx.Response(500, json={"detail": "secret-upstream-body"}),
        httpx.Response(202, content=b"not-json"),
        httpx.Response(202, json={"accepted": False, "reel_id": 42}),
        httpx.Response(202, json={"accepted": True, "reel_id": 43}),
    ],
)
def test_dispatch_confirmation_failures_are_unconfirmed_without_upstream_leak(
    monkeypatch, outcome
) -> None:
    config = settings()

    class FakeAsyncClient:
        def __init__(self, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            return None

        async def post(self, *args, **kwargs):
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    monkeypatch.setattr(internal_ingestion.httpx, "AsyncClient", FakeAsyncClient)

    assert asyncio.run(internal_ingestion.request_internal_dispatch(42, config)) == (
        internal_ingestion.DispatchState.UNCONFIRMED
    )


def test_dispatch_uses_async_client_with_exact_internal_request_contract(monkeypatch) -> None:
    clients = []

    class FakeAsyncClient:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs
            self.calls = []
            clients.append(self)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            return None

        async def post(self, url, **kwargs):
            self.calls.append((url, kwargs))
            return httpx.Response(202, json={"accepted": True, "reel_id": 42})

    monkeypatch.setattr(internal_ingestion.httpx, "AsyncClient", FakeAsyncClient)

    assert asyncio.run(internal_ingestion.request_internal_dispatch(42, settings())) == (
        internal_ingestion.DispatchState.ACCEPTED
    )
    assert len(clients) == 1
    assert clients[0].kwargs["timeout"] == httpx.Timeout(5.0, connect=1.0)
    assert clients[0].kwargs["follow_redirects"] is False
    assert clients[0].kwargs["trust_env"] is False
    assert clients[0].calls == [
        (
            "http://n8n:5678/webhook/megabrain-internal-dispatch",
            {
                "headers": {"X-MegaBrain-Key": "test-outbound-key"},
                "json": {"reel_id": 42},
            },
        )
    ]


@pytest.mark.parametrize(
    ("exception", "expected_status", "expected_code"),
    [
        (internal_ingestion.ReelIdentityConflict("conflict"), 409, "reel_identity_conflict"),
        (
            internal_ingestion.ReelRegistrationUnavailable("secret database detail"),
            503,
            "registration_unavailable",
        ),
    ],
)
def test_registration_errors_are_bounded(monkeypatch, exception, expected_status, expected_code) -> None:
    monkeypatch.setattr(internal_ingestion, "load_settings", settings)
    monkeypatch.setattr(
        internal_ingestion,
        "register_reel",
        lambda raw_url, telegram_metadata: (_ for _ in ()).throw(exception),
    )

    response = TestClient(app).post(
        "/internal/reels",
        headers={"X-MegaBrain-Key": "test-inbound-key"},
        json=valid_payload(),
    )

    assert response.status_code == expected_status
    assert response.json()["error"]["code"] == expected_code
    assert "secret database detail" not in response.text


def test_unavailable_internal_configuration_returns_bounded_503(monkeypatch) -> None:
    monkeypatch.setattr(
        internal_ingestion,
        "load_settings",
        lambda: (_ for _ in ()).throw(
            internal_ingestion.InternalIngestionConfigurationError("secret config")
        ),
    )

    response = TestClient(app).post("/internal/reels", json=valid_payload())

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "internal_ingestion_unavailable",
            "message": "Internal ingestion temporarily unavailable",
        }
    }
    assert "secret config" not in response.text


def test_internal_settings_validate_and_redact_keys() -> None:
    config = internal_ingestion.InternalIngestionSettings.from_environment(
        {
            "N8N_TO_WEB_INGESTION_KEY": "inbound-secret",
            "WEB_TO_N8N_DISPATCH_KEY": "outbound-secret",
            "WEB_TO_N8N_DISPATCH_URL": (
                "http://n8n:5678/webhook/megabrain-internal-dispatch"
            ),
        }
    )

    assert "inbound-secret" not in repr(config)
    assert "outbound-secret" not in repr(config)
    with pytest.raises(internal_ingestion.InternalIngestionConfigurationError):
        internal_ingestion.InternalIngestionSettings.from_environment(
            {
                "N8N_TO_WEB_INGESTION_KEY": "inbound-secret",
                "WEB_TO_N8N_DISPATCH_KEY": "outbound-secret",
                "WEB_TO_N8N_DISPATCH_URL": "https://n8n:5678/webhook/megabrain-internal-dispatch",
            }
        )


def test_existing_api_validation_envelope_is_not_changed_by_internal_parser(monkeypatch) -> None:
    monkeypatch.setattr(main_module, "reel_exists", lambda reel_id: True)
    app.dependency_overrides[require_owner_session] = lambda: object()
    app.dependency_overrides[require_api_csrf] = lambda: None
    try:
        response = TestClient(app).post(
            "/api/reels/42/categories",
            json={"category_id": "not-an-integer"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)


def test_public_documentation_routes_remain_disabled() -> None:
    for path in ("/docs", "/redoc", "/openapi.json"):
        response = TestClient(app).get(path)

        assert response.status_code == 404


def test_internal_openapi_documents_only_the_machine_header_contract() -> None:
    schema = app.openapi()
    operation = schema["paths"]["/internal/reels"]["post"]

    assert schema["components"]["securitySchemes"]["N8nIngestionKey"] == {
        "type": "apiKey",
        "in": "header",
        "name": "X-MegaBrain-Key",
        "description": "Machine credential for n8n Telegram ingestion only.",
    }
    assert operation["security"] == [{"N8nIngestionKey": []}]
    assert operation["requestBody"]["required"] is True
