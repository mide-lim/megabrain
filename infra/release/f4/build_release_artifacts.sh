#!/usr/bin/env bash
# Human-operated F4 image build and offline evidence bundler. It never deploys.
set -euo pipefail
umask 077

usage() {
  printf 'usage: $0 <approved-commit>\n' >&2
  exit 64
}

die() {
  printf 'f4 release build: %s\n' "$*" >&2
  exit 1
}

require_env() {
  local variable_name="$1"
  [[ -n "${!variable_name:-}" ]] || die "required environment variable is empty: ${variable_name}"
}

require_immutable_image_ref() {
  local variable_name="$1"
  local reference="${!variable_name}"
  [[ "$reference" == *@sha256:* ]] || die "${variable_name} must be an image@sha256:<digest> reference"
  [[ "$reference" != *:latest@* ]] || die "${variable_name} must not retain a latest tag"
  [[ "${reference##*@}" =~ ^sha256:[0-9a-f]{64}$ ]] || die "${variable_name} has an invalid digest"
}

[[ "$#" -eq 1 ]] || usage
REQUESTED_COMMIT="$1"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR/../../.." rev-parse --show-toplevel)"

[[ -z "$(git -C "$REPO_ROOT" status --porcelain)" ]] || die "source tree is dirty; refuse to build from uncommitted source"
APPROVED_COMMIT="$(git -C "$REPO_ROOT" rev-parse --verify "${REQUESTED_COMMIT}^{commit}")"
CURRENT_COMMIT="$(git -C "$REPO_ROOT" rev-parse HEAD)"
[[ "$APPROVED_COMMIT" =~ ^[0-9a-f]{40}$ ]] || die "approved commit is not a full commit object"

require_env F4_PYTHON_BASE_REF
require_env F4_NODE_BASE_REF
require_immutable_image_ref F4_PYTHON_BASE_REF
require_immutable_image_ref F4_NODE_BASE_REF

# These values are human-captured runtime compatibility evidence, not credentials.
require_env F4_N8N_CONFIGURED_REFERENCE
require_env F4_N8N_APPLICATION_VERSION
require_env F4_N8N_IMAGE_ID
require_env F4_N8N_REPO_DIGEST
require_env F4_POSTGRES_SERVER_VERSION
require_env F4_POSTGRES_IMAGE_ID
require_env F4_POSTGRES_REPO_DIGEST
[[ "$F4_POSTGRES_SERVER_VERSION" == 16.* ]] || die "F4 supports PostgreSQL 16 only"

SHORT_SHA="${APPROVED_COMMIT:0:12}"
WEB_TAG="megabrain-web:f4-${SHORT_SHA}"
FRONTEND_TAG="megabrain-frontend:f4-${SHORT_SHA}"
RELEASE_ROOT="${F4_RELEASE_ROOT:-/home/megabrain/releases/f4/${APPROVED_COMMIT}}"
BUILD_CONTEXT="$(mktemp -d "${TMPDIR:-/tmp}/megabrain-f4-${SHORT_SHA}.XXXXXX")"
WORKTREE_ADDED=0

cleanup() {
  if [[ "$WORKTREE_ADDED" -eq 1 ]]; then
    git -C "$REPO_ROOT" worktree remove --force "$BUILD_CONTEXT" || true
  else
    rm -rf "$BUILD_CONTEXT"
  fi
}
trap cleanup EXIT

[[ ! -e "$RELEASE_ROOT" ]] || die "release root already exists: $RELEASE_ROOT"
mkdir -p "$RELEASE_ROOT/images" "$RELEASE_ROOT/sql" "$RELEASE_ROOT/workflows"
chmod 0700 "$RELEASE_ROOT"

git -C "$REPO_ROOT" worktree add --detach "$BUILD_CONTEXT" "$APPROVED_COMMIT"
WORKTREE_ADDED=1
[[ "$(git -C "$BUILD_CONTEXT" rev-parse HEAD)" == "$APPROVED_COMMIT" ]] || die "detached build context did not resolve to the approved commit"

# Pull only explicit content-addressed base references supplied by the operator.
docker pull "$F4_PYTHON_BASE_REF"
docker pull "$F4_NODE_BASE_REF"

