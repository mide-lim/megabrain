from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient

from app import internal_ingestion, reel_dispatch
from app import main as main_module
from app.auth.dependencies import require_owner_session
from app.csrf import require_api_csrf
from app.main import app
from app.reel_ingestion import RegisteredReel


DISPATCH_URL = "http://n8n:5678/webhook/megabrain-internal-dispatch"


def registered_reel(**overrides: object) -> RegisteredReel:
    values = {
        "id": 42,
        "shortcode": "abc_123",
        "original_url": "https://www.instagram.com/reel/abc_123/",
        "source": "instagram",
        "download_status": "received",
        "curation_status": "inbox",
        "transcription_status": "not_requested",
        "telegram_chat_id": -1001234567890,
        "telegram_user_id": 123456789,
        "telegram_message_id": 987,
        "raw_message": "https://www.instagram.com/reel/abc_123/",
        "received_at": datetime(2026, 9, 14, tzinfo=UTC),
        "created": True,
    }
    values.update(overrides)
    return RegisteredReel(**values)


def inbound_settings() -> internal_ingestion.InternalIngestionSettings:
    return internal_ingestion.InternalIngestionSettings("test-inbound-key")


def outbound_settings() -> reel_dispatch.WebToN8nDispatchSettings:
    return reel_dispatch.WebToN8nDispatchSettings("test-outbound-key", DISPATCH_URL)


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


def configure_happy_path(monkeypatch, dispatch_state: str = "accepted") -> None:
    monkeypatch.setattr(internal_ingestion, "load_settings", inbound_settings)
    monkeypatch.setattr(internal_ingestion, "load_dispatch_settings", outbound_settings)
    monkeypatch.setattr(
        internal_ingestion,
        "register_reel",
        lambda raw_url, telegram_metadata: registered_reel(),
    )

    async def fake_dispatch(reel, settings):
        return reel_dispatch.DispatchState(dispatch_state)

    monkeypatch.setattr(internal_ingestion, "dispatch_reel", fake_dispatch)


def test_f33_new_reel_returns_unchanged_created_contract(monkeypatch) -> None:
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
            "download_status": "received",
            "created": True,
        },
        "dispatch": {"state": "accepted"},
    }


def test_f33_machine_credential_rejects_before_domain_work(monkeypatch) -> None:
    configure_happy_path(monkeypatch)
    monkeypatch.setattr(
        internal_ingestion,
        "register_reel",
        lambda *_args, **_kwargs: pytest.fail("invalid machine credential must not register"),
    )
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
def test_f33_invalid_local_contract_remains_bounded(monkeypatch, body: bytes) -> None:
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


def test_f33_invalid_reel_url_returns_bounded_422(monkeypatch) -> None:
    configure_happy_path(monkeypatch)
    monkeypatch.setattr(
        internal_ingestion,
        "register_reel",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
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


def test_f33_constructs_telegram_metadata_and_delegates_dispatch(monkeypatch) -> None:
    configure_happy_path(monkeypatch)
    registrations: list[tuple[str, object]] = []
    monkeypatch.setattr(
        internal_ingestion,
        "register_reel",
        lambda raw_url, telegram_metadata: registrations.append((raw_url, telegram_metadata))
        or registered_reel(),
    )

    response = TestClient(app).post(
        "/internal/reels",
        headers={"X-MegaBrain-Key": "test-inbound-key"},
        json=valid_payload(),
    )

    assert response.status_code == 201
    assert registrations == [
        (
            valid_payload()["url"],
            internal_ingestion.TelegramAdapterMetadata(
                telegram_chat_id=-1001234567890,
                telegram_user_id=123456789,
                telegram_message_id=987,
                raw_message="https://www.instagram.com/reel/abc_123/",
            ),
        )
    ]


@pytest.mark.parametrize(
    ("persisted_status", "expected_dispatch"),
    [
        ("received", "accepted"),
        ("failed", "accepted"),
        ("downloading", "not_required"),
        ("downloaded", "not_required"),
    ],
)
def test_f33_existing_reel_uses_persisted_status_for_dispatch_eligibility(
    monkeypatch, persisted_status: str, expected_dispatch: str
) -> None:
    dispatch_calls: list[int] = []
    monkeypatch.setattr(internal_ingestion, "load_settings", inbound_settings)
    monkeypatch.setattr(
        internal_ingestion, "load_dispatch_settings", outbound_settings
    )
    monkeypatch.setattr(
        internal_ingestion,
        "register_reel",
        lambda *_args, **_kwargs: registered_reel(download_status=persisted_status, created=False),
    )

    async def fake_request_dispatch(reel_id, settings):
        dispatch_calls.append(reel_id)
        return reel_dispatch.DispatchState.ACCEPTED

    monkeypatch.setattr(reel_dispatch, "request_internal_dispatch", fake_request_dispatch)
    monkeypatch.setattr(internal_ingestion, "dispatch_reel", reel_dispatch.dispatch_reel)

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
        "download_status": persisted_status,
        "created": False,
    }
    assert response.json()["dispatch"] == {"state": expected_dispatch}
    assert dispatch_calls == ([42] if expected_dispatch == "accepted" else [])


def test_f33_unknown_status_remains_bounded_without_upstream_dispatch(monkeypatch) -> None:
    configure_happy_path(monkeypatch)
    monkeypatch.setattr(
        internal_ingestion,
        "register_reel",
        lambda *_args, **_kwargs: registered_reel(download_status="unexpected_state"),
    )
    upstream_calls: list[int] = []

    async def fake_request(reel_id, settings):
        upstream_calls.append(reel_id)
        return reel_dispatch.DispatchState.ACCEPTED

    monkeypatch.setattr(reel_dispatch, "request_internal_dispatch", fake_request)
    monkeypatch.setattr(internal_ingestion, "dispatch_reel", reel_dispatch.dispatch_reel)

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
    assert upstream_calls == []
    assert "unexpected_state" not in response.text


