from __future__ import annotations

from pathlib import Path
from typing import Any

from app.stt.base import (
    SpeechToTextAdapter,
    SpeechToTextError,
    SynchronousRecognitionUnsupportedError,
    TranscriptionResult,
)


class GoogleSpeechToTextAdapter(SpeechToTextAdapter):
    """Injectable Google STT V2 adapter using synchronous Recognize only."""

    MAX_SYNC_CONTENT_BYTES = 10_485_760
    MAX_SYNC_DURATION_SECONDS = 60.0

    def __init__(
        self,
        *,
        project_id: str,
        client: Any | None = None,
        location: str = "us",
        recognizer: str = "_",
        model: str = "chirp_3",
    ) -> None:
        self._client = client
        self._project_id = project_id
        self._location = location
        self._recognizer = recognizer
        self._model = model

    def _get_client(self) -> Any:
        if self._client is None:
            from google.cloud import speech_v2

            self._client = speech_v2.SpeechClient(
                client_options={"api_endpoint": "us-speech.googleapis.com"}
            )
        return self._client

    def transcribe(
        self,
        audio_path: Path,
        *,
        language_hint: str | None = None,
        duration_seconds: float | None = None,
    ) -> TranscriptionResult:
        self._ensure_sync_supported(
            content_size=audio_path.stat().st_size,
            duration_seconds=duration_seconds,
        )
        return self.transcribe_bytes(
            audio_path.read_bytes(),
            language_hint=language_hint,
            duration_seconds=duration_seconds,
        )

    def transcribe_bytes(
        self,
        content: bytes,
        *,
        language_hint: str | None = None,
        duration_seconds: float | None = None,
    ) -> TranscriptionResult:
        self._ensure_sync_supported(
            content_size=len(content),
            duration_seconds=duration_seconds,
        )
        language = language_hint or "pt-BR"
        request = {
            "recognizer": (
                f"projects/{self._project_id}/locations/{self._location}"
                f"/recognizers/{self._recognizer}"
            ),
            "config": {
                "auto_decoding_config": {},
                "language_codes": [language],
                "model": self._model,
                "features": {"enable_automatic_punctuation": True},
            },
            "content": content,
        }
        try:
            response = self._get_client().recognize(request=request, retry=None)
        except Exception as error:  # noqa: BLE001 - SDK and ADC failures vary.
            raise self._translate_error(error) from None
        text, detected_language, request_id = self._normalize_response(response)
        return TranscriptionResult(
            transcript_text=text,
            transcript_language=detected_language or language,
            provider="google",
            model=self._model,
            provider_request_id=request_id,
        )

    @staticmethod
    def _translate_error(error: Exception) -> SpeechToTextError:
        from google.api_core import exceptions as google_errors
        from google.auth import exceptions as google_auth_errors

        if isinstance(
            error, (google_errors.DeadlineExceeded, google_errors.GatewayTimeout)
        ):
            return SpeechToTextError(
                "STT_TIMEOUT", "Transcription timed out", retryable=True
            )
        if isinstance(error, google_errors.ResourceExhausted):
            return SpeechToTextError(
                "STT_RATE_LIMITED", "Transcription rate limit exceeded", retryable=True
            )
        if isinstance(
            error,
            (
                google_errors.ServiceUnavailable,
                google_errors.Aborted,
                google_errors.InternalServerError,
                google_errors.BadGateway,
            ),
        ):
            return SpeechToTextError(
                "STT_UNAVAILABLE", "Transcription service unavailable", retryable=True
            )
        if isinstance(
            error,
            (
                google_errors.Unauthenticated,
                google_errors.PermissionDenied,
                google_auth_errors.DefaultCredentialsError,
            ),
        ):
            return SpeechToTextError(
                "STT_AUTH_FAILED",
                "Transcription authentication failed",
                retryable=False,
            )
        if isinstance(
            error, (google_errors.InvalidArgument, google_errors.FailedPrecondition)
        ):
            return SpeechToTextError(
                "STT_REQUEST_REJECTED",
                "Transcription request rejected",
                retryable=False,
            )
        return SpeechToTextError("STT_FAILED", "Transcription failed", retryable=False)

    @classmethod
    def _ensure_sync_supported(
        cls,
        *,
        content_size: int,
        duration_seconds: float | None,
    ) -> None:
        if content_size > cls.MAX_SYNC_CONTENT_BYTES or (
            duration_seconds is not None
            and duration_seconds > cls.MAX_SYNC_DURATION_SECONDS
        ):
            raise SynchronousRecognitionUnsupportedError(
                "Audio exceeds synchronous Recognize limits"
            )

    @staticmethod
    def _normalize_response(response: Any) -> tuple[str, str | None, str | None]:
        if isinstance(response, dict):
            metadata = response.get("metadata") or {}
            request_id = metadata.get("request_id")
            return (
                str(response.get("text", "")).strip(),
                response.get("language"),
                str(request_id) if request_id is not None else None,
            )

        transcript_parts: list[str] = []
        detected_language: str | None = None
        for result in getattr(response, "results", []):
            alternatives = getattr(result, "alternatives", [])
            if alternatives:
                text = str(getattr(alternatives[0], "transcript", "")).strip()
                if text:
                    transcript_parts.append(text)
            detected_language = detected_language or getattr(
                result,
                "language_code",
                None,
            )

        metadata = getattr(response, "metadata", None)
        request_id = getattr(metadata, "request_id", None)
        return (
            " ".join(transcript_parts),
            detected_language,
            str(request_id) if request_id is not None else None,
        )
