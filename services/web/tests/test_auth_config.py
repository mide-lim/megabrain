from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from app.auth import config
from app.auth.config import AuthConfigurationError, AuthSettings


VALID_ENVIRONMENT = {
    "GOOGLE_OIDC_CLIENT_ID": "client-id",
    "GOOGLE_OIDC_CLIENT_SECRET": "client-secret",
    "AUTH_OWNER_EMAIL": "owner@example.com",
    "AUTH_PUBLIC_BASE_URL": "https://megabrain.example",
    "AUTH_SESSION_TTL_SECONDS": "604800",
}


def test_auth_settings_require_every_authentication_environment_value() -> None:
    with pytest.raises(AuthConfigurationError) as error:
        AuthSettings.from_environment({})

    assert str(error.value) == (
        "Missing required authentication configuration: GOOGLE_OIDC_CLIENT_ID, "
        "GOOGLE_OIDC_CLIENT_SECRET, AUTH_OWNER_EMAIL, AUTH_PUBLIC_BASE_URL, "
        "AUTH_SESSION_TTL_SECONDS"
    )


def test_auth_settings_normalize_owner_email_and_hide_client_secret() -> None:
    settings = AuthSettings.from_environment(
        {
            "GOOGLE_OIDC_CLIENT_ID": "client-id",
            "GOOGLE_OIDC_CLIENT_SECRET": "client-secret",
            "AUTH_OWNER_EMAIL": "  Straße@EXAMPLE.COM  ",
            "AUTH_PUBLIC_BASE_URL": "https://megabrain.example/",
            "AUTH_SESSION_TTL_SECONDS": "604800",
        }
    )

    assert settings.client_id == "client-id"
    assert settings.client_secret == "client-secret"
    assert settings.owner_email == "strasse@example.com"
    assert settings.public_base_url == "https://megabrain.example"
    assert settings.session_ttl_seconds == 604800
    assert "client-secret" not in repr(settings)


def test_auth_settings_reject_blank_required_values() -> None:
    for name in VALID_ENVIRONMENT:
        environment = {**VALID_ENVIRONMENT, name: " \t "}

        with pytest.raises(AuthConfigurationError):
            AuthSettings.from_environment(environment)


def test_auth_settings_only_accept_the_locked_session_ttl() -> None:
    for ttl in ("604799", "604801", "0604800", "604800.0"):
        with pytest.raises(AuthConfigurationError) as error:
            AuthSettings.from_environment(
                {**VALID_ENVIRONMENT, "AUTH_SESSION_TTL_SECONDS": ttl}
            )

        assert str(error.value) == "AUTH_SESSION_TTL_SECONDS must be exactly 604800"


def test_auth_settings_use_os_environ_when_no_mapping_is_supplied() -> None:
    with patch.dict(os.environ, VALID_ENVIRONMENT, clear=True):
        settings = AuthSettings.from_environment()

    assert settings.owner_email == "owner@example.com"


def test_auth_settings_reject_non_origin_only_public_urls() -> None:
    invalid_urls = (
        "http://megabrain.example",
        "https://user:password@megabrain.example",
        "https://megabrain.example/library",
        "https://megabrain.example?next=/library",
        "https://megabrain.example#fragment",
        "https://megabrain.example:",
        "https://megabrain.example:0",
        "https://megabrain.example:65536",
        r"https://megabrain.example\evil",
        "https://",
    )

    for public_url in invalid_urls:
        with pytest.raises(AuthConfigurationError) as error:
            AuthSettings.from_environment(
                {**VALID_ENVIRONMENT, "AUTH_PUBLIC_BASE_URL": public_url}
            )

        assert str(error.value) == "AUTH_PUBLIC_BASE_URL must be an HTTPS origin"


def test_opaque_tokens_are_random_and_only_hashes_are_persisted() -> None:
    first_token = config.generate_opaque_token()
    second_token = config.generate_opaque_token()
    first_hash = config.sha256_token(first_token)

    assert first_token
    assert first_token != second_token
    assert len(first_hash) == 32
    assert first_hash == config.sha256_token(first_token)
    assert first_hash != config.sha256_token(second_token)
    assert first_token.encode("ascii") != first_hash


def test_auth_cookie_policies_lock_host_only_security_attributes() -> None:
    assert config.SESSION_COOKIE_NAME == "__Host-mb_session"
    assert config.OIDC_TRANSACTION_COOKIE_NAME == "__Host-mb_oidc"
    assert config.SESSION_TTL_SECONDS == 604800
    assert config.OIDC_TRANSACTION_TTL_SECONDS == 600

    for policy, max_age in (
        (config.SESSION_COOKIE_POLICY, 604800),
        (config.OIDC_TRANSACTION_COOKIE_POLICY, 600),
    ):
        assert policy.secure is True
        assert policy.httponly is True
        assert policy.samesite == "lax"
        assert policy.path == "/"
        assert policy.domain is None
        assert policy.max_age == max_age
