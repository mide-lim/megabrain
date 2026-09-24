from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import main
from app.stt.base import ReconciliationError, SpeechToTextError

main.API_KEY = "test-key"
client = TestClient(main.app)


def raise_unexpected_error() -> None:
    raise RuntimeError("internal sensitive detail")


def raise_service_unavailable() -> None:
    raise HTTPException(
        status_code=503,
        detail="upstream sensitive detail",
        headers={"Retry-After": "30"},
    )


main.app.add_api_route(
    "/_tests/unexpected-error",
    raise_unexpected_error,
    methods=["GET"],
    include_in_schema=False,
)
main.app.add_api_route(
    "/_tests/service-unavailable",
    raise_service_unavailable,
    methods=["GET"],
    include_in_schema=False,
)


def enrichment_payload(attempt_id: UUID) -> dict[str, object]:
    return {
        "contract_version": "1.0",
        "attempt_id": str(attempt_id),
        "reel_id": 42,
        "shortcode": "ABC_123-x",
        "object_key": "original/instagram/reels/ABC_123-x/video.mp4",
        "expected_sha256": "a" * 64,
        "expected_size_bytes": 1234,
        "pipeline_version": "sprint-3-v1",
        "language_hint": "pt-BR",
    }


def expected_error(attempt_id: UUID | None) -> set[str]:
    return {"error_code", "stage", "message", "retryable", "attempt_id"}


def test_health() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "version": "0.1.0"}


def test_framework_http_errors_use_structured_envelope() -> None:
    response = client.get("/route-that-does-not-exist")

    assert response.status_code == 404
    assert response.json() == {
        "error_code": "INVALID_REQUEST",
        "stage": "input",
        "message": "Request could not be processed",
        "retryable": False,
        "attempt_id": None,
    }


def test_method_not_allowed_preserves_allow_header() -> None:
    response = client.post("/health")

    assert response.status_code == 405
    assert response.headers["Allow"] == "GET"
    assert response.json()["error_code"] == "INVALID_REQUEST"


def test_server_http_error_preserves_headers_and_is_retryable() -> None:
    response = client.get("/_tests/service-unavailable")

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "30"
    assert response.json() == {
        "error_code": "INTERNAL_ERROR",
        "stage": "internal",
        "message": "Unexpected internal error",
        "retryable": True,
        "attempt_id": None,
    }


def test_unexpected_errors_use_sanitized_envelope() -> None:
    safe_client = TestClient(main.app, raise_server_exceptions=False)

    response = safe_client.get("/_tests/unexpected-error")

    assert response.status_code == 500
    assert response.json() == {
        "error_code": "INTERNAL_ERROR",
        "stage": "internal",
        "message": "Unexpected internal error",
        "retryable": False,
        "attempt_id": None,
    }


def test_enrichment_requires_authentication_before_pipeline() -> None:
    attempt_id = uuid4()

    response = client.post(
        "/v1/enrichments",
        headers={"Idempotency-Key": str(attempt_id)},
        json=enrichment_payload(attempt_id),
    )

    assert response.status_code == 401
    assert set(response.json()) == expected_error(attempt_id)
    assert response.json() == {
        "error_code": "UNAUTHORIZED",
        "stage": "input",
        "message": "Invalid or missing internal API key",
        "retryable": False,
        "attempt_id": None,
    }


