from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from authlib.jose import JsonWebKey, jwt

from app.auth import oidc
from app.auth.oidc import (
    GOOGLE_DISCOVERY_URL,
    GOOGLE_ISSUER,
    GoogleOIDCAdapter,
    OIDCValidationError,
    build_pkce_challenge,
    generate_pkce_verifier,
    validate_google_claims,
)


def valid_claims(**overrides: object) -> dict[str, object]:
    claims: dict[str, object] = {
        "iss": GOOGLE_ISSUER,
        "aud": "client-id",
        "exp": (datetime.now(UTC) + timedelta(minutes=5)).timestamp(),
        "nonce": "expected-nonce",
        "sub": "google-subject",
        "email": "owner@example.com",
        "email_verified": True,
    }
    claims.update(overrides)
    return claims


def test_pkce_verifier_is_rfc7636_compatible_and_s256_challenge_is_stable() -> None:
    verifier = generate_pkce_verifier()

    assert 43 <= len(verifier) <= 128
    assert all(character.isalnum() or character in "-._~" for character in verifier)
    assert build_pkce_challenge("a" * 43) == "ZtNPunH49FD35FWYhT5Tv8I7vRKQJ8uxMaL0_9eHjNA"


def test_authorization_url_uses_fixed_google_contract_and_pkce() -> None:
    adapter = GoogleOIDCAdapter("client-id", "client-secret", "https://app.example/auth/callback")

    authorization_url = adapter.authorization_url(
        state="state-value", nonce="nonce-value", pkce_verifier="a" * 43
    )

    assert GOOGLE_DISCOVERY_URL == "https://accounts.google.com/.well-known/openid-configuration"
    assert authorization_url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "client_id=client-id" in authorization_url
    assert "redirect_uri=https%3A%2F%2Fapp.example%2Fauth%2Fcallback" in authorization_url
    assert "response_type=code" in authorization_url
    assert "scope=openid+email" in authorization_url
    assert "state=state-value" in authorization_url
    assert "nonce=nonce-value" in authorization_url
    assert "code_challenge_method=S256" in authorization_url
    assert "code_challenge=ZtNPunH49FD35FWYhT5Tv8I7vRKQJ8uxMaL0_9eHjNA" in authorization_url


@pytest.mark.parametrize(
    "claims",
    [
        valid_claims(iss="https://issuer.example"),
        valid_claims(aud="different-client"),
        valid_claims(aud=["client-id", "other-client"]),
        valid_claims(aud=["client-id", "other-client"], azp="other-client"),
        valid_claims(azp="other-client"),
        valid_claims(exp="tomorrow"),
        valid_claims(exp=(datetime.now(UTC) - timedelta(seconds=1)).timestamp()),
        valid_claims(nonce="other-nonce"),
        valid_claims(sub=""),
        valid_claims(email=""),
        valid_claims(email_verified="true"),
        valid_claims(email_verified=1),
        valid_claims(email_verified=False),
    ],
)
def test_google_claim_policy_rejects_invalid_application_claims(
    claims: dict[str, object],
) -> None:
    with pytest.raises(OIDCValidationError):
        validate_google_claims(claims, client_id="client-id", expected_nonce="expected-nonce")


def test_google_claim_policy_returns_only_validated_identity() -> None:
    identity = validate_google_claims(
        valid_claims(aud=["client-id", "other-client"], azp="client-id"),
        client_id="client-id",
        expected_nonce="expected-nonce",
    )

    assert identity.provider_issuer == GOOGLE_ISSUER
    assert identity.provider_subject == "google-subject"
    assert identity.email == "owner@example.com"
    assert identity.email_verified is True
    assert set(identity.__dict__) == {
        "provider_issuer",
        "provider_subject",
        "email",
        "email_verified",
    }


def test_exchange_uses_exact_pkce_verifier_and_jwks_signature_validation(monkeypatch) -> None:
    signing_key = JsonWebKey.generate_key("RSA", 2048, is_private=True)
    token = jwt.encode(
        {"alg": "RS256"},
        valid_claims(),
        signing_key,
    ).decode("ascii")
    fetch_calls: list[dict[str, object]] = []

    class FakeOAuth2Client:
        def __init__(self, **_: str) -> None:
            pass

        def __enter__(self) -> FakeOAuth2Client:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def fetch_token(self, endpoint: str, **kwargs: object) -> dict[str, str]:
            fetch_calls.append({"endpoint": endpoint, **kwargs})
            return {"id_token": token, "access_token": "transient-only"}

    adapter = GoogleOIDCAdapter("client-id", "client-secret", "https://app.example/auth/callback")
    monkeypatch.setattr(oidc, "OAuth2Client", FakeOAuth2Client)
    monkeypatch.setattr(adapter, "_load_metadata", lambda: {"token_endpoint": "https://token.example", "jwks_uri": "https://keys.example"})
    monkeypatch.setattr(adapter, "_load_jwks", lambda _: {"keys": [signing_key.as_dict(is_private=False)]})

    identity = adapter.exchange_and_validate(
        code="authorization-code", pkce_verifier="a" * 43, expected_nonce="expected-nonce"
    )

    assert identity.provider_subject == "google-subject"
    assert fetch_calls == [{
        "endpoint": "https://token.example",
        "code": "authorization-code",
        "redirect_uri": "https://app.example/auth/callback",
        "code_verifier": "a" * 43,
    }]


def test_exchange_rejects_an_identity_token_not_signed_by_google_jwks(monkeypatch) -> None:
    signing_key = JsonWebKey.generate_key("RSA", 2048, is_private=True)
    other_key = JsonWebKey.generate_key("RSA", 2048, is_private=True)
    token = jwt.encode({"alg": "RS256"}, valid_claims(), signing_key).decode("ascii")

    class FakeOAuth2Client:
        def __init__(self, **_: str) -> None:
            pass

        def __enter__(self) -> FakeOAuth2Client:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def fetch_token(self, *_: object, **__: object) -> dict[str, str]:
            return {"id_token": token}

    adapter = GoogleOIDCAdapter("client-id", "client-secret", "https://app.example/auth/callback")
    monkeypatch.setattr(oidc, "OAuth2Client", FakeOAuth2Client)
    monkeypatch.setattr(adapter, "_load_metadata", lambda: {"token_endpoint": "https://token.example", "jwks_uri": "https://keys.example"})
    monkeypatch.setattr(adapter, "_load_jwks", lambda _: {"keys": [other_key.as_dict(is_private=False)]})

    with pytest.raises(OIDCValidationError):
        adapter.exchange_and_validate(
            code="authorization-code", pkce_verifier="a" * 43, expected_nonce="expected-nonce"
        )
