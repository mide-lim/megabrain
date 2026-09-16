#!/usr/bin/env bash
# Human-operated, offline F4 release-bundle verifier. It never deploys or loads images.
set -euo pipefail
umask 077

usage() {
  printf 'usage: $0 <release-root>\n' >&2
  exit 64
}

die() {
  printf 'f4 release verification: %s\n' "$*" >&2
  exit 1
}

[[ "$#" -eq 1 ]] || usage
RELEASE_ROOT="$(cd -- "$1" && pwd)"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR/../../.." rev-parse --show-toplevel)"
MANIFEST="$RELEASE_ROOT/RELEASE_MANIFEST.yml"
CHECKSUMS="$RELEASE_ROOT/SHA256SUMS"

[[ -f "$MANIFEST" ]] || die "missing release manifest"
[[ -f "$CHECKSUMS" ]] || die "missing checksum file"

manifest_value() {
  local section="$1"
  local key="$2"
  awk -v section="${section}:" -v key="${key}:" '
    $0 == section { active = 1; next }
    active && /^[^[:space:]]/ { exit }
    active && $1 == key { print $2; exit }
  ' "$MANIFEST"
}

checksum_value() {
  local relative_path="$1"
  awk -v path="$relative_path" '$2 == path { print $1; exit }' "$CHECKSUMS"
}

require_manifest_value() {
  local section="$1"
  local key="$2"
  local value
  value="$(manifest_value "$section" "$key")"
  [[ -n "$value" ]] || die "manifest is missing ${section}.${key}"
  printf '%s' "$value"
}

require_bundle_file() {
  local relative_path="$1"
  [[ -f "$RELEASE_ROOT/$relative_path" ]] || die "missing expected artifact: $relative_path"
  [[ -n "$(checksum_value "$relative_path")" ]] || die "checksum file omits artifact: $relative_path"
}

SOURCE_COMMIT="$(require_manifest_value release source_commit)"
[[ "$SOURCE_COMMIT" =~ ^[0-9a-f]{40}$ ]] || die "manifest source commit is not a full SHA-1 commit identifier"
git -C "$REPO_ROOT" cat-file -e "${SOURCE_COMMIT}^{commit}"

for required_field in \
  'release branch' \
  'release build_context' \
  'release docker_engine_version' \
  'release docker_build_version' \
  'backend image_tag' \
  'backend image_id' \
  'backend image_archive' \
  'backend archive_sha256' \
  'backend python_base_ref' \
  'backend python_base_digest' \
  'backend oci_revision' \
  'frontend image_tag' \
  'frontend image_id' \
  'frontend image_archive' \
  'frontend archive_sha256' \
  'frontend node_base_ref' \
  'frontend node_base_digest' \
  'frontend oci_revision' \
  'n8n compatibility_anchor' \
  'n8n configured_reference' \
  'n8n application_version' \
  'n8n image_id' \
  'n8n repo_digest' \
  'postgres server_version' \
  'postgres image_id' \
  'postgres repo_digest' \
  'database migration_005_sha256' \
  'database runtime_roles_001_sha256' \
  'database grants_002_sha256' \
  'database verifier_003_sha256' \
  'database rollback_004_sha256' \
  'workflows mgb020_export_sha256' \
  'workflows mgb030_export_sha256' \
  'proofs backup_sha256' \
  'proofs f4_d2_verifier_sha256'; do
  read -r section key <<<"$required_field"
  require_manifest_value "$section" "$key" >/dev/null
done

[[ "$(require_manifest_value backend oci_revision)" == "$SOURCE_COMMIT" ]] || die "backend OCI revision differs from source commit"
[[ "$(require_manifest_value frontend oci_revision)" == "$SOURCE_COMMIT" ]] || die "frontend OCI revision differs from source commit"
[[ "$(require_manifest_value backend python_base_ref)" == *@sha256:* ]] || die "backend base reference is not immutable"
[[ "$(require_manifest_value frontend node_base_ref)" == *@sha256:* ]] || die "frontend base reference is not immutable"
[[ "$(require_manifest_value postgres server_version)" == 16.* ]] || die "manifest does not record a supported PostgreSQL 16 server"

