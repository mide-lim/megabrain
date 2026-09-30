from __future__ import annotations

import json
from pathlib import Path

from app.coordinator_service import CoordinatorWorkItem
from app.production_capabilities import IdleWorkSource, ProductionCapabilityProvider


class OneWork:
    def __init__(self, item): self.item = item
    def next_work(self): item, self.item = self.item, None; return item


class ExchangeTransport:
    def __init__(self): self.calls = []
    def exchange_coordinator_bootstrap(self, *, bootstrap_id, bootstrap_secret, task_id, channel_id, correlation_id):
        self.calls.append((bootstrap_id, bootstrap_secret, task_id, channel_id, correlation_id))
        return {"coordinator_capability": {"capability_id": "coordinator", "capability_proof": "proof"}, "observer_capability": {"capability_id": "observer", "capability_proof": "proof"}}


def _item() -> CoordinatorWorkItem:
    return CoordinatorWorkItem(task_id="task_a", correlation_id="corr_a", channel_id="openai_codex", task_packet="packet", observed_context_tokens=0, max_iterations=1, timeout_seconds=1, usage_file_path="usage.json", recommended_api_call_budget=None, coordinator_capability={}, observer_capability={})


def test_production_capability_provider_exchanges_fake_systemd_credential_and_replaces_work_capabilities(tmp_path: Path):
    credentials = tmp_path / "credentials"; credentials.mkdir(mode=0o700)
    secret = "fake-bootstrap-secret-" + "x" * 64
    (credentials / "control-plane-coordinator-bootstrap").write_text(json.dumps({"version": 1, "bootstrap_id": "coordinator-v1", "secret": secret}), encoding="utf-8")
    transport = ExchangeTransport()
    bound = ProductionCapabilityProvider(transport, credential_directory=credentials).bind(OneWork(_item()))

    result = bound.next_work()

    assert result is not None
    assert result.coordinator_capability_payload()["capability_id"] == "coordinator"
    assert result.observer_capability_payload()["capability_id"] == "observer"
    assert transport.calls == [("coordinator-v1", secret, "task_a", "openai_codex", "corr_a")]
    assert secret not in repr(bound)
    assert IdleWorkSource().next_work() is None
