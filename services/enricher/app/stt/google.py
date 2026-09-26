from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

from app.gcs import TemporaryAudioStoreError
from app.stt.base import (
    BatchReconciliationResult,
    BatchSubmissionResult,
    ReconciliationError,
    SpeechToTextAdapter,
    SpeechToTextError,
    SynchronousRecognitionUnsupportedError,
    TranscriptionResult,
)


class GoogleSpeechToTextAdapter(SpeechToTextAdapter):
    """Injectable Google STT V2 adapter for sync and batch submission."""

    MAX_SYNC_CONTENT_BYTES = 10_485_760
    MAX_SYNC_DURATION_SECONDS = 60.0
    MAX_BATCH_DURATION_SECONDS = 3600.0

    def __init__(
        self,
        *,
        project_id: str,
        client: Any | None = None,
        location: str = "us",
        recognizer: str = "_",
        model: str = "chirp_3",
        temporary_audio_store: Any | None = None,
    ) -> None:
        self._client = client
        self._project_id = project_id
        self._location = location
        self._recognizer = recognizer
        self._model = model
        self._temporary_audio_store = temporary_audio_store

    def _get_client(self) -> Any:
        if self._client is None:
            from google.cloud import speech_v2

            self._client = speech_v2.SpeechClient(
                client_options={"api_endpoint": "us-speech.googleapis.com"}
            )
        return self._client

    def batch_input_uri(self, *, attempt_id: UUID | str) -> str:
        if self._temporary_audio_store is None:
            raise ReconciliationError(
                "STT_RECONCILIATION_CONFIGURATION_REQUIRED",
                "Batch transcription reconciliation requires temporary storage configuration",
                retryable=False,
            )
        try:
            return self._temporary_audio_store.uri_for(attempt_id=attempt_id)
        except TemporaryAudioStoreError:
            raise ReconciliationError(
                "STT_RECONCILIATION_CONFIGURATION_REQUIRED",
                "Batch transcription reconciliation requires temporary storage configuration",
                retryable=False,
            ) from None

    def cleanup_batch_audio(self, *, attempt_id: UUID | str) -> None:
        if self._temporary_audio_store is None:
            return
        try:
            self._temporary_audio_store.cleanup(attempt_id=attempt_id)
        except TemporaryAudioStoreError:
            return

    def reconcile_batch(
        self,
        *,
        provider_request_id: str,
        expected_input_uri: str | None = None,
    ) -> BatchReconciliationResult:
        """Read one exact known BatchRecognize operation without submitting work."""
        try:
            operation = self._get_client().transport.operations_client.get_operation(
                name=provider_request_id,
                retry=None,
            )
        except Exception as error:  # noqa: BLE001 - SDK failures vary.
            raise self._translate_reconciliation_error(error) from None

        if not getattr(operation, "done", False):
            return BatchReconciliationResult(
                state="pending",
                provider="google",
                model=self._model,
                provider_request_id=provider_request_id,
                transcript_text=None,
                transcript_language=None,
            )
        if self._operation_has_field(operation, "error"):
            return BatchReconciliationResult(
                state="terminal_provider_failure",
                provider="google",
                model=self._model,
                provider_request_id=provider_request_id,
                transcript_text=None,
                transcript_language=None,
            )
        if not self._operation_has_field(operation, "response") or not expected_input_uri:
            raise ReconciliationError(
                "STT_RECONCILIATION_INVALID_RESPONSE",
                "Batch transcription reconciliation response was invalid",
                retryable=False,
            )

        try:
            from google.cloud import speech_v2

            response_pb = speech_v2.types.BatchRecognizeResponse.pb()()
            if not operation.response.Unpack(response_pb):
                raise ValueError
            response = speech_v2.types.BatchRecognizeResponse(response_pb)
            if len(response.results) != 1:
                raise ValueError
            file_result = response.results.get(expected_input_uri)
            if file_result is None:
                raise ValueError
            inline = file_result.inline_result
            if inline is None:
                raise ValueError
            text, language, _request_id = self._normalize_response(inline.transcript)
        except Exception:  # noqa: BLE001 - provider response is untrusted input.
            raise ReconciliationError(
                "STT_RECONCILIATION_INVALID_RESPONSE",
                "Batch transcription reconciliation response was invalid",
                retryable=False,
            ) from None

        return BatchReconciliationResult(
            state="terminal_success",
            provider="google",
            model=self._model,
            provider_request_id=provider_request_id,
            transcript_text=text,
            transcript_language=language,
        )

    @staticmethod
    def _operation_has_field(operation: Any, field: str) -> bool:
        has_field = getattr(operation, "HasField", None)
        if callable(has_field):
            try:
                return bool(has_field(field))
            except (TypeError, ValueError):
                return False
        value = getattr(operation, field, None)
        return value is not None

    @staticmethod
    def _translate_reconciliation_error(error: Exception) -> ReconciliationError:
        from google.api_core import exceptions as google_errors
        from google.auth import exceptions as google_auth_errors

        if isinstance(
            error, (google_errors.DeadlineExceeded, google_errors.GatewayTimeout)
        ):
            return ReconciliationError(
                "STT_RECONCILIATION_TIMEOUT",
                "Batch transcription reconciliation timed out",
                retryable=True,
            )
        if isinstance(error, google_errors.ResourceExhausted):
            return ReconciliationError(
                "STT_RECONCILIATION_RATE_LIMITED",
                "Batch transcription reconciliation rate limit exceeded",
                retryable=True,
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
            return ReconciliationError(
                "STT_RECONCILIATION_UNAVAILABLE",
                "Batch transcription reconciliation unavailable",
                retryable=True,
            )
        if isinstance(
            error,
            (
                google_errors.Unauthenticated,
                google_errors.PermissionDenied,
                google_auth_errors.DefaultCredentialsError,
            ),
        ):
            return ReconciliationError(
                "STT_RECONCILIATION_AUTH_FAILED",
                "Batch transcription reconciliation authentication failed",
                retryable=False,
            )
        return ReconciliationError(
            "STT_RECONCILIATION_FAILED",
            "Batch transcription reconciliation failed",
            retryable=False,
        )

    def transcribe(
        self,
        audio_path: Path,
        *,
        language_hint: str | None = None,
        duration_seconds: float | None = None,
        attempt_id: UUID | str | None = None,
    ) -> TranscriptionResult | BatchSubmissionResult:
        content_size = audio_path.stat().st_size
        if self._is_sync_safe(
            content_size=content_size,
            duration_seconds=duration_seconds,
        ):
            return self.transcribe_bytes(
                audio_path.read_bytes(),
                language_hint=language_hint,
                duration_seconds=duration_seconds,
            )
        return self._submit_batch(
            audio_path,
            attempt_id=attempt_id,
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

    @classmethod
    def _is_sync_safe(
        cls,
        *,
        content_size: int,
        duration_seconds: float | None,
    ) -> bool:
        return content_size <= cls.MAX_SYNC_CONTENT_BYTES and (
            duration_seconds is None
            or duration_seconds <= cls.MAX_SYNC_DURATION_SECONDS
        )

    def _submit_batch(
        self,
        audio_path: Path,
        *,
        attempt_id: UUID | str | None,
        language_hint: str | None,
        duration_seconds: float | None,
    ) -> BatchSubmissionResult:
        normalized_duration = duration_seconds if duration_seconds is not None else 0.0
        if normalized_duration > self.MAX_BATCH_DURATION_SECONDS:
            raise SpeechToTextError(
                "STT_BATCH_UNSUPPORTED_DURATION",
                "Audio exceeds BatchRecognize duration limit",
                retryable=False,
            )
        if attempt_id is None or self._temporary_audio_store is None or not getattr(
            self._temporary_audio_store, "configured", False
        ):
            raise SpeechToTextError(
                "STT_BATCH_CONFIGURATION_REQUIRED",
                "Batch transcription requires temporary storage configuration",
                retryable=False,
            )
        try:
            temporary_audio = self._temporary_audio_store.upload(
                attempt_id=attempt_id,
                path=audio_path,
            )
        except TemporaryAudioStoreError as error:
            raise SpeechToTextError(
                error.error_code,
                str(error),
                retryable=False,
            ) from None

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
            "files": [{"uri": temporary_audio.uri}],
            "recognition_output_config": {"inline_response_config": {}},
        }
        try:
            operation = self._get_client().batch_recognize(request=request, retry=None)
            operation_name = self._operation_name(operation)
        except Exception:  # noqa: BLE001 - submission status is ambiguous.
            raise SpeechToTextError(
                "STT_BATCH_SUBMISSION_UNKNOWN",
                "Batch transcription submission outcome is unknown",
                retryable=False,
            ) from None
        if operation_name is None:
            raise SpeechToTextError(
                "STT_BATCH_SUBMISSION_UNKNOWN",
                "Batch transcription submission outcome is unknown",
                retryable=False,
            )
        return BatchSubmissionResult(
            provider="google",
            model=self._model,
            provider_request_id=operation_name,
            state="processing",
        )

    @staticmethod
    def _operation_name(operation: Any) -> str | None:
        raw_operation = getattr(operation, "operation", None)
        name = getattr(raw_operation, "name", None) or getattr(operation, "name", None)
        return str(name) if name else None

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