BACKEND_ARCHIVE="$(require_manifest_value backend image_archive)"
FRONTEND_ARCHIVE="$(require_manifest_value frontend image_archive)"
for artifact in \
  "$BACKEND_ARCHIVE" \
  "$FRONTEND_ARCHIVE" \
  sql/005_f4_reel_lifecycle.sql \
  sql/001_f4_runtime_roles.sql \
  sql/002_f4_runtime_grants.sql \
  sql/003_f4_runtime_grants_verify.sql \
  sql/004_f4_runtime_grants_rollback.sql \
  workflows/MGB-020-download-reel.json \
  workflows/MGB-030-enrichment-reel.json; do
  require_bundle_file "$artifact"
done

(
  cd "$RELEASE_ROOT"
  sha256sum -c SHA256SUMS
)

[[ "$(require_manifest_value backend archive_sha256)" == "$(checksum_value "$BACKEND_ARCHIVE")" ]] || die "backend archive SHA-256 disagrees with checksum file"
[[ "$(require_manifest_value frontend archive_sha256)" == "$(checksum_value "$FRONTEND_ARCHIVE")" ]] || die "frontend archive SHA-256 disagrees with checksum file"
[[ "$(require_manifest_value database migration_005_sha256)" == "$(checksum_value sql/005_f4_reel_lifecycle.sql)" ]] || die "migration checksum disagrees with checksum file"
[[ "$(require_manifest_value database runtime_roles_001_sha256)" == "$(checksum_value sql/001_f4_runtime_roles.sql)" ]] || die "runtime-role checksum disagrees with checksum file"
[[ "$(require_manifest_value database grants_002_sha256)" == "$(checksum_value sql/002_f4_runtime_grants.sql)" ]] || die "grants checksum disagrees with checksum file"
[[ "$(require_manifest_value database verifier_003_sha256)" == "$(checksum_value sql/003_f4_runtime_grants_verify.sql)" ]] || die "verifier checksum disagrees with checksum file"
[[ "$(require_manifest_value database rollback_004_sha256)" == "$(checksum_value sql/004_f4_runtime_grants_rollback.sql)" ]] || die "rollback checksum disagrees with checksum file"
[[ "$(require_manifest_value workflows mgb020_export_sha256)" == "$(checksum_value workflows/MGB-020-download-reel.json)" ]] || die "MGB-020 checksum disagrees with checksum file"
[[ "$(require_manifest_value workflows mgb030_export_sha256)" == "$(checksum_value workflows/MGB-030-enrichment-reel.json)" ]] || die "MGB-030 checksum disagrees with checksum file"

if [[ "${F4_VERIFY_WITH_DOCKER:-0}" == 1 ]]; then
  backend_tag="$(require_manifest_value backend image_tag)"
  frontend_tag="$(require_manifest_value frontend image_tag)"
  [[ "$(docker image inspect --format '{{.Id}}' "$backend_tag")" == "$(require_manifest_value backend image_id)" ]] || die "loaded backend image ID differs from manifest"
  [[ "$(docker image inspect --format '{{.Id}}' "$frontend_tag")" == "$(require_manifest_value frontend image_id)" ]] || die "loaded frontend image ID differs from manifest"
  [[ "$(docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$backend_tag")" == "$SOURCE_COMMIT" ]] || die "loaded backend OCI revision differs from manifest source commit"
  [[ "$(docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$frontend_tag")" == "$SOURCE_COMMIT" ]] || die "loaded frontend OCI revision differs from manifest source commit"
fi

printf 'F4 release bundle verified offline: %s\n' "$RELEASE_ROOT"
