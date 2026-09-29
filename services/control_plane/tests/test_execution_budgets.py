import pytest

import app.service as service_module
from app.auth import HermeticCapabilityIssuer, authorize
from app.errors import ControlPlaneError
from app.service import ControlPlaneService
from helpers import CORR, CORR2, HERMES, MANAGER, OBSERVER, task_body

REVIEWER = {"role": "REVIEWER", "identity_id": "reviewer"}
OBSERVED_AT = "2026-09-29T00:00:00.000Z"
RESET_AT = "2026-09-30T00:00:00.000Z"


def _service_task(tmp_path):
    service = ControlPlaneService(tmp_path / "db.sqlite")
    return service, service.create_task(HERMES, "create", CORR, task_body())["task_id"]


def _observe(service, channel_id, state, key="provider", *, reset_at=None, metadata=None):
    return service.record_provider_observation(
        OBSERVER, key, CORR, channel_id, state, OBSERVED_AT, reset_at, "hermetic-test", metadata or {}
    )


def _consume_model_calls(service, task_id, count, prefix="call"):
    for index in range(count):
        assert service.admit_model_call(HERMES, f"{prefix}-{index}", CORR, task_id, "COORDINATOR")["decision"] == "ADMIT"


def test_task_creation_atomically_initializes_default_execution_budget(tmp_path):
    service, task_id = _service_task(tmp_path)

    assert service.get_execution_budget(task_id) == {
        "task_id": task_id,
        "schema_version": "1.0.0",
        "policy_version": "1.0.0",
        "model_calls_limit": 40,
        "model_calls_used": 0,
        "max_live_delegations": 1,
        "live_delegations": 0,
        "reviewer_calls_reserved": 0,
        "reviewer_calls_used": 0,
        "provider_retry_limit": 2,
        "provider_retries_used": 0,
        "context_soft_limit_tokens": 80000,
        "context_hard_limit_tokens": 120000,
        "budget_state": "OPEN",
        "revision": 0,
    }
    service.close()


def test_model_call_debits_once_and_identical_idempotency_replay_does_not_double_debit(tmp_path):
    service, task_id = _service_task(tmp_path)
    first = service.admit_model_call(HERMES, "admit", CORR, task_id, "COORDINATOR")

    assert first == service.admit_model_call(HERMES, "admit", CORR, task_id, "COORDINATOR")
    assert first["decision"] == "ADMIT"
    assert service.get_execution_budget(task_id)["model_calls_used"] == 1
    with pytest.raises(ControlPlaneError, match="IDEMPOTENCY_CONFLICT"):
        service.admit_model_call(HERMES, "admit", CORR, task_id, "IMPLEMENTATION_WORKER")
    service.close()


def test_global_model_limit_blocks_without_extra_debit_and_records_hard_limit(tmp_path):
    service, task_id = _service_task(tmp_path)
    _consume_model_calls(service, task_id, 40)
    assert service.get_execution_budget(task_id)["budget_state"] == "HARD_LIMIT_REACHED"

    blocked = service.admit_model_call(HERMES, "over-limit", CORR, task_id, "COORDINATOR")
    budget = service.get_execution_budget(task_id)
    assert blocked["decision"] == "BLOCK_BUDGET"
    assert budget["model_calls_used"] == 40
    assert budget["budget_state"] == "HARD_LIMIT_REACHED"
    assert service.con.execute("SELECT count(*) FROM audit_events WHERE event_type='BUDGET_HARD_LIMIT_REACHED'").fetchone()[0] == 1
    service.close()


def test_context_thresholds_are_durable_and_do_not_debit_at_hard_limit(tmp_path):
    service, task_id = _service_task(tmp_path)
    soft = service.admit_model_call(HERMES, "soft", CORR, task_id, "COORDINATOR", observed_context_tokens=80000)
    hard = service.admit_model_call(HERMES, "hard", CORR2, task_id, "COORDINATOR", observed_context_tokens=120000)

    assert soft["decision"] == "ADMIT" and soft["checkpoint_required"] is True
    assert hard["decision"] == "STOP_AND_CHECKPOINT" and hard["checkpoint_required"] is True
    assert service.get_execution_budget(task_id)["model_calls_used"] == 1
    event_types = {row[0] for row in service.con.execute("SELECT event_type FROM audit_events")}
    assert {"BUDGET_SOFT_LIMIT_REACHED", "CHECKPOINT_REQUIRED"} <= event_types
    service.close()


def test_only_one_live_delegation_is_admitted_and_release_never_underflows(tmp_path):
    service, task_id = _service_task(tmp_path)
    assert service.reserve_delegation(HERMES, "delegate-1", CORR, task_id)["decision"] == "ADMIT"
    with pytest.raises(ControlPlaneError, match="RESOURCE_LIMIT_REACHED"):
        service.reserve_delegation(HERMES, "delegate-2", CORR, task_id)
    assert service.release_delegation(HERMES, "release-1", CORR, task_id)["released"] is True
    assert service.release_delegation(HERMES, "release-2", CORR, task_id)["released"] is False
    assert service.get_execution_budget(task_id)["live_delegations"] == 0
    service.close()


