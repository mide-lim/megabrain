"""AP0 v1 transactional control-plane service; no runtime resource creation."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .adapters.reconciliation import ExpectedResource, ObservedResource, reconcile
from .errors import ControlPlaneError, fail
from .ids import generate_id, validate_id
from .models import canonical_json, require_semver, utc_now, validate_timestamp
from .policy import DEFAULTS, allowed_transition, preview_allowed, resource_limit
from .schema import validate_secret_free
from .storage import repositories
from .storage.event_chain import append_event
from .storage.idempotency import begin, finalize, fingerprint
from .storage.migrations import admission_ready, apply_migrations
from .storage.sqlite import connect, immediate
from .worker_identity import (
    launch_nonce_matches,
    matches_launch_expectation,
    validate_launch_expectation,
    validate_launch_nonce,
    validate_observed_process_identity,
)

_RECORD_VERSION = "1.0.0"
_MUTATIONS = {
    "CreateTask", "TransitionTask", "PauseTask", "ResumeTask", "CreateCheckpoint",
    "AllocateResource", "BindResourceIdentity", "MarkResourceTerminal", "RecordHeartbeat",
    "CreateGate", "ResolveGate", "ConsumeGate", "AppendEvent", "ReconcileObservation",
    "AdmitModelCall", "ReserveDelegation", "ReleaseDelegation", "ReserveReviewBudget",
    "RecordProviderObservation", "ReserveTransientRetry",
}
_ALLOWED_APPEND_EVENTS = {
    "VALIDATION_RECORDED", "REVIEW_EVIDENCE", "OBSERVATION_RECORDED",
    "PROVIDER_QUOTA_OBSERVED", "OWNERSHIP_UNKNOWN_DISCOVERED",
}
_BUDGET_FIELDS = {
    "WORKER": "workers", "PROCESS": "processes", "PREVIEW": "previews", "WORKTREE": "worktrees",
    "TEMP_DIR": "temporary_bytes", "ARTIFACT": "artifact_bytes",
}


def _json(value):
    return json.loads(value) if isinstance(value, str) else value


def _identity(value: object) -> dict:
    if not isinstance(value, dict) or not isinstance(value.get("identity_id") or value.get("id"), str):
        raise fail("INVALID_REQUEST", "typed identity required")
    return value


def _expected_revision(value: object) -> int:
    if not isinstance(value, int) or value < 0:
        raise fail("INVALID_REQUEST", "expected revision required")
    return value


def _same(left: object, right: object) -> bool:
    return canonical_json(left) == canonical_json(right)


class ControlPlaneService:
    def __init__(self, path, *, worker_identity_verifier=None):
        self.path = Path(path)
        self.con = connect(self.path)
        self.worker_identity_verifier = worker_identity_verifier
        apply_migrations(self.con)

    def close(self):
        self.con.close()

    def _ready(self):
        if not admission_ready(self.con):
            raise fail("REGISTRY_UNAVAILABLE", "admission is closed", True)

    def _mutation(self, caller, key, operation, body, expected_revision, capability_id, callback, *, require_ready=True):
        if operation not in _MUTATIONS:
            raise fail("INVALID_REQUEST", "unsupported mutation")
        if require_ready:
            self._ready()
        if not isinstance(key, str) or not key or len(key) > 256:
            raise fail("INVALID_REQUEST", "idempotency key required")
        caller = _identity(caller)
        digest = fingerprint("1.0", operation, caller.get("identity_id", caller.get("id")), capability_id, expected_revision, body)
        try:
            with immediate(self.con):
                prior, replayed = begin(self.con, caller.get("identity_id", caller.get("id")), key, operation, digest)
                if replayed:
                    return prior
                result, reference = callback()
                finalize(self.con, caller.get("identity_id", caller.get("id")), key, result, reference)
                return result
        except ControlPlaneError:
            raise
        except sqlite3.Error as exc:
            raise fail("AUDIT_WRITE_FAILED", "durable mutation failed") from exc

    def _task_row(self, task_id):
        if not validate_id(task_id, "task"):
            raise fail("INVALID_REQUEST", "invalid task identifier")
        row = repositories.get_task(self.con, task_id)
        if not row:
            raise fail("TASK_NOT_FOUND")
        require_semver(row["schema_version"])
        return row

    def _resource_row(self, resource_id):
        if not validate_id(resource_id, "rsrc"):
            raise fail("INVALID_REQUEST", "invalid resource identifier")
        row = repositories.get_resource(self.con, resource_id)
        if not row:
            raise fail("RESOURCE_NOT_FOUND")
        require_semver(row["schema_version"])
        return row

    def _budget_row(self, task_id):
        self._task_row(task_id)
        row = self.con.execute("SELECT * FROM task_execution_budgets WHERE task_id=?", (task_id,)).fetchone()
        if not row:
            raise fail("REGISTRY_UNAVAILABLE", "task execution budget projection unavailable")
        require_semver(row["schema_version"])
        return row

    def _provider_row(self, channel_id):
        if not isinstance(channel_id, str) or not channel_id or len(channel_id) > 128:
            raise fail("INVALID_REQUEST", "bounded provider channel identifier required")
        row = self.con.execute("SELECT * FROM provider_channel_states WHERE channel_id=?", (channel_id,)).fetchone()
        if row:
            require_semver(row["schema_version"])
        return row

    def _event(self, *args, **kwargs):
        try:
            return append_event(self.con, *args, **kwargs)
        except ControlPlaneError:
            raise
        except Exception as exc:
            raise fail("AUDIT_WRITE_FAILED", "audit append failed") from exc

    def _task_public(self, row):
        return {
            "task_id": row["task_id"], "schema_version": row["schema_version"], "created_at": row["created_at"],
            "created_by": _json(row["created_by"]), "requested_by": _json(row["requested_by"]),
            "state": row["state"], "risk_class": row["risk_class"], "task_contract_ref": row["task_contract_ref"],
            "allowed_operations": _json(row["allowed_operations"]), "resource_budget": _json(row["resource_budget"]),
            "prerequisite_status": _json(row["prerequisite_status"]), "pause_reason": _json(row["pause_reason"]) if row["pause_reason"] else None,
            "terminal_result": _json(row["terminal_result"]) if row["terminal_result"] else None,
            "current_checkpoint_id": row["current_checkpoint_id"], "revision": row["revision"],
        }

    def _resource_public(self, row):
        return {
            "resource_id": row["resource_id"], "task_id": row["task_id"], "schema_version": row["schema_version"],
            "resource_type": row["resource_type"], "created_at": row["created_at"], "state": row["state"],
            "requested_operation": _json(row["requested_operation"]), "budget_reservation": _json(row["budget_reservation"]),
            "expected_identity": _json(row["expected_identity"]), "bound_identity": _json(row["bound_identity"]) if row["bound_identity"] else None,
            "heartbeat_required": bool(row["heartbeat_required"]), "last_heartbeat": row["last_heartbeat"], "ttl_seconds": row["ttl_seconds"],
            "metadata": _json(row["metadata"]), "terminal_reason": _json(row["terminal_reason"]) if row["terminal_reason"] and row["terminal_reason"].startswith("{") else row["terminal_reason"],
            "revision": row["revision"],
        }

    def _budget_public(self, row):
        return {key: row[key] for key in ("task_id", "schema_version", "policy_version", "model_calls_limit", "model_calls_used", "max_live_delegations", "live_delegations", "reviewer_calls_reserved", "reviewer_calls_used", "provider_retry_limit", "provider_retries_used", "context_soft_limit_tokens", "context_hard_limit_tokens", "budget_state", "revision")}

    def get_task(self, task_id):
        return self._task_public(self._task_row(task_id))

    def get_execution_budget(self, task_id):
        return self._budget_public(self._budget_row(task_id))

    def _assert_executable_task(self, task):
        if task["state"] == "TERMINAL":
            raise fail("TASK_TERMINAL")

    def _admission_result(self, decision, budget, checkpoint_required=False, **evidence):
        return {"decision": decision, "model_calls_used": budget["model_calls_used"], "model_calls_remaining": budget["model_calls_limit"] - budget["model_calls_used"], "checkpoint_required": checkpoint_required, **evidence}

    def admit_model_call(self, caller, key, correlation_id, task_id, execution_role, execution_scope=None, observed_context_tokens=None, capability_id="test"):
        body = {"task_id": task_id, "execution_role": execution_role, "execution_scope": execution_scope, "observed_context_tokens": observed_context_tokens}
        def admit():
            task = self._task_row(task_id); self._assert_executable_task(task); budget = self._budget_row(task_id)
            allowed_roles = {"HERMES_COORDINATOR": {"COORDINATOR"}, "WORKER_MANAGER": {"IMPLEMENTATION_WORKER", "CONTINUATION_WORKER"}, "REVIEWER": {"REVIEWER"}}
            if execution_role not in {"COORDINATOR", "IMPLEMENTATION_WORKER", "CONTINUATION_WORKER", "REVIEWER"}:
                raise fail("INVALID_REQUEST", "unsupported execution role")
            if execution_role not in allowed_roles.get(caller.get("role"), set()):
                raise fail("UNAUTHORIZED", "caller cannot admit this execution role")
            if execution_scope is not None: validate_secret_free(execution_scope)
            if observed_context_tokens is not None and (not isinstance(observed_context_tokens, int) or observed_context_tokens < 0):
                raise fail("INVALID_REQUEST", "nonnegative observed context tokens required")
            if budget["model_calls_used"] >= budget["model_calls_limit"]:
                if budget["budget_state"] != "HARD_LIMIT_REACHED":
                    self._event("BUDGET_HARD_LIMIT_REACHED", caller, correlation_id, {"task_id": task_id, "policy_version": budget["policy_version"]}, task_id)
                    self.con.execute("UPDATE task_execution_budgets SET budget_state='HARD_LIMIT_REACHED',revision=revision+1,updated_at=? WHERE task_id=?", (utc_now(), task_id))
                    budget = self._budget_row(task_id)
                return self._admission_result("BLOCK_BUDGET", budget), task_id
            if execution_role == "REVIEWER" and budget["reviewer_calls_used"] >= budget["reviewer_calls_reserved"]:
                return self._admission_result("BLOCK_BUDGET", budget), task_id
            if observed_context_tokens is not None and observed_context_tokens >= budget["context_hard_limit_tokens"]:
                self._event("CHECKPOINT_REQUIRED", caller, correlation_id, {"task_id": task_id, "observed_context_tokens": observed_context_tokens, "threshold": budget["context_hard_limit_tokens"]}, task_id)
                return self._admission_result("STOP_AND_CHECKPOINT", budget, True), task_id
            soft = observed_context_tokens is not None and observed_context_tokens >= budget["context_soft_limit_tokens"]
            self.con.execute("UPDATE task_execution_budgets SET model_calls_used=model_calls_used+1,reviewer_calls_used=reviewer_calls_used+?,revision=revision+1,updated_at=? WHERE task_id=?", (int(execution_role == "REVIEWER"), utc_now(), task_id))
            payload = {"task_id": task_id, "execution_role": execution_role, "execution_scope": execution_scope, "policy_version": budget["policy_version"]}
            self._event("BUDGET_ADMITTED", caller, correlation_id, payload, task_id)
            if budget["model_calls_used"] + 1 >= budget["model_calls_limit"]:
                self._event("BUDGET_HARD_LIMIT_REACHED", caller, correlation_id, {"task_id": task_id, "policy_version": budget["policy_version"]}, task_id)
                self.con.execute("UPDATE task_execution_budgets SET budget_state='HARD_LIMIT_REACHED',revision=revision+1,updated_at=? WHERE task_id=?", (utc_now(), task_id))
            if execution_role == "CONTINUATION_WORKER": self._event("CONTINUATION_ADMITTED", caller, correlation_id, payload, task_id)
            if soft:
                evidence = {"task_id": task_id, "observed_context_tokens": observed_context_tokens, "threshold": budget["context_soft_limit_tokens"]}
                self._event("BUDGET_SOFT_LIMIT_REACHED", caller, correlation_id, evidence, task_id)
                self._event("CHECKPOINT_REQUIRED", caller, correlation_id, evidence, task_id)
            return self._admission_result("ADMIT", self._budget_row(task_id), soft), task_id
        return self._mutation(caller, key, "AdmitModelCall", body, None, capability_id, admit)

    def reserve_delegation(self, caller, key, correlation_id, task_id, capability_id="test"):
        def reserve():
            task = self._task_row(task_id); self._assert_executable_task(task); budget = self._budget_row(task_id)
            if budget["live_delegations"] >= budget["max_live_delegations"]: raise fail("RESOURCE_LIMIT_REACHED", "live delegation limit reached")
            self.con.execute("UPDATE task_execution_budgets SET live_delegations=live_delegations+1,revision=revision+1,updated_at=? WHERE task_id=?", (utc_now(), task_id))
            self._event("DELEGATION_RESERVED", caller, correlation_id, {"task_id": task_id, "policy_version": budget["policy_version"]}, task_id)
            return {"decision": "ADMIT", "live_delegations": budget["live_delegations"] + 1, "max_live_delegations": budget["max_live_delegations"]}, task_id
        return self._mutation(caller, key, "ReserveDelegation", {"task_id": task_id}, None, capability_id, reserve)

    def release_delegation(self, caller, key, correlation_id, task_id, capability_id="test"):
        def release():
            budget = self._budget_row(task_id)
            if budget["live_delegations"] == 0: return {"released": False, "live_delegations": 0, "max_live_delegations": budget["max_live_delegations"]}, task_id
            self.con.execute("UPDATE task_execution_budgets SET live_delegations=live_delegations-1,revision=revision+1,updated_at=? WHERE task_id=?", (utc_now(), task_id))
            self._event("DELEGATION_RELEASED", caller, correlation_id, {"task_id": task_id, "policy_version": budget["policy_version"]}, task_id)
            return {"released": True, "live_delegations": budget["live_delegations"] - 1, "max_live_delegations": budget["max_live_delegations"]}, task_id
        return self._mutation(caller, key, "ReleaseDelegation", {"task_id": task_id}, None, capability_id, release)

    def reserve_review_budget(self, caller, key, correlation_id, task_id, requested_calls, capability_id="test"):
        def reserve():
            task = self._task_row(task_id); self._assert_executable_task(task); budget = self._budget_row(task_id)
            if not isinstance(requested_calls, int) or requested_calls <= 0 or requested_calls > DEFAULTS["reviewer_calls_limit"]: raise fail("INVALID_REQUEST", "review request must be between one and reviewer limit")
            remaining = budget["model_calls_limit"] - budget["model_calls_used"] - budget["reviewer_calls_reserved"]
            if requested_calls > remaining or budget["reviewer_calls_reserved"] + requested_calls > DEFAULTS["reviewer_calls_limit"]:
                return {"decision": "BLOCK_BUDGET", "reviewer_calls_reserved": budget["reviewer_calls_reserved"], "model_calls_remaining": budget["model_calls_limit"] - budget["model_calls_used"]}, task_id
            self.con.execute("UPDATE task_execution_budgets SET reviewer_calls_reserved=reviewer_calls_reserved+?,revision=revision+1,updated_at=? WHERE task_id=?", (requested_calls, utc_now(), task_id))
            self._event("REVIEW_BUDGET_RESERVED", caller, correlation_id, {"task_id": task_id, "requested_calls": requested_calls, "policy_version": budget["policy_version"]}, task_id)
            return {"decision": "ADMIT", "reviewer_calls_reserved": budget["reviewer_calls_reserved"] + requested_calls, "model_calls_remaining": budget["model_calls_limit"] - budget["model_calls_used"]}, task_id
        return self._mutation(caller, key, "ReserveReviewBudget", {"task_id": task_id, "requested_calls": requested_calls}, None, capability_id, reserve)

    def record_provider_observation(self, caller, key, correlation_id, channel_id, state, observed_at, reset_at, source, metadata, capability_id="test"):
        body = {"channel_id": channel_id, "state": state, "observed_at": observed_at, "reset_at": reset_at, "source": source, "metadata": metadata}
        def record():
            if state not in {"AVAILABLE", "AUTH_EXPIRED", "QUOTA_EXHAUSTED", "TRANSIENT_FAILURE", "UNKNOWN"}: raise fail("INVALID_REQUEST", "unsupported provider state")
            if not isinstance(source, str) or not source or len(source) > 128 or not isinstance(metadata, dict): raise fail("INVALID_REQUEST", "bounded provider observation required")
            try:
                validate_timestamp(observed_at)
                if reset_at is not None: validate_timestamp(reset_at)
                validate_secret_free(metadata)
            except ValueError as exc:
                raise fail("INVALID_REQUEST", "provider observation must be timestamped and secret-free") from exc
            prior = self._provider_row(channel_id); now = utc_now()
            if prior:
                self.con.execute("UPDATE provider_channel_states SET state=?,observed_at=?,reset_at=?,source=?,metadata=?,revision=revision+1,updated_at=? WHERE channel_id=?", (state, observed_at, reset_at, source, canonical_json(metadata), now, channel_id))
            else:
                self.con.execute("INSERT INTO provider_channel_states VALUES(?,?,?,?,?,?,?,?,?)", (channel_id, _RECORD_VERSION, state, observed_at, reset_at, source, canonical_json(metadata), 0, now))
            event_type = {"AVAILABLE": "PROVIDER_AVAILABLE", "AUTH_EXPIRED": "PROVIDER_AUTH_BLOCKED", "QUOTA_EXHAUSTED": "PROVIDER_QUOTA_EXHAUSTED", "TRANSIENT_FAILURE": "PROVIDER_TRANSIENT_FAILURE", "UNKNOWN": "PROVIDER_TRANSIENT_FAILURE"}[state]
            self._event(event_type, caller, correlation_id, {"channel_id": channel_id, "state": state, "observed_at": observed_at, "reset_at": reset_at, "source": source}, None)
            row = self._provider_row(channel_id)
            return {"channel_id": channel_id, "state": row["state"], "observed_at": row["observed_at"], "reset_at": row["reset_at"], "revision": row["revision"]}, channel_id
        return self._mutation(caller, key, "RecordProviderObservation", body, None, capability_id, record)

    def evaluate_provider_preflight(self, task_id, channel_id, fallback_authorized):
        budget = self._budget_row(task_id)
        if not isinstance(fallback_authorized, bool): raise fail("INVALID_REQUEST", "explicit fallback authorization flag required")
        if budget["budget_state"] == "HARD_LIMIT_REACHED" or budget["model_calls_used"] >= budget["model_calls_limit"]:
            return {"decision": "BLOCK_BUDGET", "channel_id": channel_id, "fallback_authorized": fallback_authorized}
        provider = self._provider_row(channel_id); state = provider["state"] if provider else "UNKNOWN"
        decision = {"AVAILABLE": "ADMIT", "AUTH_EXPIRED": "BLOCK_PROVIDER_AUTH", "QUOTA_EXHAUSTED": "PAUSE_PROVIDER_QUOTA", "TRANSIENT_FAILURE": "BLOCK_PROVIDER_UNKNOWN", "UNKNOWN": "BLOCK_PROVIDER_UNKNOWN"}[state]
        return {"decision": decision, "channel_id": channel_id, "provider_state": state, "reset_at": provider["reset_at"] if provider else None, "fallback_authorized": fallback_authorized}

    def reserve_transient_retry(self, caller, key, correlation_id, task_id, channel_id, capability_id="test"):
        def reserve():
            task = self._task_row(task_id); self._assert_executable_task(task); budget = self._budget_row(task_id); provider = self._provider_row(channel_id)
            if not provider or provider["state"] != "TRANSIENT_FAILURE": return {"decision": "BLOCK_PROVIDER_UNKNOWN", "provider_retries_used": budget["provider_retries_used"], "provider_retry_limit": budget["provider_retry_limit"]}, task_id
            if budget["provider_retries_used"] >= budget["provider_retry_limit"]: return {"decision": "BLOCK_BUDGET", "provider_retries_used": budget["provider_retries_used"], "provider_retry_limit": budget["provider_retry_limit"]}, task_id
            self.con.execute("UPDATE task_execution_budgets SET provider_retries_used=provider_retries_used+1,revision=revision+1,updated_at=? WHERE task_id=?", (utc_now(), task_id))
            self._event("TRANSIENT_RETRY_RESERVED", caller, correlation_id, {"task_id": task_id, "channel_id": channel_id, "policy_version": budget["policy_version"]}, task_id)
            return {"decision": "ADMIT", "provider_retries_used": budget["provider_retries_used"] + 1, "provider_retry_limit": budget["provider_retry_limit"]}, task_id
        return self._mutation(caller, key, "ReserveTransientRetry", {"task_id": task_id, "channel_id": channel_id}, None, capability_id, reserve)

    def get_task_resources(self, task_id):
        self._task_row(task_id)
        return [self._resource_public(row) for row in repositories.task_resources(self.con, task_id)]

    def get_pending_gates(self, task_id, resource_id=None):
        self._task_row(task_id)
        rows = repositories.pending_gates(self.con, task_id)
        now = utc_now()
        result = []
        for row in rows:
            if resource_id and row["resource_id"] != resource_id:
                continue
            if row["status"] == "APPROVED" and row["expires_at"] <= now:
                continue
            result.append({"gate_id": row["gate_id"], "task_id": row["task_id"], "resource_id": row["resource_id"], "requested_operation": _json(row["requested_operation"]), "status": row["status"], "expires_at": row["expires_at"], "revision": row["revision"]})
        return result

    def gate_scope(self, gate_id):
        row = self.con.execute("SELECT task_id,resource_id FROM gates WHERE gate_id=?", (gate_id,)).fetchone()
        if not row:
            raise fail("INVALID_REQUEST", "gate not found")
        return row["task_id"], row["resource_id"]

    def resource_scope(self, resource_id):
        row = self._resource_row(resource_id)
        return row["task_id"], row["resource_id"]

    def _validate_task_body(self, body):
        required = ("created_by", "requested_by", "allowed_operations", "resource_budget", "prerequisite_status")
        if not isinstance(body, dict) or any(field not in body for field in required):
            raise fail("INVALID_REQUEST", "missing task contract field")
        try:
            validate_secret_free(body)
        except ValueError as exc:
            raise fail("INVALID_REQUEST", "task payload must be secret-free") from exc
        _identity(body["created_by"]); _identity(body["requested_by"])
        if not isinstance(body["allowed_operations"], list) or not isinstance(body["resource_budget"], dict) or not isinstance(body["prerequisite_status"], dict):
            raise fail("INVALID_REQUEST", "invalid task contract shape")
        for field in ("workers", "processes", "previews", "worktrees", "temporary_bytes", "artifact_bytes", "runtime_seconds"):
            value = body["resource_budget"].get(field)
            if not isinstance(value, int) or value < 0:
                raise fail("INVALID_REQUEST", "complete nonnegative budget required", field=field)
        for grant in body["allowed_operations"]:
            if not isinstance(grant, dict) or not isinstance(grant.get("operation"), str) or "target_scope" not in grant or "gate_requirement" not in grant or grant.get("policy_version") != DEFAULTS["policy_version"]:
                raise fail("INVALID_REQUEST", "invalid operation grant")

    def create_task(self, caller, key, correlation_id, body, capability_id="test"):
        def create():
            self._validate_task_body(body)
            task_id, now = generate_id("task"), utc_now()
            self.con.execute(
                "INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (task_id, _RECORD_VERSION, now, canonical_json(body["created_by"]), canonical_json(body["requested_by"]), "CREATED", body.get("risk_class", "GREEN"), body.get("task_contract_ref"), canonical_json(body["allowed_operations"]), canonical_json(body["resource_budget"]), canonical_json(body["prerequisite_status"]), None, None, None, 0, 0),
            )
            self.con.execute(
                "INSERT INTO task_execution_budgets VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (task_id, _RECORD_VERSION, DEFAULTS["policy_version"], DEFAULTS["model_calls_limit"], 0, DEFAULTS["max_live_delegations"], 0, 0, 0, DEFAULTS["provider_retry_limit"], 0, DEFAULTS["context_soft_limit_tokens"], DEFAULTS["context_hard_limit_tokens"], "OPEN", 0, now),
            )
            self._event("TASK_REQUESTED", caller, correlation_id, {"task_id": task_id, "policy_version": DEFAULTS["policy_version"]}, task_id)
            _, seq, _ = self._event("TASK_CREATED", caller, correlation_id, {"task_id": task_id, "policy_version": DEFAULTS["policy_version"]}, task_id)
            self.con.execute("UPDATE tasks SET last_event_sequence=? WHERE task_id=?", (seq, task_id))
            return {"task_id": task_id, "revision": 0, "state": "CREATED"}, task_id
        return self._mutation(caller, key, "CreateTask", body, None, capability_id, create)

    def transition_task(self, caller, key, correlation_id, task_id, expected_revision, target, reason=None, capability_id="test"):
        body = {"task_id": task_id, "target": target, "reason": reason}
        def transition():
            row = self._task_row(task_id); revision = _expected_revision(expected_revision)
            if row["revision"] != revision or not isinstance(target, str) or not allowed_transition("task", row["state"], target):
                raise fail("INVALID_STATE_TRANSITION")
            if target == "PAUSED":
                raise fail("INVALID_STATE_TRANSITION", "use PauseTask")
            if target == "TERMINAL":
                if not isinstance(reason, dict) or reason.get("outcome") not in {"SUCCEEDED", "FAILED", "CANCELLED", "EXPIRED", "BLOCKED", "UNKNOWN"}:
                    raise fail("INVALID_REQUEST", "terminal result required")
            if target != "TERMINAL" and reason is not None:
                validate_secret_free(reason)
            event_type = "TASK_TERMINAL" if target == "TERMINAL" else f"TASK_{target}"
            _, seq, _ = self._event(event_type, caller, correlation_id, {"target": target, "reason": reason, "policy_version": DEFAULTS["policy_version"]}, task_id)
            self.con.execute("UPDATE tasks SET state=?,pause_reason=NULL,terminal_result=?,revision=revision+1,last_event_sequence=? WHERE task_id=?", (target, canonical_json(reason) if target == "TERMINAL" else None, seq, task_id))
            return {"task_id": task_id, "revision": revision + 1, "state": target}, task_id
        return self._mutation(caller, key, "TransitionTask", body, expected_revision, capability_id, transition)

    def _insert_checkpoint(self, caller, correlation_id, task, snapshot):
        try:
            validate_secret_free(snapshot)
        except ValueError as exc:
            raise fail("CHECKPOINT_FAILED", "checkpoint must be secret-free") from exc
        active_ids = snapshot.get("active_resource_ids", [])
        if not isinstance(active_ids, list) or not isinstance(snapshot.get("pending_validation", []), list) or not isinstance(snapshot.get("evidence_refs", []), list):
            raise fail("CHECKPOINT_FAILED", "invalid checkpoint shape")
        for resource_id in active_ids:
            row = self._resource_row(resource_id)
            if row["task_id"] != task["task_id"] or row["state"] == "TERMINAL":
                raise fail("CHECKPOINT_FAILED", "checkpoint resource mismatch")
        checkpoint_id, now = generate_id("chk"), utc_now()
        self.con.execute("INSERT INTO checkpoints VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (checkpoint_id, task["task_id"], _RECORD_VERSION, now, canonical_json(caller), task["state"], snapshot.get("branch"), snapshot.get("worktree"), snapshot.get("head_sha"), canonical_json(active_ids), canonical_json(snapshot.get("pending_validation", [])), canonical_json(snapshot["next_permitted_action"]) if snapshot.get("next_permitted_action") else None, canonical_json(snapshot["blocking_reason"]) if snapshot.get("blocking_reason") else None, canonical_json(snapshot["provider_state"]) if snapshot.get("provider_state") else None, canonical_json(snapshot.get("evidence_refs", []))))
        _, seq, _ = self._event("CHECKPOINT_CREATED", caller, correlation_id, {"checkpoint_id": checkpoint_id, "policy_version": DEFAULTS["policy_version"]}, task["task_id"])
        return checkpoint_id, seq

    def create_checkpoint(self, caller, key, correlation_id, task_id, expected_revision, snapshot, capability_id="test"):
        def create():
            task = self._task_row(task_id); revision = _expected_revision(expected_revision)
            if task["revision"] != revision:
                raise fail("CHECKPOINT_FAILED", "task revision conflict")
            checkpoint_id, seq = self._insert_checkpoint(caller, correlation_id, task, snapshot)
            self.con.execute("UPDATE tasks SET current_checkpoint_id=?,revision=revision+1,last_event_sequence=? WHERE task_id=?", (checkpoint_id, seq, task_id))
            return {"checkpoint_id": checkpoint_id, "revision": revision + 1}, checkpoint_id
        return self._mutation(caller, key, "CreateCheckpoint", {"task_id": task_id, "snapshot": snapshot}, expected_revision, capability_id, create)

    def pause_task(self, caller, key, correlation_id, task_id, expected_revision, reason, snapshot, capability_id="test"):
        def pause():
            task = self._task_row(task_id); revision = _expected_revision(expected_revision)
            if task["revision"] != revision or task["state"] not in {"READY", "RUNNING", "VALIDATING", "REVIEW"}:
                raise fail("INVALID_STATE_TRANSITION")
            if not isinstance(reason, dict) or reason.get("code") not in {"PROVIDER_QUOTA", "PROVIDER_TEMPORARY_FAILURE", "OPERATOR_PAUSE", "RECOVERY"}:
                raise fail("INVALID_REQUEST", "typed pause reason required")
            checkpoint_id, _ = self._insert_checkpoint(caller, correlation_id, task, snapshot)
            _, seq, _ = self._event("TASK_PAUSED", caller, correlation_id, {"reason": reason, "checkpoint_id": checkpoint_id, "policy_version": DEFAULTS["policy_version"]}, task_id)
            self.con.execute("UPDATE tasks SET state='PAUSED',pause_reason=?,current_checkpoint_id=?,revision=revision+1,last_event_sequence=? WHERE task_id=?", (canonical_json(reason), checkpoint_id, seq, task_id))
            return {"task_id": task_id, "checkpoint_id": checkpoint_id, "state": "PAUSED", "revision": revision + 1}, task_id
        return self._mutation(caller, key, "PauseTask", {"task_id": task_id, "reason": reason, "snapshot": snapshot}, expected_revision, capability_id, pause)

    def resume_task(self, caller, key, correlation_id, task_id, expected_revision, checkpoint_id, capability_id="test"):
        def resume():
            task = self._task_row(task_id); revision = _expected_revision(expected_revision)
            if task["revision"] != revision or task["state"] != "PAUSED" or task["current_checkpoint_id"] != checkpoint_id:
                raise fail("INVALID_STATE_TRANSITION")
            checkpoint = self.con.execute("SELECT * FROM checkpoints WHERE checkpoint_id=? AND task_id=?", (checkpoint_id, task_id)).fetchone()
            if not checkpoint:
                raise fail("CHECKPOINT_FAILED", "current checkpoint unavailable")
            require_semver(checkpoint["schema_version"])
            active = _json(checkpoint["active_resource_ids"])
            for resource_id in active:
                reconciled = self.con.execute("SELECT payload FROM audit_events WHERE event_type='RECONCILIATION_RECORDED' AND resource_id=? ORDER BY sequence DESC LIMIT 1", (resource_id,)).fetchone()
                if not reconciled or _json(reconciled["payload"]).get("result") != "MATCHED":
                    raise fail("TASK_BLOCKED", "matching reconciliation required")
            if not admission_ready(self.con):
                raise fail("TASK_BLOCKED", "registry recovery requires reconciliation")
            _, seq, _ = self._event("TASK_RESUMED", caller, correlation_id, {"checkpoint_id": checkpoint_id, "policy_version": DEFAULTS["policy_version"]}, task_id)
            self.con.execute("UPDATE tasks SET state='READY',pause_reason=NULL,revision=revision+1,last_event_sequence=? WHERE task_id=?", (seq, task_id))
            return {"task_id": task_id, "state": "READY", "revision": revision + 1}, task_id
        return self._mutation(caller, key, "ResumeTask", {"task_id": task_id, "checkpoint_id": checkpoint_id}, expected_revision, capability_id, resume)

    def _matching_grant(self, task, requested_operation):
        if not isinstance(requested_operation, dict) or not isinstance(requested_operation.get("operation"), str) or "target_scope" not in requested_operation:
            raise fail("INVALID_REQUEST", "bounded requested operation required")
        for grant in _json(task["allowed_operations"]):
            if grant.get("operation") == requested_operation["operation"] and _same(grant.get("target_scope"), requested_operation.get("target_scope")):
                return grant
        raise fail("UNAUTHORIZED", "operation is outside immutable task scope")

    def _consume_required_gate_check(self, caller, correlation_id, task_id, resource_id, operation, gate_id, requirement):
        if requirement not in {True, "REQUIRED", "HUMAN_GATE_REQUIRED"}:
            return
        if not gate_id:
            raise fail("GATE_REQUIRED")
        row = self.con.execute("SELECT * FROM gates WHERE gate_id=?", (gate_id,)).fetchone()
        if not row or row["task_id"] != task_id or row["resource_id"] not in (None, resource_id) or not _same(_json(row["requested_operation"]), operation):
            raise fail("GATE_REQUIRED")
        if row["status"] == "CONSUMED":
            raise fail("GATE_ALREADY_CONSUMED")
        if row["status"] == "DENIED":
            raise fail("GATE_DENIED")
        if row["status"] != "APPROVED" or not row["expires_at"] or row["expires_at"] <= utc_now():
            raise fail("GATE_EXPIRED" if row["expires_at"] else "GATE_REQUIRED")
        consumed_at = utc_now()
        _, seq, _ = self._event("GATE_CONSUMED", caller, correlation_id, {"gate_id": gate_id, "operation": operation}, task_id, row["resource_id"])
        self.con.execute("UPDATE gates SET status='CONSUMED',consumed_at=?,revision=revision+1,last_event_sequence=? WHERE gate_id=?", (consumed_at, seq, gate_id))

    def allocate_resource(self, caller, key, correlation_id, task_id, body, capability_id="test"):
        def allocate():
            task = self._task_row(task_id)
            if task["state"] in {"PAUSED", "BLOCKED"}:
                raise fail("TASK_BLOCKED")
            if task["state"] == "TERMINAL":
                raise fail("TASK_TERMINAL")
            if task["state"] not in {"READY", "RUNNING", "VALIDATING"}:
                raise fail("INVALID_STATE_TRANSITION")
            try:
                validate_secret_free(body)
            except ValueError as exc:
                raise fail("INVALID_REQUEST", "secret-free resource allocation required") from exc
            resource_type = body.get("resource_type")
            if resource_type not in _BUDGET_FIELDS:
                raise fail("INVALID_REQUEST", "unsupported resource type")
            requested_operation = body.get("requested_operation")
            grant = self._matching_grant(task, requested_operation)
            self._consume_required_gate_check(caller, correlation_id, task_id, body.get("resource_id"), requested_operation, body.get("gate_id"), grant.get("gate_requirement"))
            expected = body.get("expected_identity")
            metadata = body.get("metadata", {})
            if not isinstance(expected, dict) or not isinstance(metadata, dict):
                raise fail("INVALID_REQUEST", "expected identity and metadata required")
            if resource_type == "WORKER":
                try:
                    expected = validate_launch_expectation(expected)
                except ValueError as exc:
                    raise fail("INVALID_REQUEST", "valid worker launch expectation required") from exc
            elif resource_type == "PROCESS" and not {"pid", "start_time", "boot_id"} <= set(expected):
                raise fail("INVALID_REQUEST", "strong process identity required")
            if resource_type == "PREVIEW" and not preview_allowed(metadata):
                raise fail("UNAUTHORIZED", "preview policy denied")
            budget = _json(task["resource_budget"]); field = _BUDGET_FIELDS[resource_type]
            if resource_type in {"TEMP_DIR", "ARTIFACT"}:
                requested = body.get("budget_reservation", {}).get(field, 0)
                if not isinstance(requested, int) or requested < 0:
                    raise fail("INVALID_REQUEST", "byte reservation required")
                consumed = sum(_json(row["budget_reservation"]).get(field, 0) for row in repositories.task_resources(self.con, task_id) if row["state"] != "TERMINAL")
                if consumed + requested > budget[field]:
                    raise fail("BUDGET_EXCEEDED")
            else:
                count = self.con.execute("SELECT count(*) FROM resource_leases WHERE task_id=? AND resource_type=? AND state!='TERMINAL'", (task_id, resource_type)).fetchone()[0]
                if count >= budget[field]:
                    raise fail("BUDGET_EXCEEDED")
            if resource_type == "WORKER":
                global_workers = self.con.execute("SELECT count(*) FROM resource_leases WHERE resource_type='WORKER' AND state!='TERMINAL'").fetchone()[0]
                if global_workers >= DEFAULTS["max_workers_global"]:
                    raise fail("RESOURCE_LIMIT_REACHED")
            resource_id, now = generate_id("rsrc"), utc_now()
            try:
                self.con.execute("INSERT INTO resource_leases VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (resource_id, task_id, _RECORD_VERSION, resource_type, now, canonical_json(caller), "ALLOCATED", canonical_json(requested_operation), canonical_json(body.get("budget_reservation", {})), canonical_json(expected), None, int(bool(body.get("heartbeat_required", resource_type in {"WORKER", "PROCESS", "PREVIEW", "DELEGATED_RUN"}))), None, body.get("ttl_seconds"), canonical_json(body.get("cleanup_policy", {})), canonical_json(body.get("cleanup_authority", {})), canonical_json(metadata), None, 0, 0))
            except sqlite3.IntegrityError as exc:
                raise fail("RESOURCE_LIMIT_REACHED", "exclusive resource reservation exists") from exc
            _, seq, _ = self._event("RESOURCE_ALLOCATED", caller, correlation_id, {"resource_id": resource_id, "resource_type": resource_type, "policy_version": DEFAULTS["policy_version"]}, task_id, resource_id)
            self.con.execute("UPDATE resource_leases SET last_event_sequence=? WHERE resource_id=?", (seq, resource_id))
            return {"resource_id": resource_id, "revision": 0, "state": "ALLOCATED"}, resource_id
        return self._mutation(caller, key, "AllocateResource", {"task_id": task_id, **body}, None, capability_id, allocate)

    def bind_resource(self, caller, key, correlation_id, resource_id, expected_revision, identity, launch_nonce=None, capability_id="test"):
        def bind():
            row = self._resource_row(resource_id); revision = _expected_revision(expected_revision)
            if row["revision"] != revision or row["state"] != "ALLOCATED":
                raise fail("IDENTITY_BIND_FAILED")
            if row["resource_type"] == "WORKER":
                try:
                    expectation = validate_launch_expectation(_json(row["expected_identity"]))
                    observation = validate_observed_process_identity(identity)
                    nonce = validate_launch_nonce(launch_nonce)
                except ValueError as exc:
                    raise fail("INVALID_REQUEST", "valid worker identity binding required") from exc
                if not launch_nonce_matches(expectation, nonce):
                    raise fail("IDENTITY_MISMATCH")
                verifier = self.worker_identity_verifier
                if verifier is None:
                    raise fail("IDENTITY_BIND_FAILED", "worker identity verifier is not configured")
                try:
                    verified_evidence = verifier.verify(resource_id, expectation, observation)
                except Exception as exc:
                    raise fail("IDENTITY_BIND_FAILED", "worker identity verification failed") from exc
                if not matches_launch_expectation(expectation, observation, nonce, verified_evidence):
                    raise fail("IDENTITY_MISMATCH")
                bound_identity = observation
            else:
                if not isinstance(identity, dict) or not _same(_json(row["expected_identity"]), identity):
                    raise fail("IDENTITY_MISMATCH")
                bound_identity = identity
            try:
                self._event("IDENTITY_BOUND", caller, correlation_id, {"resource_id": resource_id}, row["task_id"], resource_id)
                _, seq, _ = self._event("RESOURCE_ACTIVE", caller, correlation_id, {"resource_id": resource_id}, row["task_id"], resource_id)
                self.con.execute("UPDATE resource_leases SET bound_identity=?,state='ACTIVE',revision=revision+1,last_event_sequence=? WHERE resource_id=?", (canonical_json(bound_identity), seq, resource_id))
            except ControlPlaneError:
                raise
            except Exception as exc:
                raise fail("IDENTITY_BIND_FAILED") from exc
            return {"resource_id": resource_id, "revision": revision + 1, "state": "ACTIVE"}, resource_id
        body = {"resource_id": resource_id, "identity": identity}
        if launch_nonce is not None:
            body["launch_nonce"] = launch_nonce
        return self._mutation(caller, key, "BindResourceIdentity", body, expected_revision, capability_id, bind)

    def terminalize_resource(self, caller, key, correlation_id, resource_id, expected_revision, reason, capability_id="test"):
        def terminalize():
            row = self._resource_row(resource_id); revision = _expected_revision(expected_revision)
            if row["revision"] != revision or row["state"] == "TERMINAL":
                raise fail("INVALID_STATE_TRANSITION")
            if not isinstance(reason, dict) or not isinstance(reason.get("code"), str):
                raise fail("INVALID_REQUEST", "typed terminal reason required")
            if reason["code"] == "RESOURCE_CREATION_FAILED":
                self._event("RESOURCE_CREATION_FAILED", caller, correlation_id, {"resource_id": resource_id, "reason": reason}, row["task_id"], resource_id)
            _, seq, _ = self._event("RESOURCE_TERMINAL", caller, correlation_id, {"resource_id": resource_id, "reason": reason}, row["task_id"], resource_id)
            self.con.execute("UPDATE resource_leases SET state='TERMINAL',terminal_reason=?,revision=revision+1,last_event_sequence=? WHERE resource_id=?", (canonical_json(reason), seq, resource_id))
            return {"resource_id": resource_id, "state": "TERMINAL", "revision": revision + 1}, resource_id
        return self._mutation(caller, key, "MarkResourceTerminal", {"resource_id": resource_id, "reason": reason}, expected_revision, capability_id, terminalize)

    def record_heartbeat(self, caller, key, correlation_id, task_id, resource_id, sequence, status="EXPECTED", evidence_ref=None, capability_id="test"):
        body = {"task_id": task_id, "resource_id": resource_id, "sequence": sequence, "status": status, "evidence_ref": evidence_ref}
        def record():
            task = self._task_row(task_id)
            if resource_id:
                resource = self._resource_row(resource_id)
                if resource["task_id"] != task_id:
                    raise fail("UNAUTHORIZED", "resource is outside task")
            if not isinstance(sequence, int) or sequence < 0 or status not in {"EXPECTED", "PAUSED", "COMPLETING", "FAILED", "UNKNOWN"}:
                raise fail("INVALID_REQUEST", "invalid heartbeat")
            scope = f"resource:{resource_id}" if resource_id else f"task:{task_id}"
            old = self.con.execute("SELECT sequence FROM heartbeats WHERE heartbeat_scope=?", (scope,)).fetchone()
            if old and sequence <= old[0]:
                raise fail("INVALID_REQUEST", "heartbeat sequence out of order")
            now = utc_now(); event_id, _, _ = self._event("HEARTBEAT_RECORDED", caller, correlation_id, body, task_id, resource_id)
            self.con.execute("INSERT INTO heartbeats VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(heartbeat_scope) DO UPDATE SET sequence=excluded.sequence,producer_monotonic_ns=excluded.producer_monotonic_ns,observed_at=excluded.observed_at,received_at=excluded.received_at,status=excluded.status,evidence_ref=excluded.evidence_ref,last_event_id=excluded.last_event_id", (scope, _RECORD_VERSION, task_id, resource_id, canonical_json(caller), sequence, None, now, now, status, evidence_ref, event_id))
            if resource_id:
                self.con.execute("UPDATE resource_leases SET last_heartbeat=? WHERE resource_id=?", (now, resource_id))
            return {"heartbeat_scope": scope, "sequence": sequence}, event_id
        return self._mutation(caller, key, "RecordHeartbeat", body, None, capability_id, record)

    def create_gate(self, caller, key, correlation_id, task_id, body, capability_id="test"):
        def create():
            self._task_row(task_id)
            validate_secret_free(body)
            resource_id = body.get("resource_id")
            if resource_id:
                resource = self._resource_row(resource_id)
                if resource["task_id"] != task_id:
                    raise fail("UNAUTHORIZED", "gate resource is outside task")
            operation = body.get("requested_operation")
            if not isinstance(operation, dict) or not isinstance(body.get("required_authority"), dict):
                raise fail("INVALID_REQUEST", "exact gate scope required")
            gate_id, now = generate_id("gate"), utc_now()
            self.con.execute("INSERT INTO gates VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (gate_id, _RECORD_VERSION, task_id, body.get("resource_id"), canonical_json(operation), body.get("risk_class", "YELLOW"), now, canonical_json(caller), canonical_json(body["required_authority"]), "PENDING", None, None, None, None, None, 0, 0))
            _, seq, _ = self._event("GATE_REQUESTED", caller, correlation_id, {"gate_id": gate_id, "requested_operation": operation}, task_id, body.get("resource_id"))
            self.con.execute("UPDATE gates SET last_event_sequence=? WHERE gate_id=?", (seq, gate_id))
            return {"gate_id": gate_id, "revision": 0, "status": "PENDING"}, gate_id
        return self._mutation(caller, key, "CreateGate", {"task_id": task_id, **body}, None, capability_id, create)

    def resolve_gate(self, caller, key, correlation_id, gate_id, expected_revision, approve, authorization_reference=None, expires_at=None, capability_id="test"):
        def resolve():
            row = self.con.execute("SELECT * FROM gates WHERE gate_id=?", (gate_id,)).fetchone(); revision = _expected_revision(expected_revision)
            if not row:
                raise fail("INVALID_REQUEST", "gate not found")
            if row["revision"] != revision or row["status"] != "PENDING":
                raise fail("INVALID_STATE_TRANSITION")
            if approve:
                if not isinstance(authorization_reference, str) or not authorization_reference:
                    raise fail("INVALID_REQUEST", "approval reference required")
                try:
                    validate_timestamp(expires_at)
                except ValueError as exc:
                    raise fail("INVALID_REQUEST", "valid expiry required") from exc
                if expires_at <= utc_now():
                    raise fail("GATE_EXPIRED")
            status, now = ("APPROVED", utc_now()) if approve else ("DENIED", None)
            _, seq, _ = self._event("GATE_DECIDED", caller, correlation_id, {"gate_id": gate_id, "status": status}, row["task_id"], row["resource_id"])
            self.con.execute("UPDATE gates SET status=?,approved_by=?,approved_at=?,expires_at=?,authorization_reference=?,revision=revision+1,last_event_sequence=? WHERE gate_id=?", (status, canonical_json(caller) if approve else None, now, expires_at if approve else None, authorization_reference if approve else None, seq, gate_id))
            return {"gate_id": gate_id, "status": status, "revision": revision + 1}, gate_id
        return self._mutation(caller, key, "ResolveGate", {"gate_id": gate_id, "approve": approve, "authorization_reference": authorization_reference, "expires_at": expires_at}, expected_revision, capability_id, resolve)

    def consume_gate(self, caller, key, correlation_id, gate_id, expected_revision, operation, now=None, capability_id="test"):
        def consume():
            row = self.con.execute("SELECT * FROM gates WHERE gate_id=?", (gate_id,)).fetchone(); revision = _expected_revision(expected_revision); observed_now = now or utc_now()
            if not row:
                raise fail("INVALID_REQUEST", "gate not found")
            if row["status"] == "CONSUMED": raise fail("GATE_ALREADY_CONSUMED")
            if row["status"] == "DENIED": raise fail("GATE_DENIED")
            if row["status"] == "EXPIRED" or (row["expires_at"] and row["expires_at"] <= observed_now): raise fail("GATE_EXPIRED")
            if row["revision"] != revision or row["status"] != "APPROVED" or not _same(_json(row["requested_operation"]), operation):
                raise fail("INVALID_STATE_TRANSITION")
            _, seq, _ = self._event("GATE_CONSUMED", caller, correlation_id, {"gate_id": gate_id, "operation": operation}, row["task_id"], row["resource_id"])
            self.con.execute("UPDATE gates SET status='CONSUMED',consumed_at=?,revision=revision+1,last_event_sequence=? WHERE gate_id=?", (observed_now, seq, gate_id))
            return {"gate_id": gate_id, "status": "CONSUMED", "revision": revision + 1}, gate_id
        return self._mutation(caller, key, "ConsumeGate", {"gate_id": gate_id, "operation": operation}, expected_revision, capability_id, consume)

    def append_event(self, caller, key, correlation_id, task_id, resource_id, event_type, payload, capability_id="test"):
        def append():
            if event_type not in _ALLOWED_APPEND_EVENTS:
                raise fail("UNAUTHORIZED", "authoritative event type requires service mutation")
            if task_id:
                self._task_row(task_id)
            if resource_id:
                resource = self._resource_row(resource_id)
                if task_id and resource["task_id"] != task_id:
                    raise fail("UNAUTHORIZED", "resource is outside task")
            validate_secret_free(payload)
            event_id, _, _ = self._event(event_type, caller, correlation_id, payload, task_id, resource_id)
            return {"event_id": event_id}, event_id
        return self._mutation(caller, key, "AppendEvent", {"task_id": task_id, "resource_id": resource_id, "event_type": event_type, "payload": payload}, None, capability_id, append)

    def reconcile_observation(self, caller, key, correlation_id, resource_id, adapter_type, adapter_version, observation, observed_at, evidence_ref, capability_id="test"):
        def reconcile_one():
            row = self._resource_row(resource_id)
            if not isinstance(adapter_type, str) or not isinstance(adapter_version, str) or not isinstance(observation, dict) or not isinstance(evidence_ref, str):
                raise fail("INVALID_REQUEST", "bounded observation required")
            try:
                validate_timestamp(observed_at)
            except ValueError as exc:
                raise fail("INVALID_REQUEST", "invalid observation timestamp") from exc
            expected = ExpectedResource(row["task_id"], resource_id, row["resource_type"], row["state"], _json(row["expected_identity"]), _json(row["bound_identity"]) if row["bound_identity"] else None, bool(row["heartbeat_required"]), row["ttl_seconds"], DEFAULTS["policy_version"])
            observed = ObservedResource(adapter_type, adapter_version, observation, observed_at, evidence_ref)
            result = reconcile(expected, observed)
            payload = {"result": result.result, "adapter_type": adapter_type, "adapter_version": adapter_version, "evidence_refs": list(result.evidence_refs), "policy_version": DEFAULTS["policy_version"], "blocking_reason": result.blocking_reason}
            event_id, _, _ = self._event("RECONCILIATION_RECORDED", caller, correlation_id, payload, row["task_id"], resource_id)
            pending = self.con.execute("SELECT metadata_value FROM registry_metadata WHERE metadata_key='recovery_pending_resources'").fetchone()
            if pending:
                values = _json(pending[0])
                if resource_id in values:
                    values.remove(resource_id)
                    self.con.execute("UPDATE registry_metadata SET metadata_value=?,updated_at=? WHERE metadata_key='recovery_pending_resources'", (canonical_json(values), utc_now()))
                    if not values:
                        self.con.execute("UPDATE registry_metadata SET metadata_value='READY',updated_at=? WHERE metadata_key='admission_state'", (utc_now(),))
            return {"event_id": event_id, "resource_id": resource_id, "result": result.result, "blocking_reason": result.blocking_reason}, event_id
        return self._mutation(caller, key, "ReconcileObservation", {"resource_id": resource_id, "adapter_type": adapter_type, "adapter_version": adapter_version, "observation": observation, "observed_at": observed_at, "evidence_ref": evidence_ref}, None, capability_id, reconcile_one, require_ready=False)

    def evaluate_heartbeats(self, caller, correlation_id, now):
        """Policy projection helper used by hermetic tests; never mutates runtime."""
        try:
            validate_timestamp(now)
        except ValueError as exc:
            raise fail("INVALID_REQUEST", "invalid evaluation time") from exc
        changed = []
        with immediate(self.con):
            for row in self.con.execute("SELECT * FROM resource_leases WHERE heartbeat_required=1 AND state IN ('ACTIVE','HEARTBEAT_MISSED')").fetchall():
                if not row["last_heartbeat"]:
                    continue
                elapsed = _seconds_between(row["last_heartbeat"], now)
                target = "HEARTBEAT_MISSED" if elapsed >= DEFAULTS["heartbeat_miss_seconds"] and row["state"] == "ACTIVE" else "STALE_CANDIDATE" if elapsed >= DEFAULTS["heartbeat_miss_seconds"] + DEFAULTS["heartbeat_grace_seconds"] else None
                if not target:
                    continue
                event_type = target
                _, seq, _ = self._event(event_type, caller, correlation_id, {"deadline_seconds": DEFAULTS["heartbeat_miss_seconds"], "last_heartbeat": row["last_heartbeat"]}, row["task_id"], row["resource_id"])
                self.con.execute("UPDATE resource_leases SET state=?,revision=revision+1,last_event_sequence=? WHERE resource_id=?", (target, seq, row["resource_id"]))
                changed.append(row["resource_id"])
        return changed


def _seconds_between(start: str, end: str) -> float:
    from datetime import datetime
    return (datetime.fromisoformat(end.replace("Z", "+00:00")) - datetime.fromisoformat(start.replace("Z", "+00:00"))).total_seconds()
