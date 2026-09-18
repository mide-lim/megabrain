# F4 Immutable Release Artifacts

## Purpose and authority boundary

This repository contract prepares an F4 release bundle. It does not authorize a deployment, database action, runtime service change, workflow import, workflow activation, credential change, or production connection.

The human operator builds only from an exact approved Git commit. The release bundle is retained at:

    /home/megabrain/releases/f4/<full-commit>/

The build script creates this directory with mode `0700`; image archives, manifest, checksums, SQL, and workflow copies are mode `0600`.

## F4 runtime-surface classification

- `services/web` — BUILD ARTIFACT: backend Web image only.
- `apps/web` — BUILD ARTIFACT: frontend image only.
- `MGB-020` — VERSIONED CONFIGURATION ARTIFACT: reviewed sanitized export, not a deploy-ready runtime backup.
- `MGB-030` — VERSIONED CONFIGURATION ARTIFACT: reviewed sanitized export, not a deploy-ready runtime backup.
- `migration 005` — VERSIONED CONFIGURATION ARTIFACT.
- `runtime-role SQL 001–004` — VERSIONED CONFIGURATION ARTIFACT.
- `n8n runtime` — EXISTING RUNTIME COMPATIBILITY ANCHOR.
- `PostgreSQL runtime` — EXISTING RUNTIME COMPATIBILITY ANCHOR.
- `Caddy` — UNCHANGED_RUNTIME_ANCHOR.
- `downloader` — UNCHANGED_RUNTIME_ANCHOR.
- `enricher` — UNCHANGED_RUNTIME_ANCHOR.
- Runtime database credentials, n8n credential bindings, private URLs, and deployment-specific environment values — HUMAN-ONLY SECRET/CONFIGURATION. They are neither copied into the bundle nor read by the release scripts.

No F4 source/configuration change requires Caddy, downloader, or enricher to be built. Their compatibility evidence may be captured by a later human operator, but they are not F4 release outputs.

## Source trust anchor

Run `infra/release/f4/build_release_artifacts.sh <approved-commit>` only from a clean repository checkout. The script rejects a dirty checkout, resolves the argument as a commit object, and creates a detached worktree at that exact full commit. It builds only from that worktree. The current branch is informational and cannot substitute for the commit identity.

The script refuses mutable base-image tags. The operator must provide these explicit, content-addressed values:

    F4_PYTHON_BASE_REF=python@sha256:<resolved-digest>
    F4_NODE_BASE_REF=node@sha256:<resolved-digest>

The actual repository/image names must match the operator's resolved references. The script records both the supplied immutable reference and digest in the manifest. No base digest is invented or resolved by this repository preparation. Until the human captures them, the state is `HUMAN_BASE_DIGEST_PROOF_REQUIRED`.

Backend retains the `python:3.12-slim` contract. Frontend retains the `node:26.7.0-alpine` family and uses the same supplied Node base reference in its dependencies, builder, and runtime stages.

## What is immutable and what is not

A release tag such as `megabrain-web:f4-1ba649f3dabf` is a readable local alias, not the authoritative identity. The release manifest records:

- full source commit;
- tag;
- Docker image ID;
- `docker save` archive path and SHA-256;
- Docker engine/build version and build timestamp;
- exact detached build context and Dockerfile;
- OCI revision label.

The image ID and archive SHA-256 are the release identifiers. A RepoDigest identifies a registry-published image when one exists; no external registry is required for this release contract. The project must not claim equal rebuilds from source unless a separate proof establishes that result.

Both Web and frontend images receive `org.opencontainers.image.revision` equal to the full approved Git commit, plus source and version labels. The build script inspects the final images and fails if the revision label differs.

## Dependency inputs

- `apps/web`: `package-lock.json` is authoritative and the Dockerfile uses `npm ci`; status: `FULLY_PINNED` for npm package resolution.
- `services/web`: `requirements.txt` uses exact `==` version pins; status: `FULLY_PINNED` for listed Python packages.

These locks do not make base images immutable. They also do not establish bit-for-bit rebuild reproducibility: package indexes, installers, timestamps, architecture, and build tooling can still affect a fresh build. An artifact archive whose SHA-256 has been recorded remains immutable evidence of the image actually built.

## Bundle contents and offline verification

The generated bundle contains:

