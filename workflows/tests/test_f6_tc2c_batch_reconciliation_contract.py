from __future__ import annotations

import json
from collections import deque
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = ROOT / "workflows" / "MGB-030-enrichment-reel.json"


PERIODIC_TRIGGER = "SCHEDULE — Consumir fila de transcrição"
PERIODIC_STATE = "DB — Determinar fluxo periódico"
PERIODIC_RECONCILE = "IF — Reconciliar LRO?"
PERIODIC_CLAIM = "IF — Claim autorizado?"
CLAIM = "DB — Criar tentativa processing"
INITIAL_HTTP = "HTTP — Enricher /v1/enrichments"
INITIAL_VALIDATE = "DATA — Validar resposta Enricher"
INITIAL_PENDING = "IF — Batch pendente?"
PERSIST_LRO = "DB — Persistir LRO Batch"
RECONCILE_HTTP = "HTTP — Enricher /v1/enrichments/reconcile"
RECONCILE_VALIDATE = "DATA — Validar resposta reconciliação"
RECONCILE_PENDING = "IF — Reconciliação pendente?"
RECONCILE_FAILURE = "DATA — Normalizar falha reconciliação"
PROVIDER_TERMINAL = "IF — Falha terminal do provider?"
RECONCILE_COMPLETE = "DB — Persistir reconciliação e concluir"
RECONCILE_FAIL = "DB — Registrar falha Batch"


def workflow() -> tuple[dict[str, dict], dict]:
    parsed = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))
    return {node["name"]: node for node in parsed["nodes"]}, parsed["connections"]


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


def query(nodes: dict[str, dict], name: str) -> str:
    return nodes[name]["parameters"]["query"]


def test_initial_202_persists_only_the_known_lro_and_stays_processing() -> None:
    nodes, connections = workflow()
    validator = nodes[INITIAL_VALIDATE]["parameters"]["jsCode"]
    persistence = query(nodes, PERSIST_LRO)

    assert "batch_pending" in validator
    assert "batch_submission?.state === 'processing'" in validator
    assert "provider_request_id" in validator
    assert successors(connections, INITIAL_PENDING, 0) == {PERSIST_LRO}
    assert "status = 'processing'" in persistence
    assert "provider_request_id IS NULL" in persistence
    assert "provider_request_id = $" in persistence
    assert "transcription_status = 'processing'" in persistence
    assert "transcription_attempt_id" in persistence
    assert "finished_at" not in persistence
    assert "INSERT INTO app.reel_enrichments" not in persistence


def test_periodic_flow_reconciles_known_lro_before_any_new_claim() -> None:
    nodes, connections = workflow()
    state_sql = query(nodes, PERIODIC_STATE)

    assert successors(connections, PERIODIC_TRIGGER) == {"DATA — Preparar consumidor periódico"}
    assert can_reach(connections, PERIODIC_TRIGGER, PERIODIC_STATE)
    assert successors(connections, PERIODIC_RECONCILE, 0) == {RECONCILE_HTTP}
    assert successors(connections, PERIODIC_RECONCILE, 1) == {PERIODIC_CLAIM}
    assert successors(connections, PERIODIC_CLAIM, 0) == {"DATA — Criar attempt_id"}
    assert successors(connections, PERIODIC_CLAIM, 1) == set()
    assert "pg_try_advisory_xact_lock(308030::BIGINT)" in state_sql
    assert "'RECONCILE'" in state_sql
    assert "'RECOVERY_REQUIRED'" in state_sql
    assert "'CLAIM'" in state_sql
    assert "'BUSY'" in state_sql
    assert "provider_request_id IS NULL" in state_sql
    assert "WHEN processing.provider_request_id IS NULL THEN 'RECOVERY_REQUIRED'" in state_sql
    assert "ELSE 'RECONCILE'" in state_sql
    assert not can_reach(connections, RECONCILE_HTTP, CLAIM)


def test_reconcile_http_and_pending_response_never_claim_or_terminalize() -> None:
    nodes, connections = workflow()
    http = nodes[RECONCILE_HTTP]
    validator = nodes[RECONCILE_VALIDATE]["parameters"]["jsCode"]

    assert http["parameters"]["method"] == "POST"
    assert http["parameters"]["url"].endswith("/reconcile")
    assert http["retryOnFail"] is False
    assert http["parameters"]["headerParameters"]["parameters"][1]["value"] == "={{ $json.attempt_id }}"
    assert "provider_request_id" in http["parameters"]["jsonBody"]
    assert "pending" in validator
    assert successors(connections, RECONCILE_PENDING, 0) == set()
    assert not can_reach(connections, RECONCILE_PENDING, CLAIM)


def test_reconcile_completion_and_failure_are_exactly_guarded() -> None:
    nodes, connections = workflow()
    completion = query(nodes, RECONCILE_COMPLETE)
    failure = query(nodes, RECONCILE_FAIL)
    error_code = nodes[RECONCILE_FAILURE]["parameters"]["jsCode"]

    assert successors(connections, RECONCILE_VALIDATE) == {"IF — Resposta reconciliação válida?"}
    assert successors(connections, "IF — Resposta reconciliação válida?", 0) == {RECONCILE_PENDING}
    assert successors(connections, RECONCILE_PENDING, 1) == {RECONCILE_COMPLETE}
    assert successors(connections, RECONCILE_FAILURE) == {PROVIDER_TERMINAL}
    assert successors(connections, PROVIDER_TERMINAL, 0) == {RECONCILE_FAIL}
    assert successors(connections, PROVIDER_TERMINAL, 1) == set()
    assert "provider_terminal === true" in error_code
    assert "provider_terminal: false" in error_code
    assert "provider_request_id === attempt.provider_request_id" in error_code
    assert "attempt_id = $1::UUID" in completion
    assert "provider_request_id = $8::TEXT" in completion
    assert "source_object_key" in completion
    assert "expected_sha256" in completion
    assert "expected_size_bytes" in completion
    assert "contract_version" in completion
    assert "attempt_id = $1::UUID" in failure
    assert "provider_request_id = $2" in failure
    assert "status = 'processing'" in failure
    assert "retryable = FALSE" in failure


def test_sync_initial_completion_and_tc2a_claim_invariants_remain_present() -> None:
    nodes, _ = workflow()
    claim_sql = query(nodes, CLAIM)
    initial_http = nodes[INITIAL_HTTP]

    assert "pg_try_advisory_xact_lock(308030::BIGINT)" in claim_sql
    assert "FOR UPDATE SKIP LOCKED" in claim_sql
    assert "ORDER BY reel.updated_at ASC, reel.id ASC" in claim_sql
    assert "processing_reel.transcription_status = 'processing'" in claim_sql
    assert initial_http["retryOnFail"] is False
