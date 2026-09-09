from __future__ import annotations

import hmac
import secrets

from fastapi import Form, HTTPException, Request
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


def require_csrf(
    request: Request,
    csrf_token: str | None = Form(default=None),
) -> None:
    cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
    valid = bool(
        cookie_token
        and csrf_token
        and hmac.compare_digest(cookie_token, csrf_token)
    )
    if not valid:
        raise HTTPException(status_code=403, detail="CSRF token validation failed")