- `RELEASE_MANIFEST.yml`;
- `SHA256SUMS`;
- `images/megabrain-web.tar`;
- `images/megabrain-frontend.tar`;
- exact-commit copies of migration 005 and runtime-role SQL 001–004;
- exact-commit reviewed sanitized MGB-020 and MGB-030 workflow exports.

Run `infra/release/f4/verify_release_artifacts.sh <release-root>` to verify the bundle offline. It checks that the manifest source commit exists locally, verifies all bundle SHA-256 entries, and cross-checks the manifest hashes for both image archives, all SQL inputs, and both workflows. It does not load an image, connect to a database, call n8n, or perform a deployment.

If the operator has already loaded the two verified images, set `F4_VERIFY_WITH_DOCKER=1` for additional read-only local image inspection. This checks the manifest image IDs and OCI revision labels; it does not pull, load, build, or run images.

`HASH MATCH` for a sanitized workflow proves reviewed logical workflow content only. It does not prove production credential bindings. It does not prove workflow IDs, webhook IDs, private URLs, or activation state. Those are later F4.6F evidence.

## SQL and prior evidence

Hashes are calculated from files copied from the detached worktree, never an operator-edited copy:

- `005_f4_reel_lifecycle.sql`;
- `001_f4_runtime_roles.sql`;
- `002_f4_runtime_grants.sql`;
- `003_f4_runtime_grants_verify.sql`;
- `004_f4_runtime_grants_rollback.sql`.

The manifest includes the approved pre-F4 backup SHA-256 `bb5beb2075305567173486b2a1f58f804cca01a371d6c47930029d4c62c800d2` and the external F4.6D2 verifier evidence SHA-256 `021bd3099e0616526d186e1f97479c5239e5d6e7d7c86a81f09d8ac03f6287fb`. The environment-specific D2 evidence remains outside Git at the human-owned evidence location.

## Runtime compatibility anchors

n8n is a compatibility anchor, not an F4 build output. The current Compose source reference is `docker.n8n.io/n8nio/n8n:latest`, so a mutable reference is detected. The release build therefore requires the human to supply captured running-service evidence for configured image reference, exact n8n application version, image ID, and RepoDigest (or `NOT_AVAILABLE`). It records `N8N_COMPATIBILITY_ANCHOR` in the manifest. If no RepoDigest exists, it records `N8N_REGISTRY_DIGEST_REQUIRED_FOR_RECREATE`; F4 must not recreate that runtime until a later human gate resolves the registry identity.

PostgreSQL is also a compatibility anchor. F4 supports PostgreSQL 16; migration 005 has human-proven disposable integration evidence on PostgreSQL 16.14. The human must capture exact running server version, image ID, and RepoDigest (or `NOT_AVAILABLE`). No PostgreSQL upgrade or recreation is authorized.

Caddy, downloader, and enricher are `UNCHANGED_RUNTIME_ANCHOR` surfaces. F4 source changes do not require their rebuild. Their image IDs may be captured as environment evidence later, but they are not F4 build outputs.

## Build-once, deploy-without-rebuild

The later human rollout consumes only the verified Web/frontend archives or images derived from them:

    build once
    -> checksum and retain archive
    -> offline verify
    -> load only if necessary
    -> verify image ID and OCI revision
    -> deploy exact verified Web/frontend identity

Production cutover must not rebuild source. Any later targeted service switch must use `--no-build` (or an equivalent proven no-rebuild control), target only Web and frontend, and bind the verified manifest image tags after image-ID verification. Do not use a broad whole-stack command. In particular, do not pull or recreate n8n because the existing Compose reference is mutable. Do not use a generic stack update that can resolve that reference.

No F4 Compose override is included: merge behavior could retain unrelated build/runtime definitions and make an exact targeted switch ambiguous. The later deployment gate must document and prove its narrow Web/frontend-only command before running it. It must not recreate PostgreSQL, n8n, Caddy, downloader, or enricher.

## Rollback identity and retention

Retain the bundle directory and its checksums for the release lifetime under human ownership. A rollback must identify the previous verified Web/frontend image IDs and archive SHA-256 values; it must not rebuild a branch or use a floating tag. Database/workflow rollback remains separately human-gated and is not implied by retaining an image artifact.

## Human proof still required

`HUMAN_BUILD_PROOF_REQUIRED` remains until the operator builds the archive bundle and verifies its output. Required human evidence includes immutable base digests, final image IDs/archive SHA-256 values, n8n compatibility evidence, and PostgreSQL compatibility evidence. This repository preparation is not an overall F4 release-ready declaration.
