from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Mapping
from urllib.parse import urlencode

import httpx
from authlib.integrations.httpx_client import OAuth2Client
from authlib.jose import JsonWebKey, jwt

GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"
GOOGLE_ISSUER = "https://accounts.google.com"
GOOGLE_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_SCOPES = "openid email"


class OIDCDependencyError(RuntimeError):
    """Raised when Google metadata or keys are unavailable."""


class OIDCValidationError(RuntimeError):
    """Raised when a provider response violates the OIDC contract."""


@dataclass(frozen=True)
class ValidatedIdentity:
    provider_issuer: str
    provider_subject: str
    email: str
    email_verified: bool


def generate_pkce_verifier() -> str:
    """Return a 64-character RFC 7636 unreserved verifier from a CSPRNG."""
    return secrets.token_urlsafe(48).replace("_", ".").replace("-", "~")


def build_pkce_challenge(verifier: str) -> str:
    if not isinstance(verifier, str) or not 43 <= len(verifier) <= 128:
        raise ValueError("PKCE verifier must be 43 to 128 characters")
    if any(not (character.isalnum() or character in "-._~") for character in verifier):
        raise ValueError("PKCE verifier contains invalid characters")
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def validate_google_claims(
    claims: Mapping[str, Any], *, client_id: str, expected_nonce: str
) -> ValidatedIdentity:
    issuer = claims.get("iss")
    if issuer != GOOGLE_ISSUER:
        raise OIDCValidationError("invalid issuer")

    audience = claims.get("aud")
    audiences = [audience] if isinstance(audience, str) else audience
    if (
        not isinstance(audiences, list)
        or not audiences
        or any(not isinstance(value, str) for value in audiences)
        or client_id not in audiences
    ):
        raise OIDCValidationError("invalid audience")

    authorized_party = claims.get("azp")
    if "azp" in claims and authorized_party != client_id:
        raise OIDCValidationError("invalid authorized party")
    if len(audiences) > 1 and authorized_party != client_id:
        raise OIDCValidationError("multiple audiences require matching authorized party")

    expiry = claims.get("exp")
    if isinstance(expiry, bool) or not isinstance(expiry, (int, float)):
        raise OIDCValidationError("invalid expiry")
    if expiry <= datetime.now(UTC).timestamp():
        raise OIDCValidationError("expired identity token")

    nonce = claims.get("nonce")
    if not isinstance(nonce, str) or not hmac.compare_digest(nonce, expected_nonce):
        raise OIDCValidationError("invalid nonce")

    subject = claims.get("sub")
    email = claims.get("email")
    if not isinstance(subject, str) or not subject:
        raise OIDCValidationError("invalid subject")
    if not isinstance(email, str) or not email.strip():
        raise OIDCValidationError("invalid email")
    if claims.get("email_verified") is not True:
        raise OIDCValidationError("unverified email")

    return ValidatedIdentity(
        provider_issuer=GOOGLE_ISSUER,
        provider_subject=subject,
        email=email,
        email_verified=True,
    )


class GoogleOIDCAdapter:
    """Narrow Authlib boundary for the fixed Google OpenID Connect provider."""

    def __init__(self, client_id: str, client_secret: str, redirect_uri: str) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri

    def authorization_url(
        self, *, state: str, nonce: str, pkce_verifier: str
    ) -> str:
        parameters = {
            "client_id": self._client_id,
            "redirect_uri": self._redirect_uri,
            "response_type": "code",
            "scope": GOOGLE_SCOPES,
            "state": state,
            "nonce": nonce,
            "code_challenge": build_pkce_challenge(pkce_verifier),
            "code_challenge_method": "S256",
        }
        return f"{GOOGLE_AUTHORIZATION_ENDPOINT}?{urlencode(parameters)}"

    def exchange_and_validate(
        self, *, code: str, pkce_verifier: str, expected_nonce: str
    ) -> ValidatedIdentity:
        metadata = self._load_metadata()
        try:
            with OAuth2Client(
                client_id=self._client_id,
                client_secret=self._client_secret,
            ) as client:
                token_response = client.fetch_token(
                    metadata["token_endpoint"],
                    code=code,
                    redirect_uri=self._redirect_uri,
                    code_verifier=pkce_verifier,
                )
        except Exception as error:  # Provider exceptions must not cross the boundary.
            raise OIDCValidationError("token exchange failed") from error

        id_token = token_response.get("id_token") if isinstance(token_response, Mapping) else None
        if not isinstance(id_token, str) or not id_token:
            raise OIDCValidationError("missing identity token")

        jwks = self._load_jwks(metadata["jwks_uri"])
        try:
            key_set = JsonWebKey.import_key_set(jwks)
            decoded = jwt.decode(id_token, key=key_set)
            if decoded.header.get("alg") != "RS256":
                raise OIDCValidationError("unexpected signing algorithm")
            decoded.validate()
        except OIDCValidationError:
            raise
        except Exception as error:  # Authlib parsing and signature errors are untrusted input.
            raise OIDCValidationError("identity token validation failed") from error

        return validate_google_claims(
            decoded, client_id=self._client_id, expected_nonce=expected_nonce
        )

    def _load_metadata(self) -> Mapping[str, str]:
        try:
            response = httpx.get(GOOGLE_DISCOVERY_URL, timeout=5.0)
            response.raise_for_status()
            metadata = response.json()
        except Exception as error:
            raise OIDCDependencyError("Google discovery metadata unavailable") from error
        if (
            not isinstance(metadata, Mapping)
            or metadata.get("issuer") != GOOGLE_ISSUER
            or not isinstance(metadata.get("token_endpoint"), str)
            or not isinstance(metadata.get("jwks_uri"), str)
        ):
            raise OIDCDependencyError("invalid Google discovery metadata")
        return {"token_endpoint": metadata["token_endpoint"], "jwks_uri": metadata["jwks_uri"]}

    def _load_jwks(self, jwks_uri: str) -> Mapping[str, Any]:
        try:
            response = httpx.get(jwks_uri, timeout=5.0)
            response.raise_for_status()
            jwks = response.json()
        except Exception as error:
            raise OIDCDependencyError("Google signing keys unavailable") from error
        if not isinstance(jwks, Mapping) or not isinstance(jwks.get("keys"), list):
            raise OIDCDependencyError("invalid Google signing keys")
        return jwks
