from __future__ import annotations

from fastapi import HTTPException, Request, status

from app.auth import repository
from app.auth.config import SESSION_COOKIE_NAME, sha256_token


def session_token_hash(raw_token: str | None) -> bytes | None:
    """Return a hash for a syntactically valid opaque session token only."""
    if not raw_token or any(not (character.isalnum() or character in "-_") for character in raw_token):
        return None
    try:
        return sha256_token(raw_token)
    except UnicodeEncodeError:
        return None


def resolve_owner_session(request: Request) -> repository.SessionIdentity | None:
    """Resolve the current opaque browser session without exposing its token."""
    token_hash = session_token_hash(request.cookies.get(SESSION_COOKIE_NAME))
    if token_hash is None:
        return None
    try:
        return repository.resolve_session(token_hash)
    except Exception:
        return None


def require_owner_session(request: Request) -> repository.SessionIdentity:
    """Require the active owner session for a FastAPI data endpoint."""
    identity = resolve_owner_session(request)
    if identity is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return identity
