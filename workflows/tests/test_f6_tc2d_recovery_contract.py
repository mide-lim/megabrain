from __future__ import annotations

import json
import re
from collections import deque
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = ROOT / "workflows" / "MGB-030-enrichment-reel.json"
ENRICHER_MAIN = ROOT / "services" / "enricher" / "app" / "main.py"

INITIAL_FAILURE = "DB — Registrar falha da tentativa"
NORMAL_CLAIM = "DB — Criar tentativa processing"
MANUAL_RETRY_IF = "IF — Retry manual interno?"
MANUAL_RETRY_ATTEMPT_ID = "DATA — Criar attempt_id retry manual"
MANUAL_RETRY = "DB — Criar retry manual processing"
PERIODIC_STATE = "DB — Determinar fluxo periódico"
PERIODIC_RECONCILE = "IF — Reconciliar LRO?"
PERIODIC_CLAIM = "IF — Claim autorizado?"
RECONCILE_HTTP = "HTTP — Enricher /v1/enrichments/reconcile"
RECONCILE_COMPLETE = "DB — Persistir reconciliação e concluir"
RECONCILE_FAIL = "DB — Registrar falha Batch"
COMPLETE_PERSISTED = "IF — Resultado terminal persistido?"
FAILURE_PERSISTED = "IF — Falha Batch persistida?"
SUCCESS_CLEANUP_DATA = "DATA — Preparar cleanup após conclusão"
FAILURE_CLEANUP_DATA = "DATA — Preparar cleanup após falha Batch"
SUCCESS_CLEANUP = "HTTP — Cleanup após conclusão"
FAILURE_CLEANUP = "HTTP — Cleanup após falha Batch"


def workflow() -> tuple[dict[str, dict], dict]:
    parsed = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))
    return {node["name"]: node for node in parsed["nodes"]}, parsed["connections"]


def query(nodes: dict[str, dict], name: str) -> str:
    return nodes[name]["parameters"]["query"]


def code(nodes: dict[str, dict], name: str) -> str:
    return nodes[name]["parameters"]["jsCode"]


def successors(connections: dict, name: str, output: int | None = None) -> set[str]:
    outputs = connections.get(name, {}).get("main", [])
    selected = outputs if output is None else outputs[output : output + 1]
    return {edge["node"] for branch in selected for edge in branch}


def can_reach(connections: dict, source: str, target: str) -> bool:
    pending = deque(successors(connections, source))
    seen: set[str] = set()
    while pending:
        current = pending.popleft()
        if current == target:
            return True
        if current not in seen:
            seen.add(current)
            pending.extend(successors(connections, current))
    return False


def test_ambiguous_initial_outcomes_preserve_processing_without_lro_or_cleanup() -> None:
    nodes, connections = workflow()
    terminal_failure = query(nodes, INITIAL_FAILURE)
    normalizer = code(nodes, "DATA — Normalizar falha Enricher")
    validator = code(nodes, "DATA — Validar resposta Enricher")

    assert "STT_BATCH_SUBMISSION_UNKNOWN" in normalizer
    assert "RESULT_UNKNOWN" in normalizer
    assert "INVALID_ENRICHER_RESPONSE" in validator
    assert "status = 'failed'" in terminal_failure
    assert "STT_BATCH_SUBMISSION_UNKNOWN" not in terminal_failure
    assert "RESULT_UNKNOWN" not in terminal_failure
    assert "INVALID_ENRICHER_RESPONSE" not in terminal_failure
    assert "provider_request_id" not in terminal_failure
    assert "finished_at" in terminal_failure
    assert "provider_may_be_active" in terminal_failure
    assert not can_reach(connections, INITIAL_FAILURE, SUCCESS_CLEANUP)
    assert not can_reach(connections, INITIAL_FAILURE, FAILURE_CLEANUP)


