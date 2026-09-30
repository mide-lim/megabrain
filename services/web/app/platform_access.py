from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import quote, urlsplit, urlunsplit

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse, RedirectResponse, Response

from app.auth.dependencies import require_owner_session
from app.auth.repository import SessionIdentity
from app.csrf import require_csrf


PAPERCLIP_HANDOFF_TTL_SECONDS = 90
PAPERCLIP_HANDOFF_ISSUER = "megabrain"
PAPERCLIP_HANDOFF_AUDIENCE = "paperclip-cockpit"
PAPERCLIP_HANDOFF_EXCHANGE_PATH = "/api/auth/megabrain-handoff/exchange"
_PAPERCLIP_HANDOFF_DOMAIN = b"megabrain:paperclip-handoff:v1"
_CACHE_CONTROL = "no-store, private"


class PaperclipHandoffConfigurationError(RuntimeError):
    """Raised when the Paperclip handoff issuer is not safely configured."""


@dataclass(frozen=True)
class PaperclipHandoffSettings:
    public_origin: str
    shared_secret: bytes

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str] | None = None
    ) -> "PaperclipHandoffSettings":
        environment = os.environ if environment is None else environment
        raw_origin = (environment.get("PAPERCLIP_COCKPIT_PUBLIC_URL") or "").strip()
        raw_secret = environment.get("PAPERCLIP_HANDOFF_SECRET") or ""

        if not raw_origin:
            raise PaperclipHandoffConfigurationError(
                "PAPERCLIP_COCKPIT_PUBLIC_URL is required"
            )
        if not raw_secret:
            raise PaperclipHandoffConfigurationError(
                "PAPERCLIP_HANDOFF_SECRET is required"
            )

        public_origin = normalize_https_origin(raw_origin)
        try:
            secret = raw_secret.encode("utf-8")
        except UnicodeEncodeError as error:
            raise PaperclipHandoffConfigurationError(
                "PAPERCLIP_HANDOFF_SECRET is invalid"
            ) from error

        if len(secret) < 32:
            raise PaperclipHandoffConfigurationError(
                "PAPERCLIP_HANDOFF_SECRET must be at least 32 bytes"
            )

        return cls(public_origin=public_origin, shared_secret=secret)


def normalize_https_origin(value: str) -> str:
    parsed = urlsplit(value.strip())
    try:
        valid_port = parsed.port is None or 0 < parsed.port <= 65535
    except ValueError:
        valid_port = False

    if not (
        parsed.scheme == "https"
        and parsed.hostname
        and parsed.username is None
        and parsed.password is None
        and parsed.path in ("", "/")
        and not parsed.query
        and not parsed.fragment
        and not parsed.netloc.endswith(":")
        and "\\" not in value
        and valid_port
    ):
        raise PaperclipHandoffConfigurationError(
            "PAPERCLIP_COCKPIT_PUBLIC_URL must be an HTTPS origin"
        )

    return urlunsplit(("https", parsed.netloc, "", "", ""))


def _b64url(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def _canonical_json(payload: Mapping[str, object]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")


def _signing_key(shared_secret: bytes) -> bytes:
    return hmac.new(
        shared_secret,
        _PAPERCLIP_HANDOFF_DOMAIN,
        hashlib.sha256,
    ).digest()


def issue_paperclip_handoff_ticket(
    owner: SessionIdentity,
    settings: PaperclipHandoffSettings,
    *,
    issued_at: int | None = None,
    nonce: str | None = None,
) -> str:
    now = int(time.time()) if issued_at is None else int(issued_at)
    ticket_nonce = nonce or secrets.token_urlsafe(24)

    header = {
        "alg": "HS256",
        "typ": "MB-PC-HANDOFF",
        "v": 1,
    }
    payload = {
        "aud": PAPERCLIP_HANDOFF_AUDIENCE,
        "email": owner.email.strip().casefold(),
        "exp": now + PAPERCLIP_HANDOFF_TTL_SECONDS,
        "iat": now,
        "iss": PAPERCLIP_HANDOFF_ISSUER,
        "jti": ticket_nonce,
        "origin": settings.public_origin,
        "path": "/",
        "sub": str(owner.user_id),
        "v": 1,
    }

    encoded_header = _b64url(_canonical_json(header))
    encoded_payload = _b64url(_canonical_json(payload))
    signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
    signature = hmac.new(
        _signing_key(settings.shared_secret),
        signing_input,
        hashlib.sha256,
    ).digest()

    return f"{encoded_header}.{encoded_payload}.{_b64url(signature)}"


def build_paperclip_exchange_url(
    settings: PaperclipHandoffSettings, ticket: str
) -> str:
    return (
        f"{settings.public_origin}{PAPERCLIP_HANDOFF_EXCHANGE_PATH}"
        f"?ticket={quote(ticket, safe='')}"
    )


def load_handoff_settings() -> PaperclipHandoffSettings:
    return PaperclipHandoffSettings.from_environment()


def _launch_error() -> Response:
    response = PlainTextResponse(
        "Paperclip access temporarily unavailable",
        status_code=503,
    )
    response.headers["Cache-Control"] = _CACHE_CONTROL
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


platform_router = APIRouter()


@platform_router.post("/api/platform/paperclip/launch")
def launch_paperclip(
    owner: SessionIdentity = Depends(require_owner_session),
    _csrf: None = Depends(require_csrf),
) -> Response:
    try:
        settings = load_handoff_settings()
        ticket = issue_paperclip_handoff_ticket(owner, settings)
        location = build_paperclip_exchange_url(settings, ticket)
    except PaperclipHandoffConfigurationError:
        return _launch_error()

    response = RedirectResponse(location, status_code=303)
    response.headers["Cache-Control"] = _CACHE_CONTROL
    response.headers["Referrer-Policy"] = "no-referrer"
    return response
