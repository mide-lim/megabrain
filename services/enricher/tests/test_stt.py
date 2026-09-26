from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from google.api_core import exceptions as google_exceptions
from google.auth import exceptions as google_auth_exceptions

from app import main
from app.stt.base import (
    BatchReconciliationResult,
    BatchSubmissionResult,
    ReconciliationError,
    SpeechToTextAdapter,
    SpeechToTextError,
    SynchronousRecognitionUnsupportedError,
    TranscriptionResult,
)
from app.stt.google import GoogleSpeechToTextAdapter
from app.gcs import TemporaryAudioObject, TemporaryAudioStoreError

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


def test_sync_route_does_not_require_temporary_bucket_configuration() -> None:
    client = FakeGoogleClient(response={"text": "texto", "language": "pt-BR"})
    adapter = GoogleSpeechToTextAdapter(client=client, project_id="test-project")

    result = adapter.transcribe(
        SizedAudioPath(1),  # type: ignore[arg-type]
        duration_seconds=60.0,
    )

    assert isinstance(result, TranscriptionResult)
    assert result.transcript_text == "texto"
    assert client.request is not None


def test_google_adapter_uses_us_regional_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    from google.cloud import speech_v2

    observed_options: list[object] = []

    class Client:
        pass

    def fake_speech_client(*, client_options: object) -> Client:
        observed_options.append(client_options)
        return Client()

    monkeypatch.setattr(speech_v2, "SpeechClient", fake_speech_client)
    adapter = GoogleSpeechToTextAdapter(project_id="test-project")

    adapter._get_client()

    assert observed_options == [{"api_endpoint": "us-speech.googleapis.com"}]


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


@dataclass
class FakeBatchClient:
    operation: object | None = None
    error: Exception | None = None
    batch_request: object | None = None
    batch_retry: object = _UNSET
    batch_calls: int = 0
    recognize_calls: int = 0

    def recognize(self, *, request: object, retry: object = _UNSET) -> object:
        self.recognize_calls += 1
        return {"text": "texto", "language": "pt-BR"}

    def batch_recognize(self, *, request: object, retry: object = _UNSET) -> object:
        self.batch_calls += 1
        self.batch_request = request
        self.batch_retry = retry
        if self.error is not None:
            raise self.error
        return self.operation


class FakeBatchOperation:
    class RawOperation:
        name = "projects/123/locations/us/operations/v2-test-operation"

    operation = RawOperation()

    def result(self) -> None:
        raise AssertionError("Batch operation must not be awaited")

    def done(self) -> None:
        raise AssertionError("Batch operation must not be polled")


class FakeTemporaryStore:
    def __init__(self) -> None:
        self.upload_calls: list[tuple[object, Path]] = []
        self.delete_calls = 0

    @property
    def configured(self) -> bool:
        return True

    def upload(self, *, attempt_id: object, path: Path) -> TemporaryAudioObject:
        self.upload_calls.append((attempt_id, path))
        return TemporaryAudioObject(
            bucket="test-temp-bucket",
            object_name=f"f6/transcription/{attempt_id}/audio.wav",
            uri=f"gs://test-temp-bucket/f6/transcription/{attempt_id}/audio.wav",
            generation="1",
        )

    def delete(self) -> None:
        self.delete_calls += 1


class SizedAudioPath:
    def __init__(self, size: int) -> None:
        self._size = size

    def stat(self):  # type: ignore[no-untyped-def]
        class Stat:
            st_size = self._size

        return Stat()

    def read_bytes(self) -> bytes:
        return b"audio"