def test_processing_first_scheduler_has_human_gated_null_lro_recovery() -> None:
    nodes, connections = workflow()
    state = query(nodes, PERIODIC_STATE)
    reconcile_condition = json.dumps(nodes[PERIODIC_RECONCILE]["parameters"])
    claim_condition = json.dumps(nodes[PERIODIC_CLAIM]["parameters"])

    assert "pg_try_advisory_xact_lock(308030::BIGINT)" in state
    assert "WHEN processing.provider_request_id IS NULL THEN 'RECOVERY_REQUIRED'" in state
    assert "ELSE 'RECONCILE'" in state
    assert "'CLAIM'" in state
    assert "flow_state" in reconcile_condition
    assert "RECONCILE" in reconcile_condition
    assert "flow_state" in claim_condition
    assert "CLAIM" in claim_condition
    assert successors(connections, PERIODIC_RECONCILE, 0) == {RECONCILE_HTTP}
    assert successors(connections, PERIODIC_RECONCILE, 1) == {PERIODIC_CLAIM}
    assert successors(connections, PERIODIC_CLAIM, 0) == {"DATA — Criar attempt_id"}
    assert successors(connections, PERIODIC_CLAIM, 1) == set()
    assert not can_reach(connections, PERIODIC_STATE, MANUAL_RETRY)


def test_normal_claim_cannot_create_implicit_retry_lineage() -> None:
    nodes, _ = workflow()
    claim = query(nodes, NORMAL_CLAIM)

    assert "NULL::UUID" in claim
    assert "created_attempt" in claim
    assert "$json.retry_of_attempt_id" not in nodes[NORMAL_CLAIM]["parameters"]["options"][
        "queryReplacement"
    ]


def test_manual_retry_requires_exact_failed_predecessor_and_is_atomic_chain_lineage() -> None:
    nodes, connections = workflow()
    retry = query(nodes, MANUAL_RETRY)
    parameters = code(nodes, "DATA — Preparar parâmetros")

    assert "retry_trigger" in parameters
    assert "MANUAL_INTERNAL" in parameters
    assert successors(connections, MANUAL_RETRY_IF, 0) == {MANUAL_RETRY_ATTEMPT_ID}
    assert successors(connections, MANUAL_RETRY_ATTEMPT_ID) == {MANUAL_RETRY}
    assert "pg_try_advisory_xact_lock(308030::BIGINT)" in retry
    assert "$2::UUID" in retry
    assert "predecessor.status = 'failed'" in retry
    assert "FOR UPDATE OF predecessor, reel" in retry
    assert "retry_of_attempt_id" in retry
    assert "predecessor.attempt_id" in retry
    assert "'processing'" in retry
    assert "transcription_status = 'processing'" in retry
    assert "transcription_attempt_id = $1::UUID" in retry
    assert "NOT EXISTS" in retry
    assert "FROM app.reel_enrichments AS enrichment" in retry
    assert "ORDER BY previous_attempt" not in retry
    assert "STT_BATCH_PROVIDER_FAILED" in retry
    for excluded in (
        "STT_BATCH_SUBMISSION_UNKNOWN",
        "STT_BATCH_UNSUPPORTED_DURATION",
        "STT_RECONCILIATION_TIMEOUT",
        "STT_RECONCILIATION_INVALID_RESPONSE",
        "RESULT_UNKNOWN",
    ):
        assert excluded not in retry


def test_retry_and_normal_claim_share_the_same_global_concurrency_guards() -> None:
    nodes, _ = workflow()
    claim = query(nodes, NORMAL_CLAIM)
    retry = query(nodes, MANUAL_RETRY)

    for statement in (claim, retry):
        assert "pg_try_advisory_xact_lock(308030::BIGINT)" in statement
        assert "transcription_status = 'processing'" in statement
        assert "NOT EXISTS" in statement
    assert "FOR UPDATE SKIP LOCKED" in claim
    assert "ORDER BY reel.updated_at ASC, reel.id ASC" in claim


