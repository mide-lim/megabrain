from __future__ import annotations

import base64
import hashlib
import hmac
import json
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from app import main
from app.auth import config, dependencies, repository
from app.platform_access import (
    PAPERCLIP_HANDOFF_AUDIENCE,
    PAPERCLIP_HANDOFF_ISSUER,
    PAPERCLIP_HANDOFF_TTL_SECONDS,
    PaperclipHandoffConfigurationError,
    PaperclipHandoffSettings,
    issue_paperclip_handoff_ticket,
)
from app import platform_access


def _decode_part(value: str) -> dict[str, object]:
    padding = "=" * (-len(value) % 4)
    return json.loads(base64.urlsafe_b64decode(value + padding))


def _settings() -> PaperclipHandoffSettings:
    return PaperclipHandoffSettings(
        public_origin="https://paperclip.midelim.tech",
        shared_secret=b"test-only-paperclip-handoff-secret-32-bytes-plus",
    )


def test_handoff_settings_require_https_origin_and_strong_secret() -> None:
    settings = PaperclipHandoffSettings.from_environment(
        {
            "PAPERCLIP_COCKPIT_PUBLIC_URL": "https://paperclip.midelim.tech/",
            "PAPERCLIP_HANDOFF_SECRET": "x" * 32,
        }
    )
    assert settings.public_origin == "https://paperclip.midelim.tech"

    with pytest.raises(PaperclipHandoffConfigurationError):
        PaperclipHandoffSettings.from_environment(
            {
                "PAPERCLIP_COCKPIT_PUBLIC_URL": "http://paperclip.midelim.tech",
                "PAPERCLIP_HANDOFF_SECRET": "x" * 32,
            }
        )

    with pytest.raises(PaperclipHandoffConfigurationError):
        PaperclipHandoffSettings.from_environment(
            {
                "PAPERCLIP_COCKPIT_PUBLIC_URL": "https://paperclip.midelim.tech/path",
                "PAPERCLIP_HANDOFF_SECRET": "x" * 32,
            }
        )

    with pytest.raises(PaperclipHandoffConfigurationError):
        PaperclipHandoffSettings.from_environment(
            {
                "PAPERCLIP_COCKPIT_PUBLIC_URL": "https://paperclip.midelim.tech",
                "PAPERCLIP_HANDOFF_SECRET": "too-short",
            }
        )


def test_ticket_is_short_lived_bound_and_hmac_signed() -> None:
    settings = _settings()
    owner = repository.SessionIdentity(7, "Owner@Example.com")
    ticket = issue_paperclip_handoff_ticket(
        owner,
        settings,
        issued_at=1_700_000_000,
        nonce="fixed-single-use-id",
    )

    parts = ticket.split(".")
    assert len(parts) == 3
    header = _decode_part(parts[0])
    payload = _decode_part(parts[1])

    assert header == {"alg": "HS256", "typ": "MB-PC-HANDOFF", "v": 1}
    assert payload == {
        "aud": PAPERCLIP_HANDOFF_AUDIENCE,
        "email": "owner@example.com",
        "exp": 1_700_000_000 + PAPERCLIP_HANDOFF_TTL_SECONDS,
        "iat": 1_700_000_000,
        "iss": PAPERCLIP_HANDOFF_ISSUER,
        "jti": "fixed-single-use-id",
        "origin": "https://paperclip.midelim.tech",
        "path": "/",
        "sub": "7",
        "v": 1,
    }

    signing_key = hmac.new(
        settings.shared_secret,
        b"megabrain:paperclip-handoff:v1",
        hashlib.sha256,
    ).digest()
    expected_signature = hmac.new(
        signing_key,
        f"{parts[0]}.{parts[1]}".encode("ascii"),
        hashlib.sha256,
    ).digest()
    signature_padding = "=" * (-len(parts[2]) % 4)
    assert hmac.compare_digest(
        base64.urlsafe_b64decode(parts[2] + signature_padding),
        expected_signature,
    )