@pytest.mark.parametrize(
    ("exception", "status_code", "code"),
    [
        (internal_ingestion.ReelIdentityConflict("private conflict"), 409, "reel_identity_conflict"),
        (internal_ingestion.ReelRegistrationUnavailable("private database detail"), 503, "registration_unavailable"),
    ],
)
def test_f33_registration_errors_remain_bounded(monkeypatch, exception, status_code: int, code: str) -> None:
    configure_happy_path(monkeypatch)
    monkeypatch.setattr(
        internal_ingestion,
        "register_reel",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(exception),
    )

    response = TestClient(app).post(
        "/internal/reels",
        headers={"X-MegaBrain-Key": "test-inbound-key"},
        json=valid_payload(),
    )

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == code
    assert "private" not in response.text


def test_f33_unavailable_internal_configuration_returns_bounded_503(monkeypatch) -> None:
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


def test_f33_dispatch_uncertainty_remains_durable_and_does_not_leak_metadata(monkeypatch) -> None:
    configure_happy_path(monkeypatch, "unconfirmed")
    monkeypatch.setattr(
        internal_ingestion,
        "register_reel",
        lambda *_args, **_kwargs: registered_reel(raw_message="private Telegram message"),
    )

    response = TestClient(app).post(
        "/internal/reels",
        headers={"X-MegaBrain-Key": "test-inbound-key"},
        json=valid_payload(),
    )

    assert response.status_code == 201
    assert response.json()["dispatch"] == {"state": "unconfirmed"}
    assert "private Telegram message" not in response.text


def test_f33_unconfirmed_dispatch_does_not_leak_raw_message_or_upstream_body(
    monkeypatch,
) -> None:
    monkeypatch.setattr(internal_ingestion, "load_settings", inbound_settings)
    monkeypatch.setattr(
        internal_ingestion, "load_dispatch_settings", outbound_settings
    )
    monkeypatch.setattr(
        internal_ingestion,
        "register_reel",
        lambda *_args, **_kwargs: registered_reel(
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

    monkeypatch.setattr(reel_dispatch.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(internal_ingestion, "dispatch_reel", reel_dispatch.dispatch_reel)

    response = TestClient(app).post(
        "/internal/reels",
        headers={"X-MegaBrain-Key": "test-inbound-key"},
        json=valid_payload(),
    )

    assert response.status_code == 201
    assert response.json()["dispatch"] == {"state": "unconfirmed"}
    assert "private Telegram message" not in response.text
    assert "secret upstream response" not in response.text


def test_shared_dispatch_validates_exact_request_and_response_contract(monkeypatch) -> None:
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

    monkeypatch.setattr(reel_dispatch.httpx, "AsyncClient", FakeAsyncClient)

    assert asyncio.run(reel_dispatch.request_internal_dispatch(42, outbound_settings())) == reel_dispatch.DispatchState.ACCEPTED
    assert clients[0].kwargs["timeout"] == httpx.Timeout(5.0, connect=1.0)
    assert clients[0].kwargs["follow_redirects"] is False
    assert clients[0].kwargs["trust_env"] is False
    assert clients[0].calls == [
        (
            DISPATCH_URL,
            {
                "headers": {"X-MegaBrain-Key": "test-outbound-key"},
                "json": {"reel_id": 42},
            },
        )
    ]


@pytest.mark.parametrize(
    "outcome",
    [
        httpx.ConnectError("private upstream"),
        httpx.ReadTimeout("private upstream"),
        httpx.Response(500, json={"detail": "private upstream"}),
        httpx.Response(202, content=b"not-json"),
        httpx.Response(202, json={"accepted": False, "reel_id": 42}),
        httpx.Response(202, json={"accepted": True, "reel_id": 43}),
    ],
)
def test_shared_dispatch_confirmation_failures_are_unconfirmed(monkeypatch, outcome) -> None:
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

    monkeypatch.setattr(reel_dispatch.httpx, "AsyncClient", FakeAsyncClient)

    assert asyncio.run(reel_dispatch.request_internal_dispatch(42, outbound_settings())) == reel_dispatch.DispatchState.UNCONFIRMED


def test_inbound_and_outbound_settings_are_separate_and_redact_keys() -> None:
    inbound = internal_ingestion.InternalIngestionSettings.from_environment(
        {"N8N_TO_WEB_INGESTION_KEY": "inbound-secret"}
    )
    outbound = reel_dispatch.WebToN8nDispatchSettings.from_environment(
        {
            "WEB_TO_N8N_DISPATCH_KEY": "outbound-secret",
            "WEB_TO_N8N_DISPATCH_URL": DISPATCH_URL,
        }
    )

    assert "inbound-secret" not in repr(inbound)
    assert "outbound-secret" not in repr(outbound)
    for invalid_url in (
        "https://n8n:5678/webhook/megabrain-internal-dispatch",
        "http://[",
    ):
        with pytest.raises(reel_dispatch.ReelDispatchConfigurationError):
            reel_dispatch.WebToN8nDispatchSettings.from_environment(
                {
                    "WEB_TO_N8N_DISPATCH_KEY": "outbound-secret",
                    "WEB_TO_N8N_DISPATCH_URL": invalid_url,
                }
            )


def test_internal_openapi_remains_machine_only() -> None:
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


def test_f33_existing_api_validation_envelope_is_not_changed_by_internal_parser(
    monkeypatch,
) -> None:
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


def test_f33_public_documentation_routes_remain_disabled() -> None:
    for path in ("/docs", "/redoc", "/openapi.json"):
        response = TestClient(app).get(path)

        assert response.status_code == 404