def test_authentication_precedes_body_validation() -> None:
    response = client.post(
        "/v1/enrichments",
        headers={"Content-Type": "application/json"},
        content="not-json",
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == "UNAUTHORIZED"
    assert response.json()["attempt_id"] is None


def test_enrichment_rejects_mismatched_idempotency_key() -> None:
    attempt_id = uuid4()

    response = client.post(
        "/v1/enrichments",
        headers={
            "X-MegaBrain-Key": "test-key",
            "Idempotency-Key": str(uuid4()),
        },
        json=enrichment_payload(attempt_id),
    )

    assert response.status_code == 409
    assert response.json() == {
        "error_code": "ATTEMPT_CONFLICT",
        "stage": "input",
        "message": "Idempotency-Key must match attempt_id",
        "retryable": False,
        "attempt_id": str(attempt_id),
    }


def test_enrichment_requires_json_content_type() -> None:
    attempt_id = uuid4()

    response = client.post(
        "/v1/enrichments",
        headers={
            "X-MegaBrain-Key": "test-key",
            "Idempotency-Key": str(attempt_id),
            "Content-Type": "text/plain",
        },
        content="not json",
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == "INVALID_REQUEST"
    assert response.json()["stage"] == "input"


def test_enrichment_rejects_invalid_request_with_stable_error() -> None:
    attempt_id = uuid4()
    payload = enrichment_payload(attempt_id)
    payload["expected_sha256"] = "not-a-sha256"

    response = client.post(
        "/v1/enrichments",
        headers={
            "X-MegaBrain-Key": "test-key",
            "Idempotency-Key": str(attempt_id),
        },
        json=payload,
    )

    assert response.status_code == 422
    body = response.json()
    assert set(body) == expected_error(attempt_id)
    assert body["error_code"] == "INVALID_REQUEST"
    assert body["stage"] == "input"
    assert body["retryable"] is False
    assert body["attempt_id"] == str(attempt_id)
    assert "success" not in body


def test_enrichment_contract_excludes_removed_fields() -> None:
    attempt_id = uuid4()
    payload = enrichment_payload(attempt_id)
    payload["timestamps"] = "segment"
    payload["timestamps_mode"] = "segment"
    payload["transcript_segments"] = []

    response = client.post(
        "/v1/enrichments",
        headers={
            "X-MegaBrain-Key": "test-key",
            "Idempotency-Key": str(attempt_id),
        },
        json=payload,
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == "INVALID_REQUEST"


def test_enrichment_returns_completed_pipeline_response(
    monkeypatch,
) -> None:
    attempt_id = uuid4()
    completed = datetime.now(timezone.utc).isoformat()
    result = main.EnrichmentResponse.model_validate(
        {
            "contract_version": "1.0",
            "attempt_id": attempt_id,
            "reel_id": 42,
            "shortcode": "ABC_123-x",
            "pipeline_version": "sprint-3-v1",
            "processor_version": main.VERSION,
            "source": {
                "object_key": enrichment_payload(attempt_id)["object_key"],
                "sha256": "a" * 64,
                "size_bytes": 1234,
            },
            "media": {
                "container_format": "mp4",
                "duration_seconds": 1,
                "video": {"codec": "h264", "width": 1080, "height": 1920},
                "audio": None,
            },
            "transcription_input": None,
            "transcription": {
                "outcome": "no_audio",
                "transcript_text": None,
                "transcript_language": None,
                "engine": {"provider": None, "model": None, "request_id": None},
            },
            "processing": {"started_at": completed, "completed_at": completed},
            "warnings": [],
        }
    )
    monkeypatch.setattr(main, "process_source", lambda *_args, **_kwargs: result)
    monkeypatch.setattr(main, "_r2_client", lambda: object())
    monkeypatch.setattr(main, "_stt_adapter", lambda: object())
    monkeypatch.setenv("R2_BUCKET", "test-bucket")

    response = client.post(
        "/v1/enrichments",
        headers={
            "X-MegaBrain-Key": "test-key",
            "Idempotency-Key": str(attempt_id),
        },
        json=enrichment_payload(attempt_id),
    )

    assert response.status_code == 200
    assert response.json()["transcription"]["outcome"] == "no_audio"
    assert "success" not in response.json()


def test_enrichment_returns_pending_batch_submission_response(monkeypatch) -> None:
    attempt_id = uuid4()
    pending = main.BatchEnrichmentResponse.model_validate(
        {
            "contract_version": "1.0",
            "attempt_id": attempt_id,
            "reel_id": 42,
            "shortcode": "ABC_123-x",
            "pipeline_version": "sprint-3-v1",
            "processor_version": main.VERSION,
            "source": {
                "object_key": enrichment_payload(attempt_id)["object_key"],
                "sha256": "a" * 64,
                "size_bytes": 1234,
            },
            "media": {
                "container_format": "mp4",
                "duration_seconds": 60.1,
                "video": {"codec": "h264", "width": 1080, "height": 1920},
                "audio": {"codec": "aac", "sample_rate_hz": 48_000, "channels": 2},
            },
            "transcription_input": {
                "format": "wav",
                "sample_rate_hz": 48_000,
                "channels": 1,
                "duration_seconds": 60.1,
            },
            "batch_submission": {
                "state": "processing",
                "provider": "google",
                "model": "chirp_3",
                "provider_request_id": "projects/123/locations/us/operations/v2-test-operation",
            },
            "warnings": [],
        }
    )
    monkeypatch.setattr(main, "process_source", lambda *_args, **_kwargs: pending)
    monkeypatch.setattr(main, "_r2_client", lambda: object())
    monkeypatch.setattr(main, "_stt_adapter", lambda: object())
    monkeypatch.setenv("R2_BUCKET", "test-bucket")

    response = client.post(
        "/v1/enrichments",
        headers={
            "X-MegaBrain-Key": "test-key",
            "Idempotency-Key": str(attempt_id),
        },
        json=enrichment_payload(attempt_id),
    )

    assert response.status_code == 202
    assert response.json()["attempt_id"] == str(attempt_id)
    assert response.json()["reel_id"] == 42
    assert response.json()["source"]["object_key"] == enrichment_payload(attempt_id)[
        "object_key"
    ]
    assert response.json()["batch_submission"] == {
        "state": "processing",
        "provider": "google",
        "model": "chirp_3",
        "provider_request_id": "projects/123/locations/us/operations/v2-test-operation",
    }
    assert "transcription" not in response.json()
    assert "processing" not in response.json()


def test_transient_google_error_uses_retryable_transcription_envelope(
    monkeypatch,
) -> None:
    attempt_id = uuid4()

    def fail_transcription(*_args, **_kwargs):
        raise SpeechToTextError(
            "STT_UNAVAILABLE",
            "Transcription service unavailable",
            retryable=True,
        )

    monkeypatch.setattr(main, "process_source", fail_transcription)
    monkeypatch.setattr(main, "_r2_client", lambda: object())
    monkeypatch.setattr(main, "_stt_adapter", lambda: object())
    monkeypatch.setenv("R2_BUCKET", "test-bucket")

    response = client.post(
        "/v1/enrichments",
        headers={
            "X-MegaBrain-Key": "test-key",
            "Idempotency-Key": str(attempt_id),
        },
        json=enrichment_payload(attempt_id),
    )

    assert response.status_code == 503
    assert response.json() == {
        "error_code": "STT_UNAVAILABLE",
        "stage": "transcription",
        "message": "Transcription service unavailable",
        "retryable": True,
        "attempt_id": str(attempt_id),
    }


def test_non_transient_google_error_uses_transcription_envelope(monkeypatch) -> None:
    attempt_id = uuid4()

    def fail_transcription(*_args, **_kwargs):
        raise SpeechToTextError(
            "STT_REQUEST_REJECTED",
            "Transcription request rejected",
            retryable=False,
        )

    monkeypatch.setattr(main, "process_source", fail_transcription)
    monkeypatch.setattr(main, "_r2_client", lambda: object())
    monkeypatch.setattr(main, "_stt_adapter", lambda: object())
    monkeypatch.setenv("R2_BUCKET", "test-bucket")

    response = client.post(
        "/v1/enrichments",
        headers={
            "X-MegaBrain-Key": "test-key",
            "Idempotency-Key": str(attempt_id),
        },
        json=enrichment_payload(attempt_id),
    )

    assert response.status_code == 422
    assert response.json() == {
        "error_code": "STT_REQUEST_REJECTED",
        "stage": "transcription",
        "message": "Transcription request rejected",
        "retryable": False,
        "attempt_id": str(attempt_id),
    }


def test_openapi_contract_has_only_approved_error_stages_and_fields() -> None:
    schema = client.get("/openapi.json").json()
    schemas = schema["components"]["schemas"]

    assert set(schema["paths"]["/v1/enrichments"]["post"]["responses"]) == {
        "200",
        "202",
        "401",
        "404",
        "409",
        "422",
        "429",
        "500",
        "503",
        "504",
    }

    assert set(schemas["ErrorStage"]["enum"]) == {
        "input",
        "r2_download",
        "integrity",
        "probe",
        "audio_extract",
        "transcription",
        "internal",
    }
    request_properties = schemas["EnrichmentRequest"]["properties"]
    assert "timestamps" not in request_properties
    assert "timestamps_mode" not in request_properties
    response_properties = schemas["EnrichmentResponse"]["properties"]
    transcription_ref = response_properties["transcription"]["$ref"].split("/")[-1]
    transcription_properties = schemas[transcription_ref]["properties"]
    assert set(transcription_properties) == {
        "outcome",
        "transcript_text",
        "transcript_language",
        "engine",
    }
    assert "processing" in response_properties
    assert "transcription_engine" not in response_properties
    assert "success" not in response_properties
    outcome_schema = transcription_properties["outcome"]
    assert set(outcome_schema["enum"]) == {
        "transcribed",
        "no_audio",
        "empty_transcript",
    }


def reconciliation_payload(attempt_id: UUID) -> dict[str, object]:
    return {
        **enrichment_payload(attempt_id),
        "provider_request_id": "projects/123/locations/us/operations/v2-test-operation",
    }


def test_reconciliation_requires_exact_auth_content_type_and_idempotency(
    monkeypatch,
) -> None:
    attempt_id = uuid4()
    payload = reconciliation_payload(attempt_id)
    called = False

    def should_not_reconcile(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("reconciliation must not be called")

    monkeypatch.setattr(main, "reconcile_source", should_not_reconcile)

    unauthorized = client.post(
        "/v1/enrichments/reconcile",
        headers={"Idempotency-Key": str(attempt_id)},
        json=payload,
    )
    wrong_content_type = client.post(
        "/v1/enrichments/reconcile",
        headers={
            "X-MegaBrain-Key": "test-key",
            "Idempotency-Key": str(attempt_id),
            "Content-Type": "text/plain",
        },
        content="not-json",
    )
    mismatch = client.post(
        "/v1/enrichments/reconcile",
        headers={
            "X-MegaBrain-Key": "test-key",
            "Idempotency-Key": str(uuid4()),
        },
        json=payload,
    )

    assert unauthorized.status_code == 401
    assert wrong_content_type.status_code == 422
    assert mismatch.status_code == 409
    assert mismatch.json()["error_code"] == "ATTEMPT_CONFLICT"
    assert called is False


def test_reconciliation_returns_correlated_pending_response(monkeypatch) -> None:
    attempt_id = uuid4()
    payload = reconciliation_payload(attempt_id)
    pending = main.ReconciliationPendingResponse.model_validate(
        {
            "contract_version": "1.0",
            "attempt_id": attempt_id,
            "reel_id": 42,
            "shortcode": "ABC_123-x",
            "pipeline_version": "sprint-3-v1",
            "source": {
                "object_key": payload["object_key"],
                "sha256": "a" * 64,
                "size_bytes": 1234,
            },
            "batch_submission": {
                "state": "processing",
                "provider": "google",
                "model": "chirp_3",
                "provider_request_id": payload["provider_request_id"],
            },
        }
    )
    monkeypatch.setattr(main, "reconcile_source", lambda *_args, **_kwargs: pending)
    monkeypatch.setattr(main, "_r2_client", lambda: object())
    monkeypatch.setattr(main, "_stt_adapter", lambda: object())
    monkeypatch.setenv("R2_BUCKET", "test-bucket")

    response = client.post(
        "/v1/enrichments/reconcile",
        headers={"X-MegaBrain-Key": "test-key", "Idempotency-Key": str(attempt_id)},
        json=payload,
    )

    assert response.status_code == 202
    assert response.json()["attempt_id"] == str(attempt_id)
    assert response.json()["batch_submission"]["provider_request_id"] == payload[
        "provider_request_id"
    ]
    assert "transcription" not in response.json()
    assert "processing" not in response.json()


def test_reconciliation_returns_explicit_provider_terminal_failure(monkeypatch) -> None:
    attempt_id = uuid4()
    payload = reconciliation_payload(attempt_id)
    failure = main.ReconciliationErrorResponse(
        error_code="STT_BATCH_PROVIDER_FAILED",
        stage=main.ErrorStage.TRANSCRIPTION,
        message="Batch transcription provider failed",
        retryable=False,
        attempt_id=attempt_id,
        reel_id=42,
        pipeline_version="sprint-3-v1",
        provider_request_id=str(payload["provider_request_id"]),
        provider_terminal=True,
    )
    monkeypatch.setattr(main, "reconcile_source", lambda *_args, **_kwargs: failure)
    monkeypatch.setattr(main, "_r2_client", lambda: object())
    monkeypatch.setattr(main, "_stt_adapter", lambda: object())
    monkeypatch.setenv("R2_BUCKET", "test-bucket")

    response = client.post(
        "/v1/enrichments/reconcile",
        headers={"X-MegaBrain-Key": "test-key", "Idempotency-Key": str(attempt_id)},
        json=payload,
    )

    assert response.status_code == 502
    assert response.json() == failure.model_dump(mode="json")


def test_reconciliation_control_error_is_never_provider_terminal(monkeypatch) -> None:
    attempt_id = uuid4()
    payload = reconciliation_payload(attempt_id)

    def fail(*_args, **_kwargs):
        raise ReconciliationError(
            "STT_RECONCILIATION_TIMEOUT",
            "Batch transcription reconciliation timed out",
            retryable=True,
        )

    monkeypatch.setattr(main, "reconcile_source", fail)
    monkeypatch.setattr(main, "_r2_client", lambda: object())
    monkeypatch.setattr(main, "_stt_adapter", lambda: object())
    monkeypatch.setenv("R2_BUCKET", "test-bucket")

    response = client.post(
        "/v1/enrichments/reconcile",
        headers={"X-MegaBrain-Key": "test-key", "Idempotency-Key": str(attempt_id)},
        json=payload,
    )

    assert response.status_code == 504
    assert response.json() == {
        "error_code": "STT_RECONCILIATION_TIMEOUT",
        "stage": "transcription",
        "message": "Batch transcription reconciliation timed out",
        "retryable": True,
        "attempt_id": str(attempt_id),
        "reel_id": 42,
        "pipeline_version": "sprint-3-v1",
        "provider_request_id": payload["provider_request_id"],
        "provider_terminal": False,
    }