def test_application_configuration_without_temp_bucket_keeps_sync_recognize(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GOOGLE_STT_TEMP_BUCKET", raising=False)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    adapter = main._stt_adapter()
    client = FakeGoogleClient(response={"text": "texto", "language": "pt-BR"})
    adapter._client = client

    result = adapter.transcribe(
        SizedAudioPath(1),  # type: ignore[arg-type]
        duration_seconds=60.0,
    )

    assert adapter._temporary_audio_store is None
    assert isinstance(result, TranscriptionResult)
    assert result.transcript_text == "texto"
    assert client.request is not None


def test_application_configuration_without_temp_bucket_blocks_batch_before_upload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ObservedTemporaryStore:
        construction_count = 0
        upload_call_count = 0

        def __init__(self, *, bucket: str) -> None:
            type(self).construction_count += 1

        def upload(self, *, attempt_id: object, path: Path) -> TemporaryAudioObject:
            type(self).upload_call_count += 1
            raise AssertionError("GCS upload must not be attempted")

    monkeypatch.delenv("GOOGLE_STT_TEMP_BUCKET", raising=False)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    monkeypatch.setattr(main, "GoogleTemporaryAudioStore", ObservedTemporaryStore)
    adapter = main._stt_adapter()
    client = FakeBatchClient(operation=FakeBatchOperation())
    adapter._client = client

    with pytest.raises(SpeechToTextError) as raised:
        adapter.transcribe(
            SizedAudioPath(1),  # type: ignore[arg-type]
            duration_seconds=60.1,
            attempt_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        )

    assert adapter._temporary_audio_store is None
    assert ObservedTemporaryStore.construction_count == 0
    assert ObservedTemporaryStore.upload_call_count == 0
    assert raised.value.error_code == "STT_BATCH_CONFIGURATION_REQUIRED"
    assert client.batch_calls == 0


@pytest.mark.parametrize(
    ("duration_seconds", "size_bytes", "expected_method"),
    [
        (59.9, 10_485_759, "recognize"),
        (60.0, 10_485_760, "recognize"),
        (60.0, 10_485_761, "batch_recognize"),
        (60.1, 10_485_760, "batch_recognize"),
        (60.1, 10_485_761, "batch_recognize"),
        (3600.0, 1, "batch_recognize"),
    ],
)
def test_google_adapter_routes_using_normalized_duration_and_size_boundaries(
    duration_seconds: float,
    size_bytes: int,
    expected_method: str,
) -> None:
    client = FakeBatchClient(operation=FakeBatchOperation())
    adapter = GoogleSpeechToTextAdapter(
        client=client,
        project_id="test-project",
        temporary_audio_store=FakeTemporaryStore(),
    )

    result = adapter.transcribe(
        SizedAudioPath(size_bytes),  # type: ignore[arg-type]
        duration_seconds=duration_seconds,
        attempt_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    )

    if expected_method == "recognize":
        assert isinstance(result, TranscriptionResult)
        assert client.recognize_calls == 1
        assert client.batch_calls == 0
    else:
        assert isinstance(result, BatchSubmissionResult)
        assert client.recognize_calls == 0
        assert client.batch_calls == 1


def test_batch_submission_has_exact_operation_name_and_does_not_wait() -> None:
    store = FakeTemporaryStore()
    client = FakeBatchClient(operation=FakeBatchOperation())
    adapter = GoogleSpeechToTextAdapter(
        client=client,
        project_id="test-project",
        temporary_audio_store=store,
    )

    result = adapter.transcribe(
        SizedAudioPath(1),  # type: ignore[arg-type]
        language_hint=None,
        duration_seconds=60.1,
        attempt_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    )

    assert result == BatchSubmissionResult(
        provider="google",
        model="chirp_3",
        provider_request_id="projects/123/locations/us/operations/v2-test-operation",
        state="processing",
    )
    assert client.batch_retry is None
    assert client.batch_request == {
        "recognizer": "projects/test-project/locations/us/recognizers/_",
        "config": {
            "auto_decoding_config": {},
            "language_codes": ["pt-BR"],
            "model": "chirp_3",
            "features": {"enable_automatic_punctuation": True},
        },
        "files": [
            {
                "uri": "gs://test-temp-bucket/f6/transcription/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/audio.wav"
            }
        ],
        "recognition_output_config": {"inline_response_config": {}},
    }
    assert len(store.upload_calls) == 1
    assert store.upload_calls[0][0] == "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    assert getattr(store.upload_calls[0][1], "_size") == 1
    assert store.delete_calls == 0


def test_batch_requires_configured_temporary_bucket_without_calling_provider() -> None:
    client = FakeBatchClient(operation=FakeBatchOperation())
    adapter = GoogleSpeechToTextAdapter(client=client, project_id="test-project")

    with pytest.raises(SpeechToTextError) as raised:
        adapter.transcribe(
            SizedAudioPath(1),  # type: ignore[arg-type]
            duration_seconds=60.1,
            attempt_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        )

    assert raised.value.error_code == "STT_BATCH_CONFIGURATION_REQUIRED"
    assert client.batch_calls == 0


def test_batch_duration_above_one_hour_fails_without_upload_or_submission() -> None:
    client = FakeBatchClient(operation=FakeBatchOperation())
    store = FakeTemporaryStore()
    adapter = GoogleSpeechToTextAdapter(
        client=client,
        project_id="test-project",
        temporary_audio_store=store,
    )

    with pytest.raises(SpeechToTextError) as raised:
        adapter.transcribe(
            SizedAudioPath(1),  # type: ignore[arg-type]
            duration_seconds=3600.1,
            attempt_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        )

    assert raised.value.error_code == "STT_BATCH_UNSUPPORTED_DURATION"
    assert store.upload_calls == []
    assert client.batch_calls == 0


def test_batch_object_collision_fails_without_provider_submission() -> None:
    class ConflictStore(FakeTemporaryStore):
        def upload(self, *, attempt_id: object, path: Path) -> TemporaryAudioObject:
            raise TemporaryAudioStoreError(
                "STT_BATCH_OBJECT_CONFLICT", "Temporary object already exists"
            )

    client = FakeBatchClient(operation=FakeBatchOperation())
    adapter = GoogleSpeechToTextAdapter(
        client=client,
        project_id="test-project",
        temporary_audio_store=ConflictStore(),
    )

    with pytest.raises(SpeechToTextError) as raised:
        adapter.transcribe(
            SizedAudioPath(1),  # type: ignore[arg-type]
            duration_seconds=60.1,
            attempt_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        )

    assert raised.value.error_code == "STT_BATCH_OBJECT_CONFLICT"
    assert client.batch_calls == 0


def test_ambiguous_batch_submission_is_not_resubmitted_or_cleaned_up() -> None:
    store = FakeTemporaryStore()
    client = FakeBatchClient(error=TimeoutError("secret transport detail"))
    adapter = GoogleSpeechToTextAdapter(
        client=client,
        project_id="test-project",
        temporary_audio_store=store,
    )

    with pytest.raises(SpeechToTextError) as raised:
        adapter.transcribe(
            SizedAudioPath(1),  # type: ignore[arg-type]
            duration_seconds=60.1,
            attempt_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        )

    assert raised.value.error_code == "STT_BATCH_SUBMISSION_UNKNOWN"
    assert "secret" not in str(raised.value)
    assert client.batch_calls == 1
    assert len(store.upload_calls) == 1
    assert store.delete_calls == 0


def test_reconciliation_pending_reads_exact_operation_once_without_submission() -> None:
    operation_name = "projects/123/locations/us/operations/v2-test-operation"

    class OperationsClient:
        calls: list[tuple[str, object]] = []

        def get_operation(self, *, name: str, retry: object) -> object:
            self.calls.append((name, retry))
            return type("Operation", (), {"done": False, "name": operation_name})()

    class Client:
        transport = type("Transport", (), {"operations_client": OperationsClient()})()

        def batch_recognize(self, **_kwargs: object) -> None:
            raise AssertionError("reconciliation must not submit batch work")

        def recognize(self, **_kwargs: object) -> None:
            raise AssertionError("reconciliation must not call synchronous recognize")

    result = GoogleSpeechToTextAdapter(
        client=Client(), project_id="test-project"
    ).reconcile_batch(provider_request_id=operation_name)

    assert result == BatchReconciliationResult(
        state="pending",
        provider="google",
        model="chirp_3",
        provider_request_id=operation_name,
        transcript_text=None,
        transcript_language=None,
    )
    assert Client.transport.operations_client.calls == [(operation_name, None)]


def test_reconciliation_terminal_success_uses_result_map_key_without_deprecated_uri() -> None:
    from google.cloud import speech_v2
    from google.longrunning import operations_pb2

    operation_name = "projects/123/locations/us/operations/v2-test-operation"
    input_uri = "gs://test-temp-bucket/f6/transcription/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/audio.wav"
    response = speech_v2.types.BatchRecognizeResponse(
        results={
            input_uri: speech_v2.types.BatchRecognizeFileResult(
                inline_result=speech_v2.types.InlineResult(
                    transcript=speech_v2.types.BatchRecognizeResults(
                        results=[
                            speech_v2.types.SpeechRecognitionResult(
                                alternatives=[
                                    speech_v2.types.SpeechRecognitionAlternative(
                                        transcript="primeira parte"
                                    )
                                ],
                                language_code="",
                            ),
                            speech_v2.types.SpeechRecognitionResult(
                                alternatives=[
                                    speech_v2.types.SpeechRecognitionAlternative(
                                        transcript="segunda parte"
                                    )
                                ],
                                language_code="pt-BR",
                            ),
                        ]
                    )
                ),
            )
        }
    )
    operation = operations_pb2.Operation(name=operation_name, done=True)
    operation.response.Pack(speech_v2.types.BatchRecognizeResponse.pb(response))

    class OperationsClient:
        def get_operation(self, *, name: str, retry: object) -> object:
            assert name == operation_name
            assert retry is None
            return operation

    class Client:
        transport = type("Transport", (), {"operations_client": OperationsClient()})()

        def batch_recognize(self, **_kwargs: object) -> None:
            raise AssertionError("reconciliation must not submit batch work")

        def recognize(self, **_kwargs: object) -> None:
            raise AssertionError("reconciliation must not call synchronous recognize")

    result = GoogleSpeechToTextAdapter(
        client=Client(), project_id="test-project"
    ).reconcile_batch(
        provider_request_id=operation_name,
        expected_input_uri=input_uri,
    )

    assert result == BatchReconciliationResult(
        state="terminal_success",
        provider="google",
        model="chirp_3",
        provider_request_id=operation_name,
        transcript_text="primeira parte segunda parte",
        transcript_language="pt-BR",
    )


def test_reconciliation_terminal_success_rejects_unexpected_result_map_key() -> None:
    from google.cloud import speech_v2
    from google.longrunning import operations_pb2

    operation_name = "projects/123/locations/us/operations/v2-test-operation"
    expected_input_uri = (
        "gs://test-temp-bucket/f6/transcription/"
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/audio.wav"
    )
    other_input_uri = (
        "gs://test-temp-bucket/f6/transcription/"
        "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb/audio.wav"
    )
    response = speech_v2.types.BatchRecognizeResponse(
        results={
            other_input_uri: speech_v2.types.BatchRecognizeFileResult(
                inline_result=speech_v2.types.InlineResult(
                    transcript=speech_v2.types.BatchRecognizeResults()
                ),
            )
        }
    )
    operation = operations_pb2.Operation(name=operation_name, done=True)
    operation.response.Pack(speech_v2.types.BatchRecognizeResponse.pb(response))

    class OperationsClient:
        def get_operation(self, *, name: str, retry: object) -> object:
            assert name == operation_name
            assert retry is None
            return operation

    class Client:
        transport = type("Transport", (), {"operations_client": OperationsClient()})()

        def batch_recognize(self, **_kwargs: object) -> None:
            raise AssertionError("reconciliation must not submit batch work")

        def recognize(self, **_kwargs: object) -> None:
            raise AssertionError("reconciliation must not call synchronous recognize")

    with pytest.raises(ReconciliationError) as raised:
        GoogleSpeechToTextAdapter(
            client=Client(), project_id="test-project"
        ).reconcile_batch(
            provider_request_id=operation_name,
            expected_input_uri=expected_input_uri,
        )

    assert raised.value.error_code == "STT_RECONCILIATION_INVALID_RESPONSE"
    assert raised.value.retryable is False


def test_reconciliation_terminal_operation_error_is_explicit_provider_failure() -> None:
    from google.longrunning import operations_pb2
    from google.rpc import status_pb2

    operation_name = "projects/123/locations/us/operations/v2-test-operation"
    operation = operations_pb2.Operation(name=operation_name, done=True)
    operation.error.CopyFrom(status_pb2.Status(code=13, message="raw provider detail"))

    class OperationsClient:
        def get_operation(self, *, name: str, retry: object) -> object:
            assert name == operation_name
            assert retry is None
            return operation

    class Client:
        transport = type("Transport", (), {"operations_client": OperationsClient()})()

        def batch_recognize(self, **_kwargs: object) -> None:
            raise AssertionError("reconciliation must not submit batch work")

        def recognize(self, **_kwargs: object) -> None:
            raise AssertionError("reconciliation must not call synchronous recognize")

    result = GoogleSpeechToTextAdapter(
        client=Client(), project_id="test-project"
    ).reconcile_batch(
        provider_request_id=operation_name,
        expected_input_uri="gs://test-temp-bucket/f6/transcription/test/audio.wav",
    )

    assert result == BatchReconciliationResult(
        state="terminal_provider_failure",
        provider="google",
        model="chirp_3",
        provider_request_id=operation_name,
        transcript_text=None,
        transcript_language=None,
    )