docker build --pull \
  --build-arg "PYTHON_BASE_IMAGE=$F4_PYTHON_BASE_REF" \
  --build-arg "SOURCE_REVISION=$APPROVED_COMMIT" \
  --build-arg "IMAGE_VERSION=f4-$SHORT_SHA" \
  --label "org.opencontainers.image.revision=$APPROVED_COMMIT" \
  --label "org.opencontainers.image.source=https://github.com/mide-lim/megabrain" \
  --label "org.opencontainers.image.version=f4-$SHORT_SHA" \
  --tag "$WEB_TAG" \
  "$BUILD_CONTEXT/services/web"

docker build --pull \
  --build-arg "NODE_BASE_IMAGE=$F4_NODE_BASE_REF" \
  --build-arg "SOURCE_REVISION=$APPROVED_COMMIT" \
  --build-arg "IMAGE_VERSION=f4-$SHORT_SHA" \
  --label "org.opencontainers.image.revision=$APPROVED_COMMIT" \
  --label "org.opencontainers.image.source=https://github.com/mide-lim/megabrain" \
  --label "org.opencontainers.image.version=f4-$SHORT_SHA" \
  --tag "$FRONTEND_TAG" \
  "$BUILD_CONTEXT/apps/web"

WEB_IMAGE_ID="$(docker image inspect --format '{{.Id}}' "$WEB_TAG")"
FRONTEND_IMAGE_ID="$(docker image inspect --format '{{.Id}}' "$FRONTEND_TAG")"
[[ "$(docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$WEB_TAG")" == "$APPROVED_COMMIT" ]] || die "backend OCI revision label does not bind the approved commit"
[[ "$(docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$FRONTEND_TAG")" == "$APPROVED_COMMIT" ]] || die "frontend OCI revision label does not bind the approved commit"

docker save --output "$RELEASE_ROOT/images/megabrain-web.tar" "$WEB_TAG"
docker save --output "$RELEASE_ROOT/images/megabrain-frontend.tar" "$FRONTEND_TAG"

copy_release_input() {
  local source_path="$1"
  local relative_path="$2"
  [[ -f "$source_path" ]] || die "approved source artifact is missing: $source_path"
  install -m 0600 "$source_path" "$RELEASE_ROOT/$relative_path"
}

copy_release_input "$BUILD_CONTEXT/infra/postgres/migrations/005_f4_reel_lifecycle.sql" "sql/005_f4_reel_lifecycle.sql"
copy_release_input "$BUILD_CONTEXT/infra/postgres/security/f4/001_f4_runtime_roles.sql" "sql/001_f4_runtime_roles.sql"
copy_release_input "$BUILD_CONTEXT/infra/postgres/security/f4/002_f4_runtime_grants.sql" "sql/002_f4_runtime_grants.sql"
copy_release_input "$BUILD_CONTEXT/infra/postgres/security/f4/003_f4_runtime_grants_verify.sql" "sql/003_f4_runtime_grants_verify.sql"
copy_release_input "$BUILD_CONTEXT/infra/postgres/security/f4/004_f4_runtime_grants_rollback.sql" "sql/004_f4_runtime_grants_rollback.sql"
copy_release_input "$BUILD_CONTEXT/workflows/MGB-020-download-reel.json" "workflows/MGB-020-download-reel.json"
copy_release_input "$BUILD_CONTEXT/workflows/MGB-030-enrichment-reel.json" "workflows/MGB-030-enrichment-reel.json"

(
  cd "$RELEASE_ROOT"
  sha256sum \
    images/megabrain-web.tar \
    images/megabrain-frontend.tar \
    sql/005_f4_reel_lifecycle.sql \
    sql/001_f4_runtime_roles.sql \
    sql/002_f4_runtime_grants.sql \
    sql/003_f4_runtime_grants_verify.sql \
    sql/004_f4_runtime_grants_rollback.sql \
    workflows/MGB-020-download-reel.json \
    workflows/MGB-030-enrichment-reel.json > SHA256SUMS
)
chmod 0600 "$RELEASE_ROOT/SHA256SUMS" "$RELEASE_ROOT/images"/*.tar "$RELEASE_ROOT/sql"/*.sql "$RELEASE_ROOT/workflows"/*.json

hash_for() {
  local relative_path="$1"
  awk -v path="$relative_path" '$2 == path { print $1; exit }' "$RELEASE_ROOT/SHA256SUMS"
}

N8N_RECREATE_STATE="ANCHORED"
[[ "$F4_N8N_REPO_DIGEST" != "NOT_AVAILABLE" ]] || N8N_RECREATE_STATE="N8N_REGISTRY_DIGEST_REQUIRED_FOR_RECREATE"
SOURCE_BRANCH="$(git -C "$REPO_ROOT" branch --show-current)"
SOURCE_BRANCH="${SOURCE_BRANCH:-DETACHED}"
DOCKER_ENGINE_VERSION="$(docker version --format '{{.Server.Version}}')"
DOCKER_BUILD_VERSION="$(docker buildx version 2>/dev/null | awk '{print $NF}' || docker version --format '{{.Client.Version}}')"
BUILD_TIMESTAMP_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

cat > "$RELEASE_ROOT/RELEASE_MANIFEST.yml" <<EOF
release:
  name: f4
  source_commit: $APPROVED_COMMIT
  branch: $SOURCE_BRANCH
  build_timestamp_utc: $BUILD_TIMESTAMP_UTC
  build_context: detached-worktree-at-$APPROVED_COMMIT
  docker_engine_version: $DOCKER_ENGINE_VERSION
  docker_build_version: $DOCKER_BUILD_VERSION
backend:
  image_tag: $WEB_TAG
  image_id: $WEB_IMAGE_ID
  image_archive: images/megabrain-web.tar
  archive_sha256: $(hash_for images/megabrain-web.tar)
  dockerfile: services/web/Dockerfile
  python_base_ref: $F4_PYTHON_BASE_REF
  python_base_digest: ${F4_PYTHON_BASE_REF##*@}
  oci_revision: $APPROVED_COMMIT
frontend:
  image_tag: $FRONTEND_TAG
  image_id: $FRONTEND_IMAGE_ID
  image_archive: images/megabrain-frontend.tar
  archive_sha256: $(hash_for images/megabrain-frontend.tar)
  dockerfile: apps/web/Dockerfile
  node_base_ref: $F4_NODE_BASE_REF
  node_base_digest: ${F4_NODE_BASE_REF##*@}
  oci_revision: $APPROVED_COMMIT
n8n:
  compatibility_anchor: N8N_COMPATIBILITY_ANCHOR
  configured_reference: $F4_N8N_CONFIGURED_REFERENCE
  application_version: $F4_N8N_APPLICATION_VERSION
  image_id: $F4_N8N_IMAGE_ID
  repo_digest: $F4_N8N_REPO_DIGEST
  recreate_state: $N8N_RECREATE_STATE
postgres:
  supported_major: 16
  server_version: $F4_POSTGRES_SERVER_VERSION
  image_id: $F4_POSTGRES_IMAGE_ID
  repo_digest: $F4_POSTGRES_REPO_DIGEST
database:
  migration_005_sha256: $(hash_for sql/005_f4_reel_lifecycle.sql)
  runtime_roles_001_sha256: $(hash_for sql/001_f4_runtime_roles.sql)
  grants_002_sha256: $(hash_for sql/002_f4_runtime_grants.sql)
  verifier_003_sha256: $(hash_for sql/003_f4_runtime_grants_verify.sql)
  rollback_004_sha256: $(hash_for sql/004_f4_runtime_grants_rollback.sql)
workflows:
  mgb020_export_sha256: $(hash_for workflows/MGB-020-download-reel.json)
  mgb030_export_sha256: $(hash_for workflows/MGB-030-enrichment-reel.json)
proofs:
  backup_sha256: bb5beb2075305567173486b2a1f58f804cca01a371d6c47930029d4c62c800d2
  f4_d2_verifier_sha256: 021bd3099e0616526d186e1f97479c5239e5d6e7d7c86a81f09d8ac03f6287fb
checksums:
  file: SHA256SUMS
  algorithm: sha256
EOF
chmod 0600 "$RELEASE_ROOT/RELEASE_MANIFEST.yml"
printf 'F4 release bundle created: %s\n' "$RELEASE_ROOT"
printf 'source commit: %s (current checkout was %s)\n' "$APPROVED_COMMIT" "$CURRENT_COMMIT"
