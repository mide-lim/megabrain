from __future__ import annotations

from dataclasses import replace

import pytest

from app.control_plane_client import ControlPlaneClient, ControlPlaneRemoteError, ControlPlaneUnavailableError
from app.provider_classifier import ProviderObservation, ProviderState, ReasonCode, UsageWindowSummary
from app.provider_control_plane import ProviderObservationClient, provider_observation_payload
from control_plane_fixture import CORRELATION_ID, ControlPlaneFixture, _module


def _observation(*, state: ProviderState = ProviderState.AVAILABLE, reset_at: str | None = None) -> ProviderObservation:
    return ProviderObservation(
        channel_id="openai_codex",
        provider="openai-codex",
        state=state,
        observed_at="2026-09-30T12:01:00Z",
        provider_fetched_at="2026-09-30T12:00:00Z",
        reset_at=reset_at,
        source="codex account usage",
        reason_code=ReasonCode.USAGE_AVAILABLE if state is ProviderState.AVAILABLE else ReasonCode.USAGE_WINDOW_EXHAUSTED,
        windows_summary=(UsageWindowSummary("5h", 20.0, "2026-09-30T18:00:00Z"),),
        probe_exit_code=0,
        timed_out=False,
    )


def _observer_capability(fixture: ControlPlaneFixture) -> dict:
    return fixture.issuer.issue(
        "observer-record",
        "OBSERVABILITY_ADAPTER",
        "observer",
        ["RecordProviderObservation"],
        "2099-01-01T00:00:00.000Z",
    )


def test_real_uds_observer_record_maps_available_evidence_then_coordinator_preflight_admits(tmp_path) -> None:
    fixture = ControlPlaneFixture(tmp_path)
    try:
        recorded = ProviderObservationClient(fixture.socket_path).record_provider_observation(
            _observation(),
            CORRELATION_ID,
            _observer_capability(fixture),
            idempotency_key="provider-observation-available-1",
        )
        preflight = ControlPlaneClient(fixture.socket_path).evaluate_provider_preflight(
            fixture.task_id,
            CORRELATION_ID,
            "openai_codex",
            fixture.capability(["EvaluateProviderPreflight"]),
        )

        assert recorded == {
            "channel_id": "openai_codex",
            "state": "AVAILABLE",
            "observed_at": "2026-09-30T12:01:00.000Z",
            "reset_at": None,
            "revision": 0,
        }
        assert preflight["decision"] == "ADMIT"
    finally:
        fixture.close()


def test_mapping_never_copies_untrusted_source_provider_or_window_values_into_the_uds_payload() -> None:
    observation = ProviderObservation(
        channel_id="openai_codex",
        provider="sk_live_not_for_metadata",
        state=ProviderState.AVAILABLE,
        observed_at="2026-09-30T12:01:00Z",
        provider_fetched_at="2026-09-30T12:00:00Z",
        reset_at=None,
        source=" codex account usage ",
        reason_code=ReasonCode.USAGE_AVAILABLE,
        windows_summary=(UsageWindowSummary("Bearer secret-value", 20.0, "2026-09-30T18:00:00Z"),),
        probe_exit_code=0,
        timed_out=False,
    )

    payload = provider_observation_payload(observation)

    assert payload["source"] == "hermes_usage_probe"
    assert payload["metadata"]["provider"] is None
    assert payload["metadata"]["windows_summary"] == [
        {"label": "window_1", "used_percent": 20.0, "resets_at": "2026-09-30T18:00:00.000Z"}
    ]


def test_real_uds_persists_adapter_source_for_untrusted_upstream_source(tmp_path) -> None:
    fixture = ControlPlaneFixture(tmp_path)
    try:
        ProviderObservationClient(fixture.socket_path).record_provider_observation(
            replace(_observation(), source="untrusted-source-123456"),
            CORRELATION_ID,
            _observer_capability(fixture),
            idempotency_key="provider-observation-untrusted-source",
        )
        service = _module("service").ControlPlaneService(fixture.database_path)
        try:
            assert service._provider_row("openai_codex")["source"] == "hermes_usage_probe"
        finally:
            service.close()
    finally:
        fixture.close()


