from __future__ import annotations

import hashlib
import os
import secrets
from dataclasses import dataclass, field
from typing import Mapping
from urllib.parse import urlsplit, urlunsplit


class AuthConfigurationError(RuntimeError):
    """Raised when required authentication configuration is invalid."""


SESSION_COOKIE_NAME = "__Host-mb_session"
OIDC_TRANSACTION_COOKIE_NAME = "__Host-mb_oidc"
SESSION_TTL_SECONDS = 604800
OIDC_TRANSACTION_TTL_SECONDS = 600


@dataclass(frozen=True)
class CookiePolicy:
    secure: bool = True
    httponly: bool = True
    samesite: str = "lax"
    path: str = "/"
    domain: str | None = None
    max_age: int = 0


SESSION_COOKIE_POLICY = CookiePolicy(max_age=SESSION_TTL_SECONDS)
OIDC_TRANSACTION_COOKIE_POLICY = CookiePolicy(max_age=OIDC_TRANSACTION_TTL_SECONDS)


def generate_opaque_token() -> str:
    return secrets.token_urlsafe(32)


def sha256_token(token: str) -> bytes:
    return hashlib.sha256(token.encode("ascii")).digest()


def normalize_public_base_url(value: str) -> str:
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
        and parsed.fragment == ""
        and not parsed.netloc.endswith(":")
        and "\\" not in value
        and valid_port
    ):
        raise AuthConfigurationError("AUTH_PUBLIC_BASE_URL must be an HTTPS origin")

    return urlunsplit(("https", parsed.netloc, "", "", ""))


@dataclass(frozen=True)
class AuthSettings:
    client_id: str
    client_secret: str = field(repr=False)
    owner_email: str = ""
    public_base_url: str = ""
    session_ttl_seconds: int = 0

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str] | None = None
    ) -> AuthSettings:
        environment = os.environ if environment is None else environment
        names = (
            "GOOGLE_OIDC_CLIENT_ID",
            "GOOGLE_OIDC_CLIENT_SECRET",
            "AUTH_OWNER_EMAIL",
            "AUTH_PUBLIC_BASE_URL",
            "AUTH_SESSION_TTL_SECONDS",
        )
        missing = [
            name
            for name in names
            if (value := environment.get(name)) is None or not value.strip()
        ]
        if missing:
            raise AuthConfigurationError(
                "Missing required authentication configuration: " + ", ".join(missing)
            )
        if environment["AUTH_SESSION_TTL_SECONDS"] != str(SESSION_TTL_SECONDS):
            raise AuthConfigurationError(
                f"AUTH_SESSION_TTL_SECONDS must be exactly {SESSION_TTL_SECONDS}"
            )
        return cls(
            client_id=environment["GOOGLE_OIDC_CLIENT_ID"],
            client_secret=environment["GOOGLE_OIDC_CLIENT_SECRET"],
            owner_email=environment["AUTH_OWNER_EMAIL"].strip().casefold(),
            public_base_url=normalize_public_base_url(
                environment["AUTH_PUBLIC_BASE_URL"]
            ),
            session_ttl_seconds=int(environment["AUTH_SESSION_TTL_SECONDS"]),
        )
