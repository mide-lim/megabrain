from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Mapping
from urllib.parse import urlsplit

import httpx

from app.reel_ingestion import RegisteredReel


DISPATCH_PATH = "/webhook/megabrain-internal-dispatch"
DISPATCH_URL = f"http://n8n:5678{DISPATCH_PATH}"


class DispatchState(StrEnum):
    ACCEPTED = "accepted"
    NOT_REQUIRED = "not_required"
    UNCONFIRMED = "unconfirmed"


class ReelDispatchConfigurationError(RuntimeError):
    """Raised when outbound dispatch configuration is unavailable or invalid."""


class ReelDispatchInvariantError(RuntimeError):
    """Raised when a registered reel has an unsupported persisted status."""


@dataclass(frozen=True)
class WebToN8nDispatchSettings:
    web_to_n8n_dispatch_key: str = field(repr=False)
    web_to_n8n_dispatch_url: str

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str] | None = None
    ) -> WebToN8nDispatchSettings:
        environment = os.environ if environment is None else environment
        key = environment.get("WEB_TO_N8N_DISPATCH_KEY", "")
        url = environment.get("WEB_TO_N8N_DISPATCH_URL", "")
        if not key.strip() or not url.strip():
            raise ReelDispatchConfigurationError("Reel dispatch configuration is unavailable")
        _validate_dispatch_url(url)
        return cls(web_to_n8n_dispatch_key=key, web_to_n8n_dispatch_url=url)


def _validate_dispatch_url(value: str) -> None:
    if value != DISPATCH_URL:
        raise ReelDispatchConfigurationError("Reel dispatch configuration is unavailable")
    try:
        parsed = urlsplit(value)
    except ValueError:
        raise ReelDispatchConfigurationError("Reel dispatch configuration is unavailable") from None
    if (
        parsed.scheme != "http"
        or parsed.hostname != "n8n"
        or parsed.port != 5678
        or parsed.path != DISPATCH_PATH
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ReelDispatchConfigurationError("Reel dispatch configuration is unavailable")


def load_dispatch_settings() -> WebToN8nDispatchSettings:
    return WebToN8nDispatchSettings.from_environment()


async def request_internal_dispatch(
    reel_id: int, settings: WebToN8nDispatchSettings
) -> DispatchState:
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(5.0, connect=1.0),
            follow_redirects=False,
            trust_env=False,
        ) as client:
            response = await client.post(
                settings.web_to_n8n_dispatch_url,
                headers={"X-MegaBrain-Key": settings.web_to_n8n_dispatch_key},
                json={"reel_id": reel_id},
            )
    except httpx.HTTPError:
        return DispatchState.UNCONFIRMED

    if response.status_code != 202:
        return DispatchState.UNCONFIRMED

    try:
        body = response.json()
    except (json.JSONDecodeError, ValueError):
        return DispatchState.UNCONFIRMED

    if (
        not isinstance(body, dict)
        or set(body) != {"accepted", "reel_id"}
        or body["accepted"] is not True
        or isinstance(body["reel_id"], bool)
        or not isinstance(body["reel_id"], int)
        or body["reel_id"] != reel_id
    ):
        return DispatchState.UNCONFIRMED
    return DispatchState.ACCEPTED


async def dispatch_reel(
    reel: RegisteredReel, settings: WebToN8nDispatchSettings | None
) -> DispatchState:
    if reel.status in {"received", "download_failed"}:
        if settings is None:
            return DispatchState.UNCONFIRMED
        return await request_internal_dispatch(reel.id, settings)
    if reel.status in {"downloading", "downloaded"}:
        return DispatchState.NOT_REQUIRED
    raise ReelDispatchInvariantError("Unsupported reel status")
