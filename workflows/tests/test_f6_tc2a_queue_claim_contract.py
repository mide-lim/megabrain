from __future__ import annotations

import json
from collections import deque
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = ROOT / "workflows" / "MGB-030-enrichment-reel.json"


LEGACY_TRIGGER = "SUB — Receber Reel downloaded"
PERIODIC_TRIGGER = "SCHEDULE — Consumir fila de transcrição"
PERIODIC_PARAMETERS = "DATA — Preparar consumidor periódico"
PERIODIC_STATE = "DB — Determinar fluxo periódico"
QUEUE = "DB — Enfileirar transcrição"
ATTEMPT_ID = "DATA — Criar attempt_id"
CLAIM = "DB — Criar tentativa processing"
ENRICHER = "HTTP — Enricher /v1/enrichments"


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


def test_mgb030_has_legacy_and_one_minute_periodic_activation_paths() -> None:
    nodes, connections = workflow()

    assert nodes[LEGACY_TRIGGER]["type"] == "n8n-nodes-base.executeWorkflowTrigger"
    assert nodes[PERIODIC_TRIGGER]["type"] == "n8n-nodes-base.scheduleTrigger"
    interval = nodes[PERIODIC_TRIGGER]["parameters"]["rule"]["interval"]
    assert interval == [{"field": "minutes", "minutesInterval": 1}]
    assert successors(connections, PERIODIC_TRIGGER) == {PERIODIC_PARAMETERS}


def test_periodic_consumer_is_queued_only_and_does_not_depend_on_an_incoming_reel_id() -> None:
    nodes, connections = workflow()
    periodic_code = nodes[PERIODIC_PARAMETERS]["parameters"]["jsCode"]
    claim_sql = query(nodes, CLAIM)

    assert "reel_id: null" in periodic_code
    assert "$json.id" not in periodic_code
    assert "$json.reel_id" not in periodic_code
    assert not can_reach(connections, PERIODIC_TRIGGER, QUEUE)
    assert can_reach(connections, PERIODIC_TRIGGER, ENRICHER)
    assert "reel.transcription_status = 'queued'" in claim_sql
    assert "reel.transcription_attempt_id IS NULL" in claim_sql
    assert "reel.download_status = 'downloaded'" in claim_sql


def test_shared_claim_uses_fifo_skip_locked_and_validates_durable_input() -> None:
    nodes, connections = workflow()
    claim_sql = query(nodes, CLAIM)

    assert successors(connections, ATTEMPT_ID) == {CLAIM}
    assert can_reach(connections, LEGACY_TRIGGER, CLAIM)
    assert can_reach(connections, PERIODIC_TRIGGER, CLAIM)
    assert "MGB030_TRANSCRIPTION_CLAIM_LOCK_KEY = 308030" in claim_sql
    assert "pg_try_advisory_xact_lock(308030::BIGINT)" in claim_sql
    assert "ORDER BY reel.updated_at ASC, reel.id ASC" in claim_sql
    assert "FOR UPDATE SKIP LOCKED" in claim_sql
    assert "LIMIT 1" in claim_sql
    assert "reel.object_key IS NOT NULL" in claim_sql
    assert "reel.object_key <> ''" in claim_sql
    assert "reel.sha256 ~ '^[0-9a-f]{64}$'" in claim_sql
    assert "reel.file_size_bytes > 0" in claim_sql
    assert "FROM app.reel_enrichments AS enrichment" in claim_sql


def test_shared_claim_enforces_global_processing_one_and_creates_attempt_atomically() -> None:
    nodes, connections = workflow()
    claim_sql = query(nodes, CLAIM)

    assert "NOT EXISTS (\n          SELECT 1\n          FROM app.reels AS processing_reel\n          WHERE processing_reel.transcription_status = 'processing'" in claim_sql
    assert "WITH consumer_lock AS MATERIALIZED" in claim_sql
    assert "activated_reel AS" in claim_sql
    assert "created_attempt AS" in claim_sql
    assert "UPDATE app.reels AS reel" in claim_sql
    assert "transcription_status = 'processing'" in claim_sql
    assert "transcription_attempt_id = $1::UUID" in claim_sql
    assert "INSERT INTO app.reel_enrichment_attempts" in claim_sql
    assert "'processing'" in claim_sql
    assert "NOW()" in claim_sql
    assert "UPDATE app.reel_enrichment_attempts" not in claim_sql
    assert successors(connections, CLAIM) == {ENRICHER}


def test_claim_derives_immutable_retry_lineage_from_latest_matching_failed_attempt() -> None:
    nodes, _ = workflow()
    claim_sql = query(nodes, CLAIM)

    assert "FROM app.reel_enrichment_attempts AS previous_attempt" in claim_sql
    assert "previous_attempt.status = 'failed'" in claim_sql
    assert "previous_attempt.reel_id = activated_reel.reel_id" in claim_sql
    assert "previous_attempt.source_object_key = activated_reel.source_object_key" in claim_sql
    assert "previous_attempt.expected_sha256 = activated_reel.expected_sha256" in claim_sql
    assert "previous_attempt.pipeline_version = $2::TEXT" in claim_sql
    assert "ORDER BY previous_attempt.finished_at DESC NULLS LAST" in claim_sql
    assert "retry_of_attempt_id" in claim_sql
    assert "COALESCE" not in claim_sql
    assert "$json.retry_of_attempt_id" not in nodes[CLAIM]["parameters"]["options"]["queryReplacement"]


def test_no_claim_stops_without_enricher_work_and_claimed_work_can_continue() -> None:
    nodes, connections = workflow()
    claim_sql = query(nodes, CLAIM)

    assert "SELECT created_attempt.*" in claim_sql
    assert successors(connections, CLAIM) == {ENRICHER}
    assert not successors(connections, CLAIM, 1)
    assert nodes[ENRICHER]["parameters"]["headerParameters"]["parameters"][1]["value"] == "={{ $json.attempt_id }}"


def test_periodic_state_preserves_claim_contract_fields() -> None:
    nodes, _ = workflow()
    periodic_code = nodes[PERIODIC_PARAMETERS]["parameters"]["jsCode"]
    state = nodes[PERIODIC_STATE]["parameters"]
    state_sql = state["query"]

    assert "pipeline_version:" in periodic_code
    assert "contract_version:" in periodic_code
    assert "language_hint:" in periodic_code
    assert "COALESCE(processing.pipeline_version, $1::TEXT) AS pipeline_version" in state_sql
    assert "COALESCE(processing.contract_version, $2::TEXT) AS contract_version" in state_sql
    assert "COALESCE(processing.language_hint, $3::TEXT) AS language_hint" in state_sql
    assert state["options"]["queryReplacement"] == (
        "={{ [$json.pipeline_version, $json.contract_version, $json.language_hint] }}"
    )
