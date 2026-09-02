from __future__ import annotations

import logging
import os
import secrets
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.media import (
    EnrichmentRequest,
    EnrichmentResponse,
    ErrorResponse,
    ErrorStage,
    MediaMetadata,
    MediaProcessingError,
    ProcessingMetadata,
    SourceMetadata,
    Transcription,
    TranscriptionEngine,
    probe_media,
    temporary_audio,
)
from app.r2 import verified_r2_object
from app.stt.base import (
    SpeechToTextAdapter,
    SpeechToTextError,
    SynchronousRecognitionUnsupportedError,
)
from app.stt.google import GoogleSpeechToTextAdapter

VERSION = "0.1.0"
API_KEY = os.getenv("ENRICHER_API_KEY", "")
logger = logging.getLogger("megabrain-enricher")

app = FastAPI(title="MegaBrain Enricher", version=VERSION)


def _r2_client() -> Any:
    import boto3

    return boto3.client(
        service_name="s3",
        endpoint_url=os.environ["R2_ENDPOINT"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )


MediaPipeline = Callable[[Path], Any]


def _stt_adapter() -> GoogleSpeechToTextAdapter:
    return GoogleSpeechToTextAdapter(project_id=os.environ["GOOGLE_CLOUD_PROJECT"])


def enrich_media(
    payload: EnrichmentRequest,
    media_path: Path,
    source: SourceMetadata,
    *,
    metadata: MediaMetadata | None = None,
    stt_adapter: SpeechToTextAdapter,
    started_at: datetime | None = None,
) -> EnrichmentResponse:
    started = started_at or datetime.now(timezone.utc)
    media = metadata or probe_media(media_path)
    transcription_input = None

    if media.audio is None:
        transcription = Transcription(
            outcome="no_audio",
            transcript_text=None,
            transcript_language=None,
            engine=TranscriptionEngine(provider=None, model=None, request_id=None),
        )
    else:
        with temporary_audio(media_path) as extracted:
            transcription_input = extracted.metadata
            result = stt_adapter.transcribe(
                extracted.path,
                language_hint=payload.language_hint,
                duration_seconds=extracted.metadata.duration_seconds,
            )
        text = result.transcript_text.strip()
        transcription = Transcription(
            outcome="transcribed" if text else "empty_transcript",
            transcript_text=text,
            transcript_language=result.transcript_language,
            engine=TranscriptionEngine(
                provider=result.provider,
                model=result.model,
                request_id=result.provider_request_id,
            ),
        )

    return EnrichmentResponse(
        contract_version=payload.contract_version,
        attempt_id=payload.attempt_id,
        reel_id=payload.reel_id,
        shortcode=payload.shortcode,
        pipeline_version=payload.pipeline_version,
        processor_version=VERSION,
        source=source,
        media=media,
        transcription_input=transcription_input,
        transcription=transcription,
        processing=ProcessingMetadata(
            started_at=started,
            completed_at=datetime.now(timezone.utc),
        ),
        warnings=[],
    )


def process_source(
    payload: EnrichmentRequest,
    *,
    client: Any,
    bucket: str,
    pipeline: MediaPipeline | None = None,
    stt_adapter: SpeechToTextAdapter | None = None,
) -> Any:
    started_at = datetime.now(timezone.utc)
    with verified_r2_object(
        client=client,
        bucket=bucket,
        object_key=payload.object_key,
        shortcode=payload.shortcode,
        expected_sha256=payload.expected_sha256,
        expected_size_bytes=payload.expected_size_bytes,
    ) as (media_path, source):
        if pipeline is not None:
            return pipeline(media_path)
        if stt_adapter is None:
            raise RuntimeError("STT adapter is required")
        return enrich_media(
            payload,
            media_path,
            source,
            stt_adapter=stt_adapter,
            started_at=started_at,
        )


def _attempt_id(value: Any) -> UUID | None:
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _error(
    status_code: int,
    *,
    error_code: str,
    stage: ErrorStage,
    message: str,
    retryable: bool,
    attempt_id: UUID | None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = ErrorResponse(
        error_code=error_code,
        stage=stage,
        message=message,
        retryable=retryable,
        attempt_id=attempt_id,
    )
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(mode="json"),
        headers=headers,
    )


@app.middleware("http")
async def authenticate_enrichment(request: Request, call_next: Any) -> JSONResponse:
    if request.url.path == "/v1/enrichments":
        received_key = request.headers.get("X-MegaBrain-Key")
        if (
            not API_KEY
            or not received_key
            or not secrets.compare_digest(
                received_key,
                API_KEY,
            )
        ):
            return _error(
                401,
                error_code="UNAUTHORIZED",
                stage=ErrorStage.INPUT,
                message="Invalid or missing internal API key",
                retryable=False,
                attempt_id=None,
            )

    return await call_next(request)


@app.exception_handler(RequestValidationError)
async def request_validation_error(
    _request: Request,
    error_details: RequestValidationError,
) -> JSONResponse:
    body = error_details.body
    correlation_id = _attempt_id(
        body.get("attempt_id") if isinstance(body, dict) else None
    )
    return _error(
        422,
        error_code="INVALID_REQUEST",
        stage=ErrorStage.INPUT,
        message="Request validation failed",
        retryable=False,
        attempt_id=correlation_id,
    )


@app.exception_handler(StarletteHTTPException)
async def framework_http_error(
    _request: Request,
    error: StarletteHTTPException,
) -> JSONResponse:
    server_error = error.status_code >= 500
    return _error(
        error.status_code,
        error_code="INTERNAL_ERROR" if server_error else "INVALID_REQUEST",
        stage=ErrorStage.INTERNAL if server_error else ErrorStage.INPUT,
        message=(
            "Unexpected internal error"
            if server_error
            else "Request could not be processed"
        ),
        retryable=error.status_code in {429, 502, 503, 504},
        attempt_id=None,
        headers=error.headers,
    )


@app.exception_handler(Exception)
async def unexpected_error(
    _request: Request,
    error: Exception,
) -> JSONResponse:
    logger.error(
        "Unexpected internal error",
        exc_info=(type(error), error, error.__traceback__),
    )
    return _error(
        500,
        error_code="INTERNAL_ERROR",
        stage=ErrorStage.INTERNAL,
        message="Unexpected internal error",
        retryable=False,
        attempt_id=None,
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "healthy", "version": VERSION}


@app.post(
    "/v1/enrichments",
    response_model=EnrichmentResponse,
    responses={
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
        504: {"model": ErrorResponse},
    },
)
async def create_enrichment(
    request: Request,
    payload: EnrichmentRequest,
    _x_megabrain_key: str | None = Header(default=None, alias="X-MegaBrain-Key"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> JSONResponse:
    correlation_id = payload.attempt_id

    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip()
    if content_type != "application/json":
        return _error(
            422,
            error_code="INVALID_REQUEST",
            stage=ErrorStage.INPUT,
            message="Content-Type must be application/json",
            retryable=False,
            attempt_id=correlation_id,
        )

    header_attempt_id = _attempt_id(idempotency_key)
    if header_attempt_id != payload.attempt_id:
        return _error(
            409,
            error_code="ATTEMPT_CONFLICT",
            stage=ErrorStage.INPUT,
            message="Idempotency-Key must match attempt_id",
            retryable=False,
            attempt_id=payload.attempt_id,
        )

    try:
        result = process_source(
            payload,
            client=_r2_client(),
            bucket=os.environ["R2_BUCKET"],
            stt_adapter=_stt_adapter(),
        )
    except MediaProcessingError as error:
        return _error(
            404 if error.error_code == "OBJECT_NOT_FOUND" else 422,
            error_code=error.error_code,
            stage=error.stage,
            message=str(error),
            retryable=error.retryable,
            attempt_id=payload.attempt_id,
        )
    except (SpeechToTextError, SynchronousRecognitionUnsupportedError) as error:
        status = {
            "STT_TIMEOUT": 504,
            "STT_RATE_LIMITED": 429,
            "STT_UNAVAILABLE": 503,
            "STT_REQUEST_REJECTED": 422,
            "STT_SYNC_RECOGNIZE_UNSUPPORTED": 422,
        }.get(error.error_code, 500)
        return _error(
            status,
            error_code=error.error_code,
            stage=ErrorStage.TRANSCRIPTION,
            message=str(error),
            retryable=error.retryable,
            attempt_id=payload.attempt_id,
        )
    except (KeyError, OSError, RuntimeError):
        return _error(
            500,
            error_code="INTERNAL_ERROR",
            stage=ErrorStage.INTERNAL,
            message="Unexpected internal error",
            retryable=False,
            attempt_id=payload.attempt_id,
        )

    return JSONResponse(status_code=200, content=result.model_dump(mode="json"))
