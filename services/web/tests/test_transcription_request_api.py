from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main, reels
from app.auth import config, dependencies, repository
from app.csrf import CSRF_COOKIE_NAME
from app.reel_lifecycle import LifecycleStatusError


CSRF_TOKEN = "valid-api-csrf-token"


def owner_client(monkeypatch) -> TestClient:
    monkeypatch.setattr(
        dependencies.repository,
        "resolve_session",
        lambda *_: repository.SessionIdentity(7, "owner@example.com"),
    )
    client = TestClient(main.app, base_url="https://testserver")
    client.cookies.set(config.SESSION_COOKIE_NAME, "valid-owner-session")
    client.cookies.set(CSRF_COOKIE_NAME, CSRF_TOKEN)
    return client


def lifecycle(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "id": 42,
        "download_status": "downloaded",
        "curation_status": "inbox",
        "transcription_status": "queued",
    }
    value.update(overrides)
    return value


def result(outcome: str, **overrides: object) -> SimpleNamespace:
    return SimpleNamespace(outcome=outcome, lifecycle=lifecycle(**overrides))


def request_headers() -> dict[str, str]:
    return {"Content-Type": "application/json", "X-CSRF-Token": CSRF_TOKEN}


def test_owner_can_queue_a_downloaded_reel(monkeypatch) -> None:
    client = owner_client(monkeypatch)
    queued = lifecycle()
    monkeypatch.setattr(
        main,
        "request_transcription",
        lambda reel_id: SimpleNamespace(outcome="accepted_new_request", lifecycle=queued),
    )

    response = client.post("/api/reels/42/transcription", content=b"{}", headers=request_headers())

    assert response.status_code == 202
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == queued


def test_transcription_request_requires_owner_before_csrf_or_domain_access(monkeypatch) -> None:
    calls: list[int] = []
    monkeypatch.setattr(main, "request_transcription", lambda reel_id: calls.append(reel_id))
    client = TestClient(main.app, base_url="https://testserver")
    client.cookies.set(CSRF_COOKIE_NAME, CSRF_TOKEN)

    response = client.post("/api/reels/42/transcription", content=b"{}", headers=request_headers())

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}
    assert calls == []


@pytest.mark.parametrize("token", [None, "invalid-api-csrf-token"])
def test_transcription_request_requires_csrf_before_domain_access(monkeypatch, token: str | None) -> None:
    client = owner_client(monkeypatch)
    monkeypatch.setattr(
        main,
        "request_transcription",
        lambda *_: pytest.fail("CSRF failure must not reach the domain"),
    )
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["X-CSRF-Token"] = token

    response = client.post("/api/reels/42/transcription", content=b"{}", headers=headers)

    assert response.status_code == 403
    assert response.json() == {"detail": "CSRF token validation failed"}


@pytest.mark.parametrize(
    "body",
    [
        b"{",
        b"[]",
        b"null",
        b'{"provider":"google"}',
        b'{"transcription_status":"completed"}',
        b'{"force":true}',
        b'{"status":"queued"}',
        b'{"language":"en"}',
        b'{"operation_id":"client-id"}',
    ],
)
def test_transcription_request_rejects_non_strict_json_before_domain_access(monkeypatch, body: bytes) -> None:
    client = owner_client(monkeypatch)
    monkeypatch.setattr(
        main,
        "request_transcription",
        lambda *_: pytest.fail("invalid request must not reach the domain"),
    )

    response = client.post("/api/reels/42/transcription", content=body, headers=request_headers())

    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "error": {"code": "invalid_request", "message": "Invalid transcription request"}
    }


@pytest.mark.parametrize("content_type", [None, "text/plain"])
def test_transcription_request_requires_json_content_type_before_domain_access(
    monkeypatch, content_type: str | None
) -> None:
    client = owner_client(monkeypatch)
    monkeypatch.setattr(
        main,
        "request_transcription",
        lambda *_: pytest.fail("invalid media type must not reach the domain"),
    )
    headers = {"X-CSRF-Token": CSRF_TOKEN}
    if content_type is not None:
        headers["Content-Type"] = content_type

    response = client.post("/api/reels/42/transcription", content=b"{}", headers=headers)

    assert response.status_code == 422


