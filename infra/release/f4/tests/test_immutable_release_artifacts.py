from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
RELEASE_DIR = REPO_ROOT / "infra" / "release" / "f4"
BUILD_SCRIPT = RELEASE_DIR / "build_release_artifacts.sh"
VERIFY_SCRIPT = RELEASE_DIR / "verify_release_artifacts.sh"
MANIFEST_TEMPLATE = RELEASE_DIR / "RELEASE_MANIFEST.template"
BACKEND_DOCKERFILE = REPO_ROOT / "services" / "web" / "Dockerfile"
FRONTEND_DOCKERFILE = REPO_ROOT / "apps" / "web" / "Dockerfile"
DOCUMENTATION = REPO_ROOT / "docs" / "F4_IMMUTABLE_RELEASE_ARTIFACTS.md"
READINESS = REPO_ROOT / "docs" / "F4_6_RELEASE_READINESS.md"


APPROVED_SQL = (
    "005_f4_reel_lifecycle.sql",
    "001_f4_runtime_roles.sql",
    "002_f4_runtime_grants.sql",
    "003_f4_runtime_grants_verify.sql",
    "004_f4_runtime_grants_rollback.sql",
)
APPROVED_WORKFLOWS = (
    "MGB-020-download-reel.json",
    "MGB-030-enrichment-reel.json",
)


def text(path: Path) -> str:
    assert path.is_file(), f"missing F4 immutable-release artifact: {path}"
    return path.read_text(encoding="utf-8")


def test_build_script_requires_an_explicit_verified_commit_and_clean_source() -> None:
    script = text(BUILD_SCRIPT)

    assert 'usage: $0 <approved-commit>' in script
    assert '[[ "$#" -eq 1 ]]' in script
    assert 'git -C "$REPO_ROOT" status --porcelain' in script
    assert 'git -C "$REPO_ROOT" rev-parse --verify "${REQUESTED_COMMIT}^{commit}"' in script
    assert 'git -C "$REPO_ROOT" rev-parse HEAD' in script
    assert 'worktree add --detach' in script
    assert 'git -C "$BUILD_CONTEXT" rev-parse HEAD' in script


def test_build_script_requires_immutable_base_references_and_nonmoving_tags() -> None:
    script = text(BUILD_SCRIPT)

    assert 'F4_PYTHON_BASE_REF' in script
    assert 'F4_NODE_BASE_REF' in script
    assert "@sha256:" in script
    assert '[[ "$reference" != *:latest@* ]]' in script
    assert 'megabrain-web:f4-${SHORT_SHA}' in script
    assert 'megabrain-frontend:f4-${SHORT_SHA}' in script
    assert re.search(r"--tag[^\n]*latest", script, re.IGNORECASE) is None
    assert "stable" not in script.lower()
    assert 'docker image inspect --format' in script
    assert 'docker save --output' in script


def test_build_script_is_narrow_and_never_reads_or_mutates_runtime_state() -> None:
    script = text(BUILD_SCRIPT).lower()

    for prohibited in (
        "infra/.env",
        "docker compose",
        "docker-compose",
        "docker restart",
        "docker start",
        "docker stop",
        "docker rm",
        "psql",
        "pg_restore",
        "n8n:latest",
        "workflow import",
        "workflow activate",
    ):
        assert prohibited not in script
    assert "password" not in script
    assert "secret" not in script


def test_build_script_derives_sql_and_workflow_hashes_from_detached_commit_context() -> None:
    script = text(BUILD_SCRIPT)

    for artifact in APPROVED_SQL + APPROVED_WORKFLOWS:
        assert artifact in script
    assert 'copy_release_input "$BUILD_CONTEXT/infra/postgres/migrations/005_f4_reel_lifecycle.sql"' in script
    assert 'copy_release_input "$BUILD_CONTEXT/workflows/MGB-020-download-reel.json"' in script
    assert "sha256sum" in script
    assert "SHA256SUMS" in script


