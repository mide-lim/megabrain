from __future__ import annotations

import hmac
import secrets

from fastapi import Form, Header, HTTPException, Request
from fastapi.responses import Response

CSRF_COOKIE_NAME = "__Host-csrf_token"
CSRF_TOKEN_BYTES = 32


def csrf_token(request: Request) -> tuple[str, bool]:
    existing = request.cookies.get(CSRF_COOKIE_NAME)
    if existing:
        return existing, False
    return secrets.token_urlsafe(CSRF_TOKEN_BYTES), True


def set_csrf_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        CSRF_COOKIE_NAME,
        token,
        secure=True,
        httponly=True,
        samesite="lax",
        path="/",
    )


def _validate_csrf(cookie_token: str | None, presented_token: str | None) -> bool:
    return bool(
        cookie_token
        and presented_token
        and hmac.compare_digest(cookie_token, presented_token)
    )


def require_csrf(
    request: Request,
    csrf_token: str | None = Form(default=None),
) -> None:
    if not _validate_csrf(request.cookies.get(CSRF_COOKIE_NAME), csrf_token):
        raise HTTPException(status_code=403, detail="CSRF token validation failed")


def require_api_csrf(
    request: Request,
    csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
) -> None:
    if not _validate_csrf(request.cookies.get(CSRF_COOKIE_NAME), csrf_token):
        raise HTTPException(status_code=403, detail="CSRF token validation failed")
