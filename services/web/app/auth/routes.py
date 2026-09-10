from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse, Response
from pydantic import BaseModel

from app.auth import repository
from app.auth.config import (
    AuthConfigurationError,
    AuthSettings,
    OIDC_TRANSACTION_COOKIE_NAME,
    OIDC_TRANSACTION_COOKIE_POLICY,
    SESSION_COOKIE_NAME,
    SESSION_COOKIE_POLICY,
    generate_opaque_token,
    sha256_token,
)
from app.auth.dependencies import require_owner_session, resolve_owner_session, session_token_hash
from app.auth.oidc import (
    GoogleOIDCAdapter,
    OIDCDependencyError,
    OIDCValidationError,
    generate_pkce_verifier,
)
from app.csrf import csrf_token, require_csrf, set_csrf_cookie

auth_router = APIRouter()
_CACHE_CONTROL = "no-store, private"


class InvalidReturnPath(ValueError):
    """Raised when a return path is not an unambiguous local pathname."""


class CsrfTokenResponse(BaseModel):
    csrf_token: str


def validate_local_return_path(value: str) -> str:
    if not isinstance(value, str) or not value.startswith("/") or value.startswith("//"):
        raise InvalidReturnPath("return path must be a local pathname")

    if any(character in value for character in ("\\", "%", "?", "#", ":")) or any(
        ord(character) < 32 or ord(character) == 127 for character in value
    ):
        raise InvalidReturnPath("return path must be an unambiguous local pathname")

    return value


def load_auth_settings() -> AuthSettings:
    return AuthSettings.from_environment()


def build_oidc_adapter(settings: AuthSettings) -> GoogleOIDCAdapter:
    return GoogleOIDCAdapter(
        settings.client_id,
        settings.client_secret,
        f"{settings.public_base_url}/auth/callback",
    )


def _apply_auth_headers(response: Response, *, callback: bool = False) -> Response:
    response.headers["Cache-Control"] = _CACHE_CONTROL
    if callback:
        response.headers["Referrer-Policy"] = "no-referrer"
    return response


def _set_cookie(response: Response, name: str, value: str, policy) -> None:
    response.set_cookie(
        name,
        value,
        max_age=policy.max_age,
        secure=policy.secure,
        httponly=policy.httponly,
        samesite=policy.samesite,
        path=policy.path,
        domain=policy.domain,
    )


def _clear_transaction_cookie(response: Response) -> None:
    response.delete_cookie(
        OIDC_TRANSACTION_COOKIE_NAME,
        secure=OIDC_TRANSACTION_COOKIE_POLICY.secure,
        httponly=OIDC_TRANSACTION_COOKIE_POLICY.httponly,
        samesite=OIDC_TRANSACTION_COOKIE_POLICY.samesite,
        path=OIDC_TRANSACTION_COOKIE_POLICY.path,
        domain=OIDC_TRANSACTION_COOKIE_POLICY.domain,
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        secure=SESSION_COOKIE_POLICY.secure,
        httponly=SESSION_COOKIE_POLICY.httponly,
        samesite=SESSION_COOKIE_POLICY.samesite,
        path=SESSION_COOKIE_POLICY.path,
        domain=SESSION_COOKIE_POLICY.domain,
    )


def _session_response(payload: dict, status_code: int) -> Response:
    response = JSONResponse(payload, status_code=status_code)
    _apply_auth_headers(response)
    response.headers["Vary"] = "Cookie"
    return response


def _error_response(status_code: int, body: str, *, clear_transaction: bool = False) -> Response:
    response = PlainTextResponse(body, status_code=status_code)
    _apply_auth_headers(response, callback=True)
    if clear_transaction:
        _clear_transaction_cookie(response)
    return response


@auth_router.get("/auth/login")
def login(return_to: str | None = Query(default=None)) -> Response:
    try:
        settings = load_auth_settings()
        return_path = validate_local_return_path(return_to if return_to is not None else "/")
        transaction_id = generate_opaque_token()
        state = generate_opaque_token()
        nonce = generate_opaque_token()
        pkce_verifier = generate_pkce_verifier()
        repository.create_auth_transaction(
            transaction_hash=sha256_token(transaction_id),
            state_hash=sha256_token(state),
            nonce=nonce,
            pkce_verifier=pkce_verifier,
            return_path=return_path,
        )
        authorization_url = build_oidc_adapter(settings).authorization_url(
            state=state,
            nonce=nonce,
            pkce_verifier=pkce_verifier,
        )
    except InvalidReturnPath:
        response = PlainTextResponse("Invalid authentication request", status_code=400)
        return _apply_auth_headers(response)
    except Exception:  # Do not disclose auth configuration or provider setup details.
        response = PlainTextResponse("Authentication temporarily unavailable", status_code=503)
        return _apply_auth_headers(response)

    response = RedirectResponse(authorization_url, status_code=303)
    _apply_auth_headers(response)
    _set_cookie(
        response,
        OIDC_TRANSACTION_COOKIE_NAME,
        transaction_id,
        OIDC_TRANSACTION_COOKIE_POLICY,
    )
    return response