def test_verifier_is_offline_read_only_and_checks_manifest_and_bundle_hashes() -> None:
    script = text(VERIFY_SCRIPT).lower()

    for expected in (
        "sha256sum -c sha256sums",
        "git -c",
        "cat-file -e",
        "source_commit",
        "archive_sha256",
        "mgb020_export_sha256",
        "mgb030_export_sha256",
    ):
        assert expected in script
    for prohibited in (
        "docker compose",
        "docker pull",
        "docker load",
        "docker save",
        "psql",
        "curl",
        "wget",
        "n8n:latest",
        "infra/.env",
    ):
        assert prohibited not in script
    assert "f4_verify_with_docker" in script
    assert "docker image inspect" in script


def test_manifest_template_contains_required_trust_and_compatibility_fields() -> None:
    manifest = text(MANIFEST_TEMPLATE)

    for required_field in (
        "source_commit:",
        "branch:",
        "image_tag:",
        "image_id:",
        "image_archive:",
        "archive_sha256:",
        "python_base_ref:",
        "python_base_digest:",
        "node_base_ref:",
        "node_base_digest:",
        "configured_reference:",
        "application_version:",
        "server_version:",
        "migration_005_sha256:",
        "runtime_roles_001_sha256:",
        "grants_002_sha256:",
        "verifier_003_sha256:",
        "rollback_004_sha256:",
        "mgb020_export_sha256:",
        "mgb030_export_sha256:",
        "backup_sha256:",
        "f4_d2_verifier_sha256:",
        "N8N_COMPATIBILITY_ANCHOR",
    ):
        assert required_field in manifest


def test_dockerfiles_accept_pinned_base_overrides_and_bind_oci_revision() -> None:
    backend = text(BACKEND_DOCKERFILE)
    frontend = text(FRONTEND_DOCKERFILE)

    assert "ARG PYTHON_BASE_IMAGE=python:3.12-slim" in backend
    assert "FROM ${PYTHON_BASE_IMAGE}" in backend
    assert "org.opencontainers.image.revision" in backend
    assert "ARG NODE_BASE_IMAGE=node:26.7.0-alpine" in frontend
    assert frontend.count("FROM ${NODE_BASE_IMAGE}") == 3
    assert "org.opencontainers.image.revision" in frontend


def test_release_documentation_classifies_every_f4_runtime_surface() -> None:
    documentation = text(DOCUMENTATION)

    for required_text in (
        "`services/web` — BUILD ARTIFACT",
        "`apps/web` — BUILD ARTIFACT",
        "`MGB-020` — VERSIONED CONFIGURATION ARTIFACT",
        "`MGB-030` — VERSIONED CONFIGURATION ARTIFACT",
        "`migration 005` — VERSIONED CONFIGURATION ARTIFACT",
        "`runtime-role SQL 001–004` — VERSIONED CONFIGURATION ARTIFACT",
        "`n8n runtime` — EXISTING RUNTIME COMPATIBILITY ANCHOR",
        "`PostgreSQL runtime` — EXISTING RUNTIME COMPATIBILITY ANCHOR",
        "`Caddy` — UNCHANGED_RUNTIME_ANCHOR",
        "`downloader` — UNCHANGED_RUNTIME_ANCHOR",
        "`enricher` — UNCHANGED_RUNTIME_ANCHOR",
        "HUMAN-ONLY SECRET/CONFIGURATION",
    ):
        assert required_text in documentation


def test_release_documentation_preserves_no_rebuild_and_n8n_latest_boundaries() -> None:
    documentation = text(DOCUMENTATION)
    readiness = text(READINESS)

    for required_text in (
        "build once",
        "--no-build",
        "N8N_REGISTRY_DIGEST_REQUIRED_FOR_RECREATE",
        "HUMAN_BASE_DIGEST_PROOF_REQUIRED",
        "HUMAN_BUILD_PROOF_REQUIRED",
        "not prove production credential bindings",
        "not prove workflow IDs",
    ):
        assert required_text in documentation
    assert "F4_6E_IMMUTABLE_ARTIFACT_PREPARATION_READY" in readiness
    assert "human build evidence is still required" in readiness


def test_no_release_script_contains_broad_stack_deployment_or_mutable_n8n_reference() -> None:
    for script_path in (BUILD_SCRIPT, VERIFY_SCRIPT):
        script = text(script_path)
        assert re.search(r"docker\s+compose\s+(?:up|pull|down)", script, re.IGNORECASE) is None
        assert "n8n:latest" not in script.lower()