def test_launch_requires_owner_session_before_issuing_ticket(monkeypatch) -> None:
    monkeypatch.setattr(dependencies.repository, "resolve_session", lambda *_: None)
    monkeypatch.setattr(
        platform_access,
        "load_handoff_settings",
        lambda: pytest.fail("must not load handoff config without an owner session"),
    )
    client = TestClient(main.app, base_url="https://testserver")
    client.cookies.set("__Host-csrf_token", "csrf-value")

    response = client.post(
        "/api/platform/paperclip/launch",
        data={"csrf_token": "csrf-value"},
        follow_redirects=False,
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}


def test_launch_requires_csrf_for_valid_owner(monkeypatch) -> None:
    monkeypatch.setattr(
        dependencies.repository,
        "resolve_session",
        lambda *_: repository.SessionIdentity(7, "owner@example.com"),
    )
    client = TestClient(main.app, base_url="https://testserver")
    client.cookies.set(config.SESSION_COOKIE_NAME, "valid-owner-session")

    response = client.post(
        "/api/platform/paperclip/launch",
        follow_redirects=False,
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "CSRF token validation failed"}


def test_launch_issues_only_paperclip_ticket_and_redirects(monkeypatch) -> None:
    monkeypatch.setattr(
        dependencies.repository,
        "resolve_session",
        lambda *_: repository.SessionIdentity(7, "Owner@Example.com"),
    )
    monkeypatch.setattr(platform_access, "load_handoff_settings", _settings)
    monkeypatch.setattr(platform_access.time, "time", lambda: 1_700_000_000)
    monkeypatch.setattr(
        platform_access.secrets,
        "token_urlsafe",
        lambda _: "fixed-single-use-id",
    )

    client = TestClient(main.app, base_url="https://testserver")
    client.cookies.set(config.SESSION_COOKIE_NAME, "raw-megabrain-owner-session")
    client.cookies.set("__Host-csrf_token", "csrf-value")

    response = client.post(
        "/api/platform/paperclip/launch",
        data={"csrf_token": "csrf-value"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["cache-control"] == "no-store, private"
    assert response.headers["referrer-policy"] == "no-referrer"

    location = response.headers["location"]
    parsed = urlsplit(location)
    assert parsed.scheme == "https"
    assert parsed.netloc == "paperclip.midelim.tech"
    assert parsed.path == "/api/auth/megabrain-handoff/exchange"

    ticket = parse_qs(parsed.query)["ticket"][0]
    payload = _decode_part(ticket.split(".")[1])
    assert payload["sub"] == "7"
    assert payload["email"] == "owner@example.com"
    assert payload["origin"] == "https://paperclip.midelim.tech"
    assert payload["exp"] - payload["iat"] == PAPERCLIP_HANDOFF_TTL_SECONDS
    assert "raw-megabrain-owner-session" not in location


def test_launch_configuration_failure_is_generic_and_non_redirecting(monkeypatch) -> None:
    monkeypatch.setattr(
        dependencies.repository,
        "resolve_session",
        lambda *_: repository.SessionIdentity(7, "owner@example.com"),
    )
    monkeypatch.setattr(
        platform_access,
        "load_handoff_settings",
        lambda: (_ for _ in ()).throw(
            PaperclipHandoffConfigurationError("sensitive-config-detail")
        ),
    )

    client = TestClient(main.app, base_url="https://testserver")
    client.cookies.set(config.SESSION_COOKIE_NAME, "valid-owner-session")
    client.cookies.set("__Host-csrf_token", "csrf-value")

    response = client.post(
        "/api/platform/paperclip/launch",
        data={"csrf_token": "csrf-value"},
        follow_redirects=False,
    )

    assert response.status_code == 503
    assert response.text == "Paperclip access temporarily unavailable"
    assert response.headers["cache-control"] == "no-store, private"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "sensitive-config-detail" not in response.text