def test_known_lro_remains_reconcile_only_and_no_provider_rediscovery_exists() -> None:
    nodes, connections = workflow()
    raw = WORKFLOW_PATH.read_text(encoding="utf-8").lower()
    enricher_main = ENRICHER_MAIN.read_text(encoding="utf-8").lower()
    reconcile = nodes[RECONCILE_HTTP]

    assert reconcile["parameters"]["url"].endswith("/reconcile")
    assert "provider_request_id" in reconcile["parameters"]["jsonBody"]
    assert not can_reach(connections, RECONCILE_HTTP, NORMAL_CLAIM)
    assert not can_reach(connections, RECONCILE_HTTP, MANUAL_RETRY)
    for forbidden in ("list_operations", "delete_operation", "cancel_operation"):
        assert forbidden not in raw
        assert forbidden not in enricher_main


def test_terminal_cleanup_is_strictly_after_accepted_exact_db_transitions() -> None:
    nodes, connections = workflow()
    complete = query(nodes, RECONCILE_COMPLETE)
    failure = query(nodes, RECONCILE_FAIL)
    success_condition = nodes[COMPLETE_PERSISTED]["parameters"]["conditions"]["conditions"][0][
        "leftValue"
    ]
    failure_condition = nodes[FAILURE_PERSISTED]["parameters"]["conditions"]["conditions"][0][
        "leftValue"
    ]
    success_cleanup = nodes[SUCCESS_CLEANUP]
    failure_cleanup = nodes[FAILURE_CLEANUP]

    assert "attempt_id = $1::UUID" in complete
    assert "provider_request_id = $8::TEXT" in complete
    assert re.search(
        r"RETURNING\s+reel\.id\s*,\s*reel\.transcription_status\s*;",
        complete,
        re.IGNORECASE,
    )
    assert "$json.id" in success_condition
    assert "$json.transcription_status" in success_condition
    assert "$json.transcription_status === 'completed'" in success_condition
    assert "attempt_id = $1::UUID" in failure
    assert "provider_request_id = $2" in failure
    assert re.search(r"RETURNING\s+failed_attempt\.attempt_id\s*;", failure, re.IGNORECASE)
    assert "$json.attempt_id" in failure_condition
    assert "typeof $json.attempt_id === 'string'" in failure_condition
    assert "$json.attempt_id !== ''" in failure_condition
    assert successors(connections, RECONCILE_COMPLETE) == {COMPLETE_PERSISTED}
    assert successors(connections, RECONCILE_FAIL) == {FAILURE_PERSISTED}
    assert successors(connections, COMPLETE_PERSISTED, 0) == {SUCCESS_CLEANUP_DATA}
    assert successors(connections, FAILURE_PERSISTED, 0) == {FAILURE_CLEANUP_DATA}
    assert successors(connections, SUCCESS_CLEANUP_DATA) == {SUCCESS_CLEANUP}
    assert successors(connections, FAILURE_CLEANUP_DATA) == {FAILURE_CLEANUP}
    assert successors(connections, COMPLETE_PERSISTED, 1) == set()
    assert successors(connections, FAILURE_PERSISTED, 1) == set()
    for cleanup in (success_cleanup, failure_cleanup):
        assert cleanup["parameters"]["method"] == "POST"
        assert cleanup["parameters"]["url"].endswith("/cleanup")
        assert cleanup["retryOnFail"] is False
        headers = cleanup["parameters"]["headerParameters"]["parameters"]
        assert headers[1]["name"] == "Idempotency-Key"
        assert "attempt_id" in cleanup["parameters"]["jsonBody"]


def test_ambiguous_and_processing_paths_cannot_reach_cleanup() -> None:
    nodes, connections = workflow()
    for source in (
        INITIAL_FAILURE,
        "DB — Persistir LRO Batch",
    ):
        assert not can_reach(connections, source, SUCCESS_CLEANUP)
        assert not can_reach(connections, source, FAILURE_CLEANUP)
    assert "STT_BATCH_SUBMISSION_UNKNOWN" not in query(nodes, MANUAL_RETRY)