def test_real_uds_auth_expired_observation_blocks_coordinator_preflight(tmp_path) -> None:
    fixture = ControlPlaneFixture(tmp_path)
    try:
        ProviderObservationClient(fixture.socket_path).record_provider_observation(
            _observation(state=ProviderState.AUTH_EXPIRED),
            CORRELATION_ID,
            _observer_capability(fixture),
            idempotency_key="provider-observation-auth-expired",
        )
        preflight = ControlPlaneClient(fixture.socket_path).evaluate_provider_preflight(
            fixture.task_id,
            CORRELATION_ID,
            "openai_codex",
            fixture.capability(["EvaluateProviderPreflight"]),
        )

        assert preflight["decision"] == "BLOCK_PROVIDER_AUTH"
    finally:
        fixture.close()


def test_idempotent_provider_replay_keeps_one_revision_and_changed_body_conflicts(tmp_path) -> None:
    fixture = ControlPlaneFixture(tmp_path)
    try:
        client = ProviderObservationClient(fixture.socket_path)
        available = _observation()
        first = client.record_provider_observation(
            available,
            CORRELATION_ID,
            _observer_capability(fixture),
            idempotency_key="provider-observation-idempotent",
        )
        replay = client.record_provider_observation(
            available,
            CORRELATION_ID,
            _observer_capability(fixture),
            idempotency_key="provider-observation-idempotent",
        )

        assert first == replay
        assert first["revision"] == 0
        with pytest.raises(ControlPlaneRemoteError, match="IDEMPOTENCY_CONFLICT"):
            client.record_provider_observation(
                _observation(state=ProviderState.QUOTA_EXHAUSTED, reset_at="2026-09-30T18:00:00Z"),
                CORRELATION_ID,
                _observer_capability(fixture),
                idempotency_key="provider-observation-idempotent",
            )
    finally:
        fixture.close()


def test_control_plane_role_policy_prevents_observer_and_coordinator_privilege_shortcuts(tmp_path) -> None:
    fixture = ControlPlaneFixture(tmp_path)
    try:
        body = provider_observation_payload(_observation())
        with pytest.raises(ControlPlaneRemoteError, match="UNAUTHORIZED"):
            ControlPlaneClient(fixture.socket_path)._request(
                "RecordProviderObservation",
                None,
                CORRELATION_ID,
                fixture.capability(["RecordProviderObservation"]),
                body,
                idempotency_key="coordinator-write-denied",
            )

        observer = ProviderObservationClient(fixture.socket_path)
        with pytest.raises(ControlPlaneRemoteError, match="UNAUTHORIZED"):
            observer._transport._request(
                "EvaluateProviderPreflight",
                fixture.task_id,
                CORRELATION_ID,
                _observer_capability(fixture),
                {"task_id": fixture.task_id, "channel_id": "openai_codex", "fallback_authorized": False},
            )
    finally:
        fixture.close()


def test_secret_like_metadata_is_rejected_by_the_real_control_plane(tmp_path) -> None:
    fixture = ControlPlaneFixture(tmp_path)
    try:
        body = provider_observation_payload(_observation())
        body["metadata"] = {"api_token": "not-a-secret"}
        with pytest.raises(ControlPlaneRemoteError, match="INVALID_REQUEST"):
            ProviderObservationClient(fixture.socket_path)._transport._request(
                "RecordProviderObservation",
                None,
                CORRELATION_ID,
                _observer_capability(fixture),
                body,
                idempotency_key="provider-secret-rejected",
            )
    finally:
        fixture.close()


def test_provider_observation_client_fails_closed_when_the_uds_is_unavailable(tmp_path) -> None:
    with pytest.raises(ControlPlaneUnavailableError):
        ProviderObservationClient(tmp_path / "missing.sock").record_provider_observation(
            _observation(),
            CORRELATION_ID,
            {},
            idempotency_key="provider-unavailable",
        )