def test_reviewer_requires_reservation_and_debits_global_and_reviewer_counters(tmp_path):
    service, task_id = _service_task(tmp_path)
    assert service.admit_model_call(REVIEWER, "review-none", CORR, task_id, "REVIEWER")["decision"] == "BLOCK_BUDGET"
    assert service.reserve_review_budget(HERMES, "reserve-review", CORR, task_id, 2)["decision"] == "ADMIT"

    admitted = service.admit_model_call(REVIEWER, "review-one", CORR, task_id, "REVIEWER")
    budget = service.get_execution_budget(task_id)
    assert admitted["decision"] == "ADMIT"
    assert (budget["model_calls_used"], budget["reviewer_calls_reserved"], budget["reviewer_calls_used"]) == (1, 2, 1)
    service.close()


def test_review_reservation_cannot_exceed_remaining_global_budget(tmp_path):
    service, task_id = _service_task(tmp_path)
    _consume_model_calls(service, task_id, 35)

    result = service.reserve_review_budget(HERMES, "reserve-too-many", CORR, task_id, 8)
    assert result["decision"] == "BLOCK_BUDGET"
    assert service.get_execution_budget(task_id)["reviewer_calls_reserved"] == 0
    service.close()


def test_provider_auth_and_quota_preflight_do_not_consume_transient_retry_budget(tmp_path):
    service, task_id = _service_task(tmp_path)
    _observe(service, "codex_cli", "AUTH_EXPIRED", "auth")
    auth = service.evaluate_provider_preflight(task_id, "codex_cli", False)
    _observe(service, "codex_cli", "QUOTA_EXHAUSTED", "quota", reset_at=RESET_AT)
    quota = service.evaluate_provider_preflight(task_id, "codex_cli", False)

    assert auth["decision"] == "BLOCK_PROVIDER_AUTH"
    assert quota == {"decision": "PAUSE_PROVIDER_QUOTA", "channel_id": "codex_cli", "provider_state": "QUOTA_EXHAUSTED", "reset_at": RESET_AT, "fallback_authorized": False}
    assert service.get_execution_budget(task_id)["provider_retries_used"] == 0
    service.close()


def test_transient_failure_allows_exactly_two_retry_reservations(tmp_path):
    service, task_id = _service_task(tmp_path)
    _observe(service, "codex_cli", "TRANSIENT_FAILURE")

    assert service.reserve_transient_retry(MANAGER, "retry-1", CORR, task_id, "codex_cli")["decision"] == "ADMIT"
    assert service.reserve_transient_retry(MANAGER, "retry-2", CORR2, task_id, "codex_cli")["decision"] == "ADMIT"
    assert service.reserve_transient_retry(MANAGER, "retry-3", "corr_018f3d4a-7b8c-7c9d-8e1f-0123456789ad", task_id, "codex_cli")["decision"] == "BLOCK_BUDGET"
    assert service.get_execution_budget(task_id)["provider_retries_used"] == 2
    service.close()


def test_provider_channels_are_independent_unknown_fails_closed_and_fallback_is_only_evidence(tmp_path):
    service, task_id = _service_task(tmp_path)
    _observe(service, "codex_cli", "AUTH_EXPIRED", "auth")
    _observe(service, "openai_codex", "AVAILABLE", "available")

    assert service.evaluate_provider_preflight(task_id, "codex_cli", False)["decision"] == "BLOCK_PROVIDER_AUTH"
    assert service.evaluate_provider_preflight(task_id, "openai_codex", False)["decision"] == "ADMIT"
    unknown = service.evaluate_provider_preflight(task_id, "not-observed", True)
    assert unknown["decision"] == "BLOCK_PROVIDER_UNKNOWN"
    assert unknown["fallback_authorized"] is True
    assert service.con.execute("SELECT count(*) FROM provider_channel_states").fetchone()[0] == 2
    service.close()


def test_provider_metadata_is_secret_free_and_audit_failure_rolls_back_budget_debit(tmp_path, monkeypatch):
    service, task_id = _service_task(tmp_path)
    with pytest.raises(ControlPlaneError, match="INVALID_REQUEST"):
        _observe(service, "codex_cli", "AVAILABLE", "secret", metadata={"api_token": "nope"})

    def broken(*args, **kwargs):
        raise RuntimeError("injected")

    monkeypatch.setattr(service_module, "append_event", broken)
    with pytest.raises(ControlPlaneError, match="AUDIT_WRITE_FAILED"):
        service.admit_model_call(HERMES, "audit-failure", CORR, task_id, "COORDINATOR")
    assert service.get_execution_budget(task_id)["model_calls_used"] == 0
    service.close()


def test_protocol_authorization_exposes_only_conservative_tc5_roles():
    issuer = HermeticCapabilityIssuer()
    task_id = "task_018f3d4a-7b8c-7c9d-8e1f-0123456789ab"
    coordinator_capability = issuer.issue("budget-read", "HERMES_COORDINATOR", "hermes", ["GetExecutionBudget"], "2099-01-01T00:00:00.000Z", task_id=task_id)
    authorize(HERMES, coordinator_capability, "GetExecutionBudget", task_id, issuer=issuer)
    worker = {"role": "WORKER", "identity_id": "worker"}
    worker_capability = issuer.issue("worker-budget", "WORKER", "worker", ["GetExecutionBudget"], "2099-01-01T00:00:00.000Z", task_id=task_id, resource_id="rsrc_018f3d4a-7b8c-7c9d-8e1f-0123456789ab")
    with pytest.raises(ControlPlaneError, match="UNAUTHORIZED"):
        authorize(worker, worker_capability, "GetExecutionBudget", task_id, issuer=issuer)
