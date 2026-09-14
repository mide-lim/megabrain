from __future__ import annotations

import hmac
import json
import os
from dataclasses import dataclass, field
from typing import Mapping

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from app.reel_dispatch import (
    DispatchState,
    ReelDispatchConfigurationError,
    ReelDispatchInvariantError,
    WebToN8nDispatchSettings,
    dispatch_reel,
    load_dispatch_settings,
)

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
INTERNAL_INGESTION_SECURITY_SCHEME = "N8nIngestionKey"


class InternalIngestionConfigurationError(RuntimeError):
    """Raised when the internal ingestion boundary lacks valid configuration."""


class InternalRequestInvalid(ValueError):
    """Raised when the local internal-ingestion request contract is invalid."""


@dataclass(frozen=True)
class InternalIngestionSettings:
    n8n_to_web_ingestion_key: str = field(repr=False)

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str] | None = None
    ) -> InternalIngestionSettings:
        environment = os.environ if environment is None else environment
        key = environment.get("N8N_TO_WEB_INGESTION_KEY", "")
        if not key.strip():
            raise InternalIngestionConfigurationError(
                "Internal ingestion configuration is unavailable"
            )
        return cls(n8n_to_web_ingestion_key=key)


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


async def _dispatch_state(
    reel: RegisteredReel, settings: WebToN8nDispatchSettings
) -> DispatchState:
    return await dispatch_reel(reel, settings)


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
        dispatch_settings = load_dispatch_settings()
    except (InternalIngestionConfigurationError, ReelDispatchConfigurationError):
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
        dispatch = await _dispatch_state(reel, dispatch_settings)
    except ReelDispatchInvariantError:
        return _error_response(
            503,
            "internal_ingestion_unavailable",
            "Internal ingestion temporarily unavailable",
        )
    return _success_response(reel, dispatch)
