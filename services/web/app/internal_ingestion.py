from __future__ import annotations

import hmac
import json
import os
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Mapping
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from app.reel_ingestion import (
    InvalidReelUrl,
    ReelIdentityConflict,
    ReelRegistrationUnavailable,
    RegisteredReel,
    TelegramAdapterMetadata,
    register_reel,
)

router = APIRouter(prefix="/internal", tags=["internal"])

MAX_SAFE_INTEGER = 9_007_199_254_740_991
DISPATCH_PATH = "/webhook/megabrain-internal-dispatch"
DISPATCH_URL = f"http://n8n:5678{DISPATCH_PATH}"
INTERNAL_INGESTION_SECURITY_SCHEME = "N8nIngestionKey"


class InternalIngestionConfigurationError(RuntimeError):
    """Raised when the internal ingestion boundary lacks valid configuration."""


class InternalRequestInvalid(ValueError):
    """Raised when the local internal-ingestion request contract is invalid."""


class InternalIngestionInvariantError(RuntimeError):
    """Raised when a registered reel has an unsupported persisted status."""


class DispatchState(StrEnum):
    ACCEPTED = "accepted"
    NOT_REQUIRED = "not_required"
    UNCONFIRMED = "unconfirmed"


@dataclass(frozen=True)
class InternalIngestionSettings:
    n8n_to_web_ingestion_key: str = field(repr=False)
    web_to_n8n_dispatch_key: str = field(repr=False)
    web_to_n8n_dispatch_url: str

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str] | None = None
    ) -> InternalIngestionSettings:
        environment = os.environ if environment is None else environment
        names = (
            "N8N_TO_WEB_INGESTION_KEY",
            "WEB_TO_N8N_DISPATCH_KEY",
            "WEB_TO_N8N_DISPATCH_URL",
        )
        values = {name: environment.get(name, "") for name in names}
        if any(not value.strip() for value in values.values()):
            raise InternalIngestionConfigurationError(
                "Internal ingestion configuration is unavailable"
            )
        if values["WEB_TO_N8N_DISPATCH_URL"] != DISPATCH_URL:
            raise InternalIngestionConfigurationError(
                "Internal ingestion configuration is unavailable"
            )
        _validate_dispatch_url(values["WEB_TO_N8N_DISPATCH_URL"])
        return cls(
            n8n_to_web_ingestion_key=values["N8N_TO_WEB_INGESTION_KEY"],
            web_to_n8n_dispatch_key=values["WEB_TO_N8N_DISPATCH_KEY"],
            web_to_n8n_dispatch_url=values["WEB_TO_N8N_DISPATCH_URL"],
        )


def _validate_dispatch_url(value: str) -> None:
    parsed = urlsplit(value)
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
        raise InternalIngestionConfigurationError(
            "Internal ingestion configuration is unavailable"
        )


def load_settings() -> InternalIngestionSettings:
    return InternalIngestionSettings.from_environment()


class TelegramPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    chat_id: int
    user_id: int
    message_id: int
    raw_message: str

    @field_validator("chat_id")
    @classmethod
    def validate_chat_id(cls, value: int) -> int:
        if value == 0 or abs(value) > MAX_SAFE_INTEGER:
            raise ValueError("invalid chat_id")
        return value

    @field_validator("user_id", "message_id")
    @classmethod
    def validate_positive_safe_id(cls, value: int) -> int:
        if value <= 0 or value > MAX_SAFE_INTEGER:
            raise ValueError("invalid Telegram identifier")
        return value


class InternalReelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    url: str
    telegram: TelegramPayload


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
        headers={"Cache-Control": "no-store"},
    )


def _unauthorized_response() -> JSONResponse:
    return _error_response(401, "unauthorized", "Unauthorized")


def _validate_api_key(request: Request, settings: InternalIngestionSettings) -> bool:
    provided_key = request.headers.get("X-MegaBrain-Key")
    return isinstance(provided_key, str) and hmac.compare_digest(
        provided_key, settings.n8n_to_web_ingestion_key
    )


async def _parse_request(request: Request) -> InternalReelRequest:
    try:
        body = await request.body()
        parsed = json.loads(body)
        return InternalReelRequest.model_validate(parsed)
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError, TypeError):
        raise InternalRequestInvalid("Invalid ingestion request") from None


async def request_internal_dispatch(
    reel_id: int, settings: InternalIngestionSettings
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


async def _dispatch_state(
    reel: RegisteredReel, settings: InternalIngestionSettings
) -> DispatchState:
    if reel.status in {"received", "download_failed"}:
        return await request_internal_dispatch(reel.id, settings)
    if reel.status in {"downloading", "downloaded"}:
        return DispatchState.NOT_REQUIRED
    raise InternalIngestionInvariantError("Unsupported reel status")


def _success_response(reel: RegisteredReel, dispatch: DispatchState) -> JSONResponse:
    return JSONResponse(
        status_code=201 if reel.created else 200,
        content={
            "reel": {
                "id": reel.id,
                "shortcode": reel.shortcode,
                "original_url": reel.original_url,
                "status": reel.status,
                "created": reel.created,
            },
            "dispatch": {"state": dispatch.value},
        },
        headers={"Cache-Control": "no-store"},
    )


@router.post(
    "/reels",
    openapi_extra={
        "security": [{INTERNAL_INGESTION_SECURITY_SCHEME: []}],
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "required": ["url", "telegram"],
                        "additionalProperties": False,
                    }
                }
            },
        },
    },
)
async def register_internal_reel(request: Request) -> JSONResponse:
    try:
        settings = load_settings()
    except InternalIngestionConfigurationError:
        return _error_response(
            503,
            "internal_ingestion_unavailable",
            "Internal ingestion temporarily unavailable",
        )

    if not _validate_api_key(request, settings):
        return _unauthorized_response()

    try:
        payload = await _parse_request(request)
        telegram_metadata = TelegramAdapterMetadata(
            telegram_chat_id=payload.telegram.chat_id,
            telegram_user_id=payload.telegram.user_id,
            telegram_message_id=payload.telegram.message_id,
            raw_message=payload.telegram.raw_message,
        )
        reel = register_reel(
            raw_url=payload.url,
            telegram_metadata=telegram_metadata,
        )
    except (InternalRequestInvalid, ValueError, InvalidReelUrl):
        return _error_response(422, "invalid_request", "Invalid ingestion request")
    except ReelIdentityConflict:
        return _error_response(
            409,
            "reel_identity_conflict",
            "Reel natural identity conflict",
        )
    except ReelRegistrationUnavailable:
        return _error_response(
            503,
            "registration_unavailable",
            "Reel registration temporarily unavailable",
        )

    try:
        dispatch = await _dispatch_state(reel, settings)
    except InternalIngestionInvariantError:
        return _error_response(
            503,
            "internal_ingestion_unavailable",
            "Internal ingestion temporarily unavailable",
        )
    return _success_response(reel, dispatch)
