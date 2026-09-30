from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.control_plane_client import ControlPlaneClient
from app.provider_classifier import ProviderState
from app.provider_control_plane import ProviderObservationClient, provider_observation_payload
from app.provider_observer import HermesUsageProbe, ProviderObserver
from control_plane_fixture import CORRELATION_ID, ControlPlaneFixture


FAKE_HERMES_USAGE = """#!/usr/bin/env python3
import json
import os
import sys
import time

mode = os.environ['FAKE_USAGE_MODE']
if sys.argv[1:] != ['usage', '--provider', 'openai-codex', '--json']:
    sys.exit(91)
if mode == 'exit_one':
    sys.exit(1)
if mode == 'timeout':
    time.sleep(60)
window = {'label': '5h', 'used_percent': 100 if mode == 'quota' else 20, 'resets_at': '2026-09-30T18:00:00+00:00', 'detail': 'Account limit'}
document = {
    'provider': 'openai-codex',
    'source': 'codex account usage',
    'title': 'Account limits',
    'plan': 'Pro',
    'fetched_at': '2026-09-30T12:00:00+00:00',
    'windows': [window],
    'details': [],
    'unavailable_reason': None,
}
sys.stdout.write(json.dumps(document))
"""


def _observer(tmp_path: Path, mode: str) -> ProviderObserver:
    tmp_path.mkdir(mode=0o700, parents=True, exist_ok=True)
    executable = tmp_path / f"fake-hermes-{mode}"
    executable.write_text(FAKE_HERMES_USAGE, encoding="utf-8")
    executable.chmod(0o700)
    return ProviderObserver(
        probe=HermesUsageProbe(
            hermes_executable=str(executable),
            timeout_seconds=0.1,
            environment={"FAKE_USAGE_MODE": mode},
            termination_grace_seconds=0.1,
        ),
        clock=lambda: datetime(2026, 9, 30, 12, 1, tzinfo=timezone.utc),
    )


def _observer_capability(fixture: ControlPlaneFixture) -> dict:
    return fixture.issuer.issue(
        "observer-record",
        "OBSERVABILITY_ADAPTER",
        "observer",
        ["RecordProviderObservation"],
        "2099-01-01T00:00:00.000Z",
    )


def _observe_record_preflight(fixture: ControlPlaneFixture, tmp_path: Path, mode: str, key: str):
    observation = _observer(tmp_path, mode).observe("openai_codex")
    recorded = ProviderObservationClient(fixture.socket_path).record_provider_observation(
        observation,
        CORRELATION_ID,
        _observer_capability(fixture),
        idempotency_key=key,
    )
    preflight = ControlPlaneClient(fixture.socket_path).evaluate_provider_preflight(
        fixture.task_id,
        CORRELATION_ID,
        "openai_codex",
        fixture.capability(["EvaluateProviderPreflight"]),
    )
    return observation, recorded, preflight


def test_fake_usage_available_then_quota_then_fresh_available_replaces_control_plane_state(tmp_path) -> None:
    fixture = ControlPlaneFixture(tmp_path)
    try:
        available, first, available_preflight = _observe_record_preflight(fixture, tmp_path / "available", "available", "observe-available")
        quota, exhausted, quota_preflight = _observe_record_preflight(fixture, tmp_path / "quota", "quota", "observe-quota")
        restored, final, restored_preflight = _observe_record_preflight(fixture, tmp_path / "restored", "available", "observe-restored")

        assert available.state is ProviderState.AVAILABLE
        assert first["state"] == "AVAILABLE"
        assert available_preflight["decision"] == "ADMIT"
        assert quota.state is ProviderState.QUOTA_EXHAUSTED
        assert exhausted["state"] == "QUOTA_EXHAUSTED"
        assert exhausted["reset_at"] == "2026-09-30T18:00:00.000Z"
        assert quota_preflight == {
            "decision": "PAUSE_PROVIDER_QUOTA",
            "channel_id": "openai_codex",
            "provider_state": "QUOTA_EXHAUSTED",
            "reset_at": "2026-09-30T18:00:00.000Z",
            "fallback_authorized": False,
        }
        assert restored.state is ProviderState.AVAILABLE
        assert final["state"] == "AVAILABLE"
        assert final["revision"] == exhausted["revision"] + 1
        assert restored_preflight["decision"] == "ADMIT"
    finally:
        fixture.close()


def test_fake_usage_ambiguous_and_timeout_evidence_block_preflight_without_retry_reservation(tmp_path) -> None:
    fixture = ControlPlaneFixture(tmp_path)
    try:
        unknown, unknown_recorded, unknown_preflight = _observe_record_preflight(fixture, tmp_path / "unknown", "exit_one", "observe-unknown")
        transient, transient_recorded, transient_preflight = _observe_record_preflight(fixture, tmp_path / "transient", "timeout", "observe-transient")

        assert unknown.state is ProviderState.UNKNOWN
        assert unknown_recorded["state"] == "UNKNOWN"
        assert provider_observation_payload(unknown)["source"] == "hermes_usage_probe"
        assert unknown_preflight["decision"] == "BLOCK_PROVIDER_UNKNOWN"
        assert transient.state is ProviderState.TRANSIENT_FAILURE
        assert transient_recorded["state"] == "TRANSIENT_FAILURE"
        assert provider_observation_payload(transient)["source"] == "hermes_usage_probe"
        assert transient_preflight["decision"] == "BLOCK_PROVIDER_UNKNOWN"
    finally:
        fixture.close()
