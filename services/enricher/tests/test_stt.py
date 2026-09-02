from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from google.api_core import exceptions as google_exceptions
from google.auth import exceptions as google_auth_exceptions

from app.stt.base import (
    SpeechToTextAdapter,
    SynchronousRecognitionUnsupportedError,
    TranscriptionResult,
)
from app.stt.google import GoogleSpeechToTextAdapter

_UNSET = object()


@dataclass
class FakeGoogleClient:
    response: object
    request: object | None = None
    retry: object = _UNSET

    def recognize(self, *, request: object, retry: object = _UNSET) -> object:
        self.request = request
        self.retry = retry
        return self.response


def test_stt_contract_is_provider_independent() -> None:
    class StubAdapter(SpeechToTextAdapter):
        def transcribe(
            self,
            audio_path: Path,
            *,
            language_hint: str | None = None,
            duration_seconds: float | None = None,
        ) -> TranscriptionResult:
            return TranscriptionResult(
                transcript_text="Texto completo.",
                transcript_language="pt-BR",
                provider="stub",
                model="stub-model",
                provider_request_id=None,
            )

    result = StubAdapter().transcribe(Path("audio.wav"), language_hint="pt-BR")

    assert result.transcript_text == "Texto completo."
    assert result.transcript_language == "pt-BR"
    assert not hasattr(result, "transcript_segments")


def test_sync_recognize_limit_has_stable_provider_neutral_error() -> None:
    error = SynchronousRecognitionUnsupportedError("audio outside sync limits")

    assert error.error_code == "STT_SYNC_RECOGNIZE_UNSUPPORTED"
    assert error.stage == "transcription"
    assert error.retryable is False


def test_google_adapter_rejects_content_above_sync_size_limit() -> None:
    client = FakeGoogleClient(response={})
    adapter = GoogleSpeechToTextAdapter(client=client, project_id="test-project")

    try:
        adapter.transcribe_bytes(
            b"x" * (adapter.MAX_SYNC_CONTENT_BYTES + 1),
            duration_seconds=1.0,
        )
    except SynchronousRecognitionUnsupportedError as error:
        assert error.error_code == "STT_SYNC_RECOGNIZE_UNSUPPORTED"
    else:
        raise AssertionError("Expected synchronous size limit error")
    assert client.request is None


def test_google_adapter_rejects_duration_above_sync_limit() -> None:
    client = FakeGoogleClient(response={})
    adapter = GoogleSpeechToTextAdapter(client=client, project_id="test-project")

    try:
        adapter.transcribe_bytes(b"audio", duration_seconds=60.1)
    except SynchronousRecognitionUnsupportedError as error:
        assert error.stage == "transcription"
        assert error.retryable is False
    else:
        raise AssertionError("Expected synchronous duration limit error")
    assert client.request is None


def test_google_adapter_accepts_exact_synchronous_limits() -> None:
    client = FakeGoogleClient(response={"text": "texto", "language": "pt-BR"})
    adapter = GoogleSpeechToTextAdapter(client=client, project_id="test-project")

    result = adapter.transcribe_bytes(
        b"x" * adapter.MAX_SYNC_CONTENT_BYTES,
        duration_seconds=adapter.MAX_SYNC_DURATION_SECONDS,
    )

    assert result.transcript_text == "texto"
    assert client.request is not None


def test_google_adapter_is_injectable_and_does_not_require_credentials() -> None:
    client = FakeGoogleClient(
        response={
            "text": "fala clara",
            "language": "pt-BR",
            "metadata": {"request_id": "request-123"},
        }
    )
    adapter = GoogleSpeechToTextAdapter(
        client=client,
        project_id="test-project",
        recognizer="_",
        model="chirp_3",
    )

    result = adapter.transcribe_bytes(b"audio", language_hint="pt-BR")

    assert result == TranscriptionResult(
        transcript_text="fala clara",
        transcript_language="pt-BR",
        provider="google",
        model="chirp_3",
        provider_request_id="request-123",
    )
    assert client.request == {
        "recognizer": "projects/test-project/locations/us/recognizers/_",
        "config": {
            "auto_decoding_config": {},
            "language_codes": ["pt-BR"],
            "model": "chirp_3",
            "features": {"enable_automatic_punctuation": True},
        },
        "content": b"audio",
    }
    assert client.retry is None


def test_google_adapter_normalizes_object_response_to_complete_text() -> None:
    @dataclass
    class Alternative:
        transcript: str

    @dataclass
    class Result:
        alternatives: list[Alternative]
        language_code: str

    @dataclass
    class Response:
        results: list[Result]
        metadata: object

    @dataclass
    class Metadata:
        request_id: str

    response = Response(
        results=[
            Result([Alternative("primeira parte")], "pt-BR"),
            Result([Alternative("segunda parte")], "pt-BR"),
        ],
        metadata=Metadata(request_id="request-123"),
    )
    adapter = GoogleSpeechToTextAdapter(
        client=FakeGoogleClient(response),
        project_id="test-project",
    )

    result = adapter.transcribe_bytes(b"audio")

    assert result.transcript_text == "primeira parte segunda parte"
    assert result.transcript_language == "pt-BR"
    assert result.provider_request_id == "request-123"


@pytest.mark.parametrize(
    ("sdk_error", "code", "retryable"),
    [
        (google_exceptions.DeadlineExceeded("secret"), "STT_TIMEOUT", True),
        (google_exceptions.GatewayTimeout("secret"), "STT_TIMEOUT", True),
        (google_exceptions.ResourceExhausted("secret"), "STT_RATE_LIMITED", True),
        (google_exceptions.ServiceUnavailable("secret"), "STT_UNAVAILABLE", True),
        (google_exceptions.Aborted("secret"), "STT_UNAVAILABLE", True),
        (google_exceptions.InternalServerError("secret"), "STT_UNAVAILABLE", True),
        (google_exceptions.BadGateway("secret"), "STT_UNAVAILABLE", True),
        (google_exceptions.Unauthenticated("secret"), "STT_AUTH_FAILED", False),
        (google_exceptions.PermissionDenied("secret"), "STT_AUTH_FAILED", False),
        (
            google_auth_exceptions.DefaultCredentialsError("secret"),
            "STT_AUTH_FAILED",
            False,
        ),
        (google_exceptions.InvalidArgument("secret"), "STT_REQUEST_REJECTED", False),
        (
            google_exceptions.FailedPrecondition("secret"),
            "STT_REQUEST_REJECTED",
            False,
        ),
        (RuntimeError("secret"), "STT_FAILED", False),
    ],
)
def test_google_sdk_errors_are_sanitized_and_stable(
    sdk_error: Exception, code: str, retryable: bool
) -> None:
    class FailingClient:
        def recognize(self, *, request: object, retry: object = _UNSET) -> object:
            raise sdk_error

    adapter = GoogleSpeechToTextAdapter(client=FailingClient(), project_id="project")

    with pytest.raises(Exception) as raised:
        adapter.transcribe_bytes(b"audio")

    assert raised.value.error_code == code
    assert raised.value.stage == "transcription"
    assert raised.value.retryable is retryable
    assert "secret" not in str(raised.value)
