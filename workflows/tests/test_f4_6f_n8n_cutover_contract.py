from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CUTOVER = ROOT / "docs" / "F4_N8N_CUTOVER.md"
READINESS = ROOT / "docs" / "F4_6_RELEASE_READINESS.md"
MGB020 = ROOT / "workflows" / "MGB-020-download-reel.json"
MGB030 = ROOT / "workflows" / "MGB-030-enrichment-reel.json"
GRANTS = ROOT / "infra" / "postgres" / "security" / "f4" / "002_f4_runtime_grants.sql"

MGB020_SHA256 = "1534ec7412447f0285223de54c8ff19e9b542d17e7e2e92b603a2771adc236ac"
MGB030_SHA256 = "f6b5974643926a42f1033560abb0293fb239fd7330c65a9d4a54d177c58e4695"


def text(path: Path) -> str:
    assert path.is_file(), f"missing required F4.6F artifact: {path}"
    return path.read_text(encoding="utf-8")


def test_cutover_document_pins_sanitized_workflow_artifacts_and_limitations() -> None:
    document = text(CUTOVER)

    assert hashlib.sha256(MGB020.read_bytes()).hexdigest() == MGB020_SHA256
    assert hashlib.sha256(MGB030.read_bytes()).hexdigest() == MGB030_SHA256
    for required in (
        "workflows/MGB-020-download-reel.json",
        "workflows/MGB-030-enrichment-reel.json",
        MGB020_SHA256,
        MGB030_SHA256,
        "credential IDs",
        "credential secrets",
        "private URLs",
        "production workflow IDs",
        "webhook runtime IDs",
        "activation state",
        "Matching JSON SHA proves reviewed logical definition",
    ):
        assert required in document


def test_cutover_contract_requires_dedicated_principals_and_preserves_old_owner_credential() -> None:
    document = text(CUTOVER)

    for required in (
        "MegaBrain F4 MGB-020",
        "megabrain_mgb020",
        "MegaBrain F4 MGB-030",
        "megabrain_mgb030",
        "LOGIN",
        "NOSUPERUSER",
        "NOCREATEDB",
        "NOCREATEROLE",
        "NOREPLICATION",
        "NOBYPASSRLS",
        "NOINHERIT",
        "MegaBrain → megabrain",
        "must NOT be deleted",
        "OWNER_ROLE_USED_BY_F4_RUNTIME=NO",
    ):
        assert required in document


def test_quiesce_order_closes_the_trigger_race_before_inflight_zero() -> None:
    document = text(CUTOVER)

    entry_close = document.index("Close every F4 entry point and dispatch source")
    entry_proof = document.index("Prove new entry is impossible")
    drain = document.index("Drain/account for every existing execution")
    inflight = document.index("Confirm INFLIGHT_ZERO only after")
    migrate = document.index("Run migration 005 exactly once")
    assert entry_close < entry_proof < drain < inflight < migrate
    assert "One zero-count query before entry closure is insufficient" in document
    assert "HUMAN_N8N_EXECUTION_STATE_PROOF_REQUIRED" in document


def test_cutover_contract_is_fail_closed_and_forbids_rebuild_or_broad_stack_operations() -> None:
    document = text(CUTOVER)

    for required in (
        "wrong workflow hash → STOP",
        "wrong runtime n8n image/version → STOP",
        "in-flight execution exists → STOP",
        "migration preflight mismatch → STOP",
        "role verifier FAIL → STOP",
        "workflow still bound to owner credential → STOP",
        "OCI image revision mismatch → STOP",
        "No build during cutover.",
        "No broad docker compose up.",
        "No n8n pull/recreate.",
        "No PostgreSQL pull/recreate.",
        "Post-migration, pre-write",
        "Post-F4 write",
    ):
        assert required in document


def test_workflow_sql_operations_fit_the_dedicated_grant_contract_without_owner_authority() -> None:
    document = text(CUTOVER)
    grants = text(GRANTS)
    mgb020 = json.loads(MGB020.read_text(encoding="utf-8"))
    mgb030 = json.loads(MGB030.read_text(encoding="utf-8"))
    mgb020_sql = "\n".join(
        node.get("parameters", {}).get("query", "") for node in mgb020["nodes"]
    )
    mgb030_sql = "\n".join(
        node.get("parameters", {}).get("query", "") for node in mgb030["nodes"]
    )

    assert "UPDATE app.reels" in mgb020_sql
    assert "INSERT INTO app.reel_enrichment_attempts" in mgb030_sql
    assert "INSERT INTO app.reel_enrichments" in mgb030_sql
    for workflow in (mgb020, mgb030):
        postgres_nodes = [
            node for node in workflow["nodes"] if node["type"] == "n8n-nodes-base.postgres"
        ]
        assert postgres_nodes
        for node in postgres_nodes:
            binding = node["credentials"]["postgres"]
            assert binding["id"] == "__CREDENTIAL_ID_POSTGRES__"
            assert binding["name"] == "__CREDENTIAL_NAME_POSTGRES__"
            assert "megabrain" not in json.dumps(binding).lower()
    assert "GRANT UPDATE (" in grants
    assert "TO megabrain_mgb020" in grants
    assert "TO megabrain_mgb030" in grants
    for required in (
        "MGB-020 static SQL review: PASS",
        "MGB-030 static SQL review: PASS",
        "No workflow operation requires owner authority.",
        "MGB-020 → MGB-030: execute-workflow reference by workflow ID placeholder",
        "MGB-001",
        "MGB-010",
        "MGB-015",
    ):
        assert required in document


def test_readiness_references_the_f4_6f_human_cutover_runbook_without_marking_f4_ready() -> None:
    readiness = text(READINESS)

    assert "F4_N8N_CUTOVER.md" in readiness
    assert "F4_6_RELEASE_READINESS_BLOCKED" in readiness
    assert "F4_6F_N8N_CUTOVER_PREPARATION_READY" in readiness
