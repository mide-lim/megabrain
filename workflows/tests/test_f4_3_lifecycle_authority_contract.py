from __future__ import annotations

import json
from collections import deque
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MGB020_PATH = ROOT / "workflows" / "MGB-020-download-reel.json"
MGB030_PATH = ROOT / "workflows" / "MGB-030-enrichment-reel.json"


def workflow_nodes(path: Path) -> tuple[dict[str, dict], dict]:
    workflow = json.loads(path.read_text(encoding="utf-8"))
    return {node["name"]: node for node in workflow["nodes"]}, workflow["connections"]


def successors(connections: dict, name: str, output: int | None = None) -> set[str]:
    outputs = connections.get(name, {}).get("main", [])
    selected = outputs if output is None else outputs[output : output + 1]
    return {edge["node"] for branch in selected for edge in branch}


def can_reach(connections: dict, source: str, target: str) -> bool:
    queue = deque(successors(connections, source))
    seen: set[str] = set()
    while queue:
        current = queue.popleft()
        if current == target:
            return True
        if current not in seen:
            seen.add(current)
            queue.extend(successors(connections, current))
    return False


def query(nodes: dict[str, dict], name: str) -> str:
    return nodes[name]["parameters"]["query"]


def test_mgb020_is_the_only_download_writer_with_guarded_final_vocabulary() -> None:
    nodes, _ = workflow_nodes(MGB020_PATH)
    claim = query(nodes, "DB — Reivindicar processamento")
    completed = query(nodes, "DB — Marcar downloaded")
    failed = query(nodes, "DB — Registrar falha")

    assert "download_status IN ('received', 'failed')" in claim
    assert "download_status = 'downloading'" in claim
    assert "download_status = 'downloaded'" in completed
    assert "AND download_status = 'downloading'" in completed
    assert "download_status = 'failed'" in failed
    assert "AND download_status = 'downloading'" in failed
    assert "download_failed" not in "\n".join((claim, completed, failed))
    assert "transcription_status" not in "\n".join((claim, completed, failed))


def test_mgb030_dispatch_marks_queued_before_a_current_attempt_becomes_processing() -> None:
    nodes, connections = workflow_nodes(MGB030_PATH)
    queued = query(nodes, "DB — Enfileirar transcrição")
    processing = query(nodes, "DB — Criar tentativa processing")

    assert "UPDATE app.reels" in queued
    assert "transcription_status = 'queued'" in queued
    assert "transcription_status IN ('not_requested', 'failed')" in queued
    assert "NOT EXISTS" in queued
    assert successors(connections, "DB — Localizar Reel elegível") == {"IF — Precisa enriquecer?"}
    assert successors(connections, "IF — Precisa enriquecer?", 0) == {"DB — Enfileirar transcrição"}
    assert successors(connections, "DB — Enfileirar transcrição") == {"DATA — Criar attempt_id"}
    assert can_reach(connections, "DB — Enfileirar transcrição", "HTTP — Enricher /v1/enrichments")

    assert "UPDATE app.reels" in processing
    assert "transcription_status = 'processing'" in processing
    assert "transcription_attempt_id = $1::UUID" in processing
    assert "AND transcription_status = 'queued'" in processing
    assert "INSERT INTO app.reel_enrichment_attempts" in processing


def test_mgb030_success_projects_all_accepted_outcomes_to_completed_only_for_current_attempt() -> None:
    nodes, _ = workflow_nodes(MGB030_PATH)
    completed = query(nodes, "DB — Persistir resultado e concluir tentativa")

    assert "UPDATE app.reel_enrichment_attempts" in completed
    assert "status = 'completed'" in completed
    assert "INSERT INTO app.reel_enrichments" in completed
    assert "UPDATE app.reels" in completed
    assert "transcription_status = 'completed'" in completed
    assert "transcription_attempt_id = NULL" in completed
    assert "AND transcription_status = 'processing'" in completed
    assert "AND transcription_attempt_id = $1::UUID" in completed
    validator = nodes["DATA — Validar resposta Enricher"]["parameters"]["jsCode"]
    for outcome in ("transcribed", "no_audio", "empty_transcript"):
        assert f"outcome === '{outcome}'" in validator


def test_mgb030_failure_is_idempotent_and_cannot_regress_a_newer_attempt() -> None:
    nodes, _ = workflow_nodes(MGB030_PATH)
    failed = query(nodes, "DB — Registrar falha da tentativa")

    assert "UPDATE app.reel_enrichment_attempts" in failed
    assert "status = 'failed'" in failed
    assert "WHERE attempt_id = $1::UUID" in failed
    assert "AND status = 'processing'" in failed
    assert "UPDATE app.reels" in failed
    assert "transcription_status = 'failed'" in failed
    assert "transcription_attempt_id = NULL" in failed
    assert "AND reel.transcription_status = 'processing'" in failed
    assert "AND reel.transcription_attempt_id = failed_attempt.attempt_id" in failed


def test_mgb030_is_the_only_transcription_lifecycle_writer_and_never_mutates_curation() -> None:
    mgb020_nodes, _ = workflow_nodes(MGB020_PATH)
    mgb030_nodes, _ = workflow_nodes(MGB030_PATH)
    mgb020_sql = "\n".join(
        node.get("parameters", {}).get("query", "") for node in mgb020_nodes.values()
    )
    mgb030_sql = "\n".join(
        node.get("parameters", {}).get("query", "") for node in mgb030_nodes.values()
    )

    assert "transcription_status" not in mgb020_sql
    assert "UPDATE app.reels" in mgb030_sql
    assert "curation_status" not in mgb020_sql
    assert "curation_status" not in mgb030_sql