def test_eligible_transcription_request_returns_accepted(monkeypatch) -> None:
    client = owner_client(monkeypatch)
    calls: list[int] = []
    queued = lifecycle(curation_status="organized")
    monkeypatch.setattr(
        main,
        "request_transcription",
        lambda reel_id: calls.append(reel_id)
        or SimpleNamespace(outcome="accepted_new_request", lifecycle=queued),
    )

    response = client.post("/api/reels/42/transcription", content=b"{}", headers=request_headers())

    assert response.status_code == 202
    assert response.json() == queued
    assert calls == [42]
    assert queued["download_status"] == "downloaded"
    assert queued["curation_status"] == "organized"
    assert queued["transcription_status"] == "queued"


@pytest.mark.parametrize(
    "outcome,status",
    [
        ("already_queued", "queued"),
        ("already_processing", "processing"),
        ("already_completed", "completed"),
    ],
)
def test_idempotent_transcription_states_return_current_lifecycle(
    monkeypatch, outcome: str, status: str
) -> None:
    client = owner_client(monkeypatch)
    current = lifecycle(transcription_status=status)
    monkeypatch.setattr(main, "request_transcription", lambda _: SimpleNamespace(outcome=outcome, lifecycle=current))

    response = client.post("/api/reels/42/transcription", content=b"{}", headers=request_headers())

    assert response.status_code == 200
    assert response.json() == current


@pytest.mark.parametrize("download_status", ["received", "downloading", "failed"])
def test_not_downloaded_reel_returns_conflict_without_lifecycle_mutation(
    monkeypatch, download_status: str
) -> None:
    client = owner_client(monkeypatch)
    current = lifecycle(download_status=download_status, transcription_status="not_requested")
    monkeypatch.setattr(main, "request_transcription", lambda _: SimpleNamespace(outcome="not_ready", lifecycle=current))

    response = client.post("/api/reels/42/transcription", content=b"{}", headers=request_headers())

    assert response.status_code == 409
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "error": {"code": "reel_not_ready", "message": "Reel is not ready for transcription"}
    }
    assert current["transcription_status"] == "not_requested"


def test_missing_reel_returns_bounded_not_found(monkeypatch) -> None:
    client = owner_client(monkeypatch)
    monkeypatch.setattr(main, "request_transcription", lambda _: SimpleNamespace(outcome="not_found", lifecycle=None))

    response = client.post("/api/reels/999/transcription", content=b"{}", headers=request_headers())

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "reel_not_found", "message": "Reel not found"}}


def test_database_or_inconsistent_lifecycle_is_bounded_as_unavailable(monkeypatch) -> None:
    client = owner_client(monkeypatch)
    monkeypatch.setattr(
        main,
        "request_transcription",
        lambda _: (_ for _ in ()).throw(LifecycleStatusError("private lifecycle failure")),
    )

    response = client.post("/api/reels/42/transcription", content=b"{}", headers=request_headers())

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "transcription_request_unavailable",
            "message": "Transcription request temporarily unavailable",
        }
    }
    assert "private lifecycle failure" not in response.text


def test_unknown_domain_outcome_fails_closed(monkeypatch) -> None:
    client = owner_client(monkeypatch)
    monkeypatch.setattr(main, "request_transcription", lambda _: result("unexpected"))

    response = client.post("/api/reels/42/transcription", content=b"{}", headers=request_headers())

    assert response.status_code == 503


@pytest.mark.parametrize("initial_status", ["not_requested", "failed"])
def test_request_repository_uses_one_atomic_transition_then_observes_current_state(
    initial_status: str,
) -> None:
    calls: list[tuple[str, tuple[int]]] = []
    durable_mutations: list[str] = []
    state = {"transcription_status": initial_status}

    class FakeCursor:
        current: dict[str, object] | None = None

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execute(self, query: str, parameters: tuple[int]) -> None:
            calls.append((query, parameters))
            if query == reels.REQUEST_TRANSCRIPTION_QUERY:
                if state["transcription_status"] in {"not_requested", "failed"}:
                    state["transcription_status"] = "queued"
                    durable_mutations.append("queued")
                    self.current = lifecycle()
                else:
                    self.current = None
            else:
                self.current = {
                    **lifecycle(transcription_status=state["transcription_status"]),
                    "transcription_attempt_id": None,
                }

        def fetchone(self):
            return self.current

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def cursor(self, *, row_factory):
            return FakeCursor()

    original_connect = reels.database.connect
    reels.database.connect = lambda: FakeConnection()
    try:
        first = reels.request_transcription(42)
        second = reels.request_transcription(42)
    finally:
        reels.database.connect = original_connect

    assert first.outcome == "accepted_new_request"
    assert second.outcome == "already_queued"
    assert durable_mutations == ["queued"]
    assert calls == [
        (reels.REQUEST_TRANSCRIPTION_QUERY, (42,)),
        (reels.REQUEST_TRANSCRIPTION_QUERY, (42,)),
        (reels.REQUEST_TRANSCRIPTION_LIFECYCLE_QUERY, (42,)),
    ]