@auth_router.get("/auth/callback")
def callback(
    request: Request,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> Response:
    has_code = bool(code)
    has_error = bool(error)
    has_state = bool(state)
    if (has_code == has_error) or not has_state:
        return _error_response(400, "Invalid authentication transaction")

    transaction_id = request.cookies.get(OIDC_TRANSACTION_COOKIE_NAME)
    if not transaction_id:
        return _error_response(400, "Invalid authentication transaction")
    assert state is not None

    try:
        consumed = repository.consume_auth_transaction(
            sha256_token(transaction_id), sha256_token(state)
        )
    except Exception:
        return _error_response(503, "Authentication temporarily unavailable", clear_transaction=True)
    if consumed is None:
        return _error_response(400, "Invalid authentication transaction", clear_transaction=True)

    if has_error:
        return _error_response(401, "Authentication failed", clear_transaction=True)

    try:
        settings = load_auth_settings()
        assert code is not None
        identity = build_oidc_adapter(settings).exchange_and_validate(
            code=code,
            pkce_verifier=consumed.pkce_verifier,
            expected_nonce=consumed.nonce,
        )
    except OIDCDependencyError:
        return _error_response(503, "Authentication temporarily unavailable", clear_transaction=True)
    except AuthConfigurationError:
        return _error_response(503, "Authentication temporarily unavailable", clear_transaction=True)
    except OIDCValidationError:
        return _error_response(401, "Authentication failed", clear_transaction=True)
    except Exception:
        return _error_response(401, "Authentication failed", clear_transaction=True)

    try:
        user_id = repository.resolve_or_bootstrap_owner(identity, settings.owner_email)
    except repository.OwnerAuthorizationError:
        return _error_response(403, "Authentication denied", clear_transaction=True)
    except Exception:
        return _error_response(503, "Authentication temporarily unavailable", clear_transaction=True)

    try:
        session_token = generate_opaque_token()
        repository.create_session(user_id=user_id, token_hash=sha256_token(session_token))
    except Exception:
        return _error_response(503, "Authentication temporarily unavailable", clear_transaction=True)

    response = RedirectResponse(consumed.return_path, status_code=303)
    _apply_auth_headers(response, callback=True)
    _clear_transaction_cookie(response)
    _set_cookie(response, SESSION_COOKIE_NAME, session_token, SESSION_COOKIE_POLICY)
    return response


@auth_router.get("/api/auth/session")
def session(request: Request) -> Response:
    identity = resolve_owner_session(request)
    if identity is None:
        return _session_response({"authenticated": False}, 401)
    return _session_response(
        {
            "authenticated": True,
            "user": {"id": identity.user_id, "email": identity.email},
        },
        200,
    )


@auth_router.get("/api/auth/csrf", response_model=CsrfTokenResponse)
def api_csrf(request: Request, _owner=Depends(require_owner_session)) -> Response:
    token, should_set_cookie = csrf_token(request)
    response = JSONResponse({"csrf_token": token})
    _apply_auth_headers(response)
    response.headers["Vary"] = "Cookie"
    if should_set_cookie:
        set_csrf_cookie(response, token)
    return response


@auth_router.post("/auth/logout")
def logout(request: Request, _csrf: None = Depends(require_csrf)) -> Response:
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    if raw_token:
        try:
            token_hash = session_token_hash(raw_token)
        except UnicodeEncodeError:
            token_hash = None
        if token_hash is not None:
            try:
                repository.revoke_session(token_hash)
            except Exception:
                response = PlainTextResponse("Authentication temporarily unavailable", status_code=503)
                _apply_auth_headers(response)
                _clear_session_cookie(response)
                return response

    response = RedirectResponse("/", status_code=303)
    _apply_auth_headers(response)
    _clear_session_cookie(response)
    return response