def test_request_repository_mutation_preserves_independent_lifecycles_and_attempt_history() -> None:
    mutation = reels.REQUEST_TRANSCRIPTION_QUERY.split("WHERE", 1)[0]

    assert "UPDATE app.reels" in reels.REQUEST_TRANSCRIPTION_QUERY
    assert "transcription_status = 'queued'" in mutation
    assert "transcription_attempt_id = NULL" in mutation
    assert "updated_at = NOW()" in mutation
    assert "download_status" not in mutation
    assert "curation_status" not in mutation
    assert "reel_enrichment_attempts" not in reels.REQUEST_TRANSCRIPTION_QUERY
    assert "reel_enrichments" not in reels.REQUEST_TRANSCRIPTION_QUERY
    assert "INSERT" not in reels.REQUEST_TRANSCRIPTION_QUERY
    assert "DELETE" not in reels.REQUEST_TRANSCRIPTION_QUERY


def test_request_repository_requires_downloaded_eligible_state_and_has_no_dispatch() -> None:
    query = reels.REQUEST_TRANSCRIPTION_QUERY

    assert "download_status = 'downloaded'" in query
    assert "transcription_status IN ('not_requested', 'failed')" in query
    assert "transcription_attempt_id IS NULL" in query
    assert "dispatch" not in query.lower()
    assert "n8n" not in query.lower()
    assert "gcs" not in query.lower()


@pytest.mark.parametrize(
    "row",
    [
        {
            **lifecycle(download_status="unknown"),
            "transcription_attempt_id": None,
        },
        {
            **lifecycle(transcription_status="processing"),
            "transcription_attempt_id": None,
        },
        {
            **lifecycle(transcription_status="queued"),
            "transcription_attempt_id": "unexpected-attempt",
        },
        {
            **lifecycle(curation_status="unknown"),
            "transcription_attempt_id": None,
        },
    ],
)
def test_request_repository_fails_closed_for_unknown_or_inconsistent_lifecycle(
    row: dict[str, object]
) -> None:
    with pytest.raises(LifecycleStatusError):
        reels._classify_transcription_lifecycle(row)


def test_transcription_request_endpoint_does_not_dispatch_processing(monkeypatch) -> None:
    client = owner_client(monkeypatch)
    monkeypatch.setattr(main, "request_transcription", lambda _: result("accepted_new_request"))
    monkeypatch.setattr(main, "load_dispatch_settings", lambda: pytest.fail("TC1 must not dispatch"))
    monkeypatch.setattr(main, "dispatch_reel", lambda *_: pytest.fail("TC1 must not dispatch"))

    response = client.post("/api/reels/42/transcription", content=b"{}", headers=request_headers())

    assert response.status_code == 202


def test_transcription_request_openapi_contract_is_owner_csrf_and_strict() -> None:
    main.app.openapi_schema = None
    operation = main.app.openapi()["paths"]["/api/reels/{reel_id}/transcription"]["post"]

    assert operation["security"] == [{"OwnerSessionCookie": []}]
    assert operation["requestBody"] == {
        "required": True,
        "content": {
            "application/json": {
                "schema": {"type": "object", "properties": {}, "additionalProperties": False}
            }
        },
    }
    assert {"200", "202", "401", "403", "404", "409", "422", "503"} <= set(operation["responses"])
    assert [
        parameter
        for parameter in operation["parameters"]
        if parameter["in"] == "header" and parameter["name"] == "X-CSRF-Token"
    ] == [
        {
            "name": "X-CSRF-Token",
            "in": "header",
            "required": True,
            "schema": {"type": "string", "title": "X-Csrf-Token"},
        }
    ]
