# F4.6 — Reel Lifecycle Release Readiness

## Verdict and authority boundary

**Verdict: `F4_6_RELEASE_READINESS_BLOCKED`.** The repository implementation and local validation pass, but production rollout must not be authorized until the human prerequisites in this document are satisfied.

This validation performed no production mutation. It did not execute migration 005, deploy or build production images, activate workflows, restart containers, change PostgreSQL, change n8n, or grant authority. A future rollout requires a distinct human gate; this document does not use or imply that gate.

The F4 release scope is limited to:

- `status` renamed to `download_status` with explicit legacy mapping;
- independent `curation_status`, `transcription_status`, and current transcription-attempt projection;
- MGB-020 download authority and MGB-030 transcription authority;
- owner-authenticated, CSRF-protected curation;
- lifecycle API projections and lifecycle UI.

No new product scope is approved by this release plan.

## F4.6D1A migration legacy-compatibility remediation

**Blocker:** the unapplied migration 005 assumed that
`app.reels.reels_status_check` existed. The human-controlled PostgreSQL 16
restore of approved pre-F4 backup
`megabrain-pre-f4-20260916-180216.dump` (SHA-256
`bb5beb2075305567173486b2a1f58f804cca01a371d6c47930029d4c62c800d2`)
instead failed with `app.reels.reels_status_check is required for F4.2 lifecycle
migration`.

**Reality:** the restored production legacy schema has `app.reels.status`, none
of the four F4 lifecycle target columns, and no constraint with that assumed
name. Repository discovery contains no tracked baseline `app.reels` DDL that
proves a lifecycle CHECK under another name. The old static fixture encoded the
assumed named constraint, so it only proved agreement with the migration's
incorrect model and never modeled the restored production-like shape.

**Remediation:** migration 005 accepts only the exact relevant legacy shape:
`status` present and `download_status`, `curation_status`,
`transcription_status`, and `transcription_attempt_id` all absent. It does not
require or drop a named legacy lifecycle constraint. Before any DDL it rejects
null and unknown legacy values using aggregate-only preflights for the approved
`received`, `downloading`, `downloaded`, and `download_failed` vocabulary. It
rejects mixed, partial, and replayed F4 shapes; it records and verifies the
aggregate Reel count; and it retains the F4.3 current-attempt invariant and
deterministic target CHECK constraints.

The companion role-structure artifact now creates restrictive `NOLOGIN` roles
without interactive password prompts, so the disposable proof can run it through
noninteractive psql and use superuser `SET ROLE`. Production authentication
remains a later human-only credential-provisioning step that enables `LOGIN` and
sets each secret outside Git.

## Trust and repository baseline

| Item | Evidence |
| --- | --- |
| Branch | `agent/f4-2-reel-lifecycle-domain` |
| Starting HEAD | `286ecbb2a3a40b8462810bfd1c496ae0075ac0f9` |
| Starting working tree | clean |
| F4 chain | `8664b59` → `66656c2` → `bcc0ce4` → `286ecbb` |
| Final repository change | this release-readiness document only |

## Current live preflight evidence

The approved, read-only A1 gateway was invoked only through its three fixed capabilities during this validation.

| Capability | Result |
| --- | --- |
| `runtime-status` | exit 0; postgres, n8n, caddy, downloader, enricher, web, and frontend are all `running`; postgres, downloader, enricher, web, and frontend are `healthy` |
| `postgres-health` | exit 0; `postgres=ready` |
| `prod-schema-discovery` | exit 0; `transaction_read_only=on`; `rollback=complete`; legacy `app.reels.status` exists; `unexpected_status_values=false` |

Current aggregate legacy lifecycle counts, captured without inspecting individual Reels:

| Legacy status | Count |
| --- | ---: |
| `received` | 3 |
| `downloading` | 0 |
| `downloaded` | 8 |
| `download_failed` | 0 |
| **Total Reels** | **11** |

The same bounded read also confirmed the prerequisite `app.reel_enrichment_attempts` relation. Current attempt/outcome aggregates are not used to infer any migrated Reel transcription state.

## Migration 005 static review

Artifact: `infra/postgres/migrations/005_f4_reel_lifecycle.sql`.

| Required property | Static result |
| --- | --- |
| Transactional execution | `BEGIN` through `COMMIT`; any preflight/postcondition failure aborts the transaction |
| Expected preflight shape | requires `app.reels`, `app.reel_enrichment_attempts`, legacy `status`, and exactly zero F4 lifecycle target columns; no named legacy constraint dependency |
| Unknown-state handling | null or any status outside the four approved legacy values raises a distinct exception; no coercion/defaulting |
| Exact mapping | `received→received`, `downloading→downloading`, `downloaded→downloaded`, `download_failed→failed` |
| Rename | `status` is renamed to `download_status`; no permanent compatibility column or dual write exists |
| Curation initialization | all existing rows obtain `curation_status='inbox'`; categories are not consulted |
| Transcription initialization | all existing rows obtain `transcription_status='not_requested'`; enrichment history is not consulted |
| Attempt invariant | `processing` requires non-null `transcription_attempt_id`; every other state requires null; deferred composite FK binds `(attempt_id, reel_id)` to the same Reel |
| Constraints | CHECK constraints enumerate exactly the approved download, curation, and transcription vocabularies |
| Postconditions | legacy `status` absence, all four target columns, aggregate row-count preservation, resulting values, and all five lifecycle constraints are verified before commit |
| Row preservation/destruction | the migration records the pre-DDL aggregate Reel count, verifies it before commit, and has no `DELETE`, truncation, or Reel-removal statement; it updates only the legacy failed spelling |

The migration is intentionally not replay-safe after its new columns exist. This is correct for a one-time forward migration but requires the operator to record application of migration 005 exactly once.

## Compatibility matrix and deployment consequence

`005` deliberately has no compatibility alias or bridge. Therefore all rows in the following table refer to the whole dependent runtime set, not merely process availability.

| Database / runtime combination | Classification | Reason |
| --- | --- | --- |
| Old DB + old MGB-020/MGB-030/web/frontend | SAFE | legacy `status` contract is intact |
| Old DB + new MGB-020/MGB-030/web | UNSAFE | new runtime requires `download_status` and new lifecycle columns |
| Old DB + new frontend | READ-ONLY SAFE FAILURE | runtime validators reject missing lifecycle fields and show unavailable state; it is not a usable release state |
| New DB + old MGB-020/MGB-030/web | UNSAFE | old queries and writes use removed `status` and old `download_failed` vocabulary |
| New DB + old frontend | UNSAFE | old detail client requires removed generic `status` |
| New DB + new MGB-020/MGB-030/web/frontend | SAFE, subject to permissions and human gates below | all artifacts use the final explicit lifecycle contract |

MGB-001 and MGB-010 remain source adapters and must be paused with their downstream dispatch path during the cutover. They do not make old/new lifecycle schemas interoperable.

### Options evaluated

- **Option A — migration → workflows/backend → frontend:** selected only as a **quiesced cutover**, never a rolling deployment. Between migration and matching runtime release, old readers/writers are incompatible.
- **Option B — services/workflows → migration → frontend:** rejected. New MGB-020, MGB-030, and backend require columns absent from the old database.
- **Option C — temporary compatibility bridge → migration → cleanup:** no bridge is present or approved. It would be a separate scoped design/change, not F4.6 work.

A compatibility bridge is **not required for the selected maintenance-window cutover**. It is **required if the operator requires continuous mixed-version availability**; no such bridge exists today.

## Selected production rollout order

1. Obtain the explicit rollout gate, verified recovery proof, required privilege proof, and approved post-migration aggregate-validation capability described below.
2. At Checkpoint A, rerun bounded health and capture the pre-migration aggregate table above immediately before the maintenance window.
3. At Checkpoint B, pause Telegram intake/dispatch (MGB-001/MGB-010/MGB-015), MGB-020, MGB-030, and all Web writes; drain or account for in-flight executions and requests. Block dynamic Web reads too because old backend API reads would fail after the rename.
4. At Checkpoint C, apply migration 005 once. Verify its preconditions before execution and its postconditions using the separately approved post-migration aggregate validation capability. Abort on any failure.
5. At Checkpoint D, deploy the matching new backend and import/review/activate matching MGB-020 and MGB-030 only under the rollout gate. Confirm their required database grants before allowing processing.
6. At Checkpoint E, deploy the matching frontend.
7. At Checkpoint F, run the approved smoke plan.
8. At Checkpoint G, resume writers in the order accepted by the operator after passing smoke: registration/intake and dispatch, then MGB-020/MGB-030 processing.
9. At Checkpoint H, capture final lifecycle aggregates and runtime health with the post-migration capability.

This release has no rolling-safe interval. The atomic boundary is the drained writer/read traffic window starting before migration and ending only after the new DB, workflow/backend, and frontend contract is validated.

## Quiesce requirements

| Surface | Requirement |
| --- | --- |
| Reel ingestion / MGB-001 / MGB-010 / MGB-015 | pause and drain: required |
| MGB-020 | pause and drain: required |
| MGB-030 | pause and drain: required |
| Web registration and curation writes | pause: required |
| Web/library/detail reads | take offline or maintenance-route during migration and backend replacement; old readers are incompatible with new DB |
| Static non-Reel traffic | may remain only if it cannot invoke the old Reel API contract |

Do not attempt remediation or pausing during F4.6; this is a rollout instruction for the human operator.

## Workflow release review

The sanitized exports for MGB-001, MGB-010, MGB-020, and MGB-030 parse and support static contract review.

- MGB-020 claims only `received|failed → downloading`; guarded terminal writes require `downloading`; it emits `downloaded|failed`, never `download_failed`, and never writes transcription or curation state.
- MGB-020 invokes MGB-030 only after guarded `downloaded` persistence.
- MGB-030 requires `download_status='downloaded'`; accepted dispatch queues `not_requested|failed`; atomic attempt creation performs `queued→processing` and stores the current UUID.
- MGB-030 accepts `transcribed`, `no_audio`, and `empty_transcript` as guarded `completed` results; guarded current-attempt failure projects `failed`; retry returns through `failed→queued→processing`.
- Current-attempt UUID checks prevent stale callbacks from regressing a later attempt. Neither workflow writes curation state.

The exports are sufficient to review the intended lifecycle behavior, but **not sufficient to reproduce a production import**: they intentionally omit credential values/bindings, runtime IDs, node/workflow/webhook IDs, and private service URLs. The operator must restore private configuration, review the import against the production n8n version/image, and activate it separately. The export currently marks MGB-030 inactive; F4.6 does not activate it.

## Backend and frontend release review

### Backend

Registration accepts strict URL input and initializes only the approved lifecycle projection. Library and detail APIs are owner-protected and return `download_status`, `curation_status`, and `transcription_status`; they have no runtime dependency on legacy `app.reels.status` and no generic `status` API alias.

`PATCH /api/reels/{id}/curation` requires the owner session and existing CSRF path, accepts only `inbox|organized`, and issues a parameterized update of only `curation_status`. Category operations remain independent. Browser request schemas do not permit `download_status` or `transcription_status` writes.

**Blocking privilege proof:** historical least-privilege documentation grants the Web role no `UPDATE` on `app.reels`, while F4 curation needs only a narrow `UPDATE (curation_status)` privilege. The current A1 capability does not expose grants. A human must approve and verify the deployed Web-role grant, plus n8n read/write access required for the final MGB-020/MGB-030 lifecycle queries, before release.

### Frontend

The frontend validates and renders all approved explicit lifecycle values. It does not consume a generic Reel status, mutate download/transcription state, or expose the attempt UUID. Curation sends only `{ "curation_status": "inbox"|"organized" }` after the existing same-origin CSRF bootstrap.

Pending mutations are disabled; responses become authoritative confirmed state; failures preserve confirmed state and expose bounded user feedback. Missing/unknown lifecycle projections fail closed as unavailable rather than being invented.

## Test and build validation

All commands below exited 0 unless explicitly marked otherwise.

| Gate | Command/result |
| --- | --- |
| F4.6D1A migration static fixture | `services/web/.venv/bin/python -m pytest -q infra/postgres/tests/test_f4_reel_lifecycle_migration.py`: 7 passed; includes the no-constraint production-like legacy fixture, null/unknown, mixed/partial/replay, mapping, count-preservation, target-constraint, and F4.3 invariant checks |
| F4.6D1A role-hardening static | `services/web/.venv/bin/python -m pytest -q infra/postgres/tests/test_f4_runtime_role_hardening.py`: 9 passed; verifies noninteractive restrictive `NOLOGIN` structure and unchanged grant/verifier boundaries |
| Lifecycle backend | `pytest services/web/tests/test_reel_lifecycle.py`: 19 passed |
| Workflow contract | `pytest workflows/tests`: 20 passed; 5 workflow JSON exports parsed |
| Downloader regression | `unittest discover services/downloader/tests`: 9 passed |
| Web/backend, auth, ownership, CSRF, categories | `pytest services/web`: 285 passed (3 third-party deprecation warnings) |
| Enricher regression | `pytest services/enricher`: 58 passed (1 third-party deprecation warning) |
| Governance/security | 174 skill/capability governance tests passed |
| Frontend tests | `npm test`: 38 passed |
| Frontend lint | `npm run lint`: passed |
| Frontend typecheck | `npm run typecheck`: passed |
| Frontend build | `npm run build`: passed on Next.js 16.3.4 / Node 26.7.0 |
| Workflow JSON | all 5 versioned workflow JSON exports parsed successfully |

A targeted lifecycle test was initially invoked from the repository root and failed collection because `services/web/app` was not on the import path. It was rerun from `services/web` and passed: 19/19. The complete 285-test Web suite also passed from its correct working directory.

There is no repository-defined non-container backend artifact build. The Web, downloader, and enricher Dockerfiles define production image builds, but privileged Docker/image builds are outside F4.6 authority and were not attempted. **`HUMAN_BUILD_PROOF_REQUIRED`:** the operator must produce image-build evidence in the authorized rollout environment without asking Hermes for Docker authority.

A1 gateway tests are not present in this F4 branch and no F4 change modified their repository integration. The previously approved A1 gateway itself was exercised only through its three allowed live read capabilities above.

## Data preservation and post-migration validation

Immediately before migration, record only bounded aggregates:

- total Reels = 11 at this validation-time capture;
- legacy status counts: `received=3`, `downloading=0`, `downloaded=8`, `download_failed=0`.

Immediately after migration, require a bounded aggregate validator to prove:

- total Reels is unchanged;
- `download_status.received = old.status.received`;
- `download_status.downloading = old.status.downloading`;
- `download_status.downloaded = old.status.downloaded`;
- `download_status.failed = old.status.download_failed`;
- every migrated existing Reel has `curation_status=inbox`;
- every migrated existing Reel has `transcription_status=not_requested` and no current attempt UUID;
- legacy `status` is absent and final constraints/attempt relationship exist.

### A1 post-migration gap

The current `prod-schema-discovery` capability is deliberately legacy-bound: it discovers/counts `app.reels.status` and the approved legacy vocabulary. It can establish pre-migration readiness but cannot prove the required F4 post-migration aggregates.

Do not expand A1 in F4.6. Before rollout, a separately reviewed and human-authorized read-only update/capability is required. It must retain the A1 fixed-target, read-only transaction, rollback, aggregate-only, no-row-content grammar and add only F4 post-migration metadata/counts for `download_status`, `curation_status`, `transcription_status`, `transcription_attempt_id`, final lifecycle constraints, and unchanged Reel total. It must have a fail-closed output validator and no mutation interface.

## Rollback decision tree

1. **Migration has not started:** cancel rollout; no schema rollback is required. This is fully reversible because no production mutation occurred.
2. **Migration transaction has not committed:** abort on preflight/constraint failure. PostgreSQL transaction rollback is the complete recovery path.
3. **Migration committed; no new F4 writer has run:** stop before traffic resumes. A separately reviewed reverse migration may be considered only after confirming no dependent runtime has run. It would map `failed→download_failed`, remove F4 constraints/columns, and rename `download_status→status`. This is conditionally reversible, not an automatic rollback.
4. **New MGB-020/MGB-030 or backend has written F4 lifecycle state:** do not run old runtime against the new schema. Prefer a forward fix. A reverse migration would discard F4 transcription projection state and can no longer be claimed semantically lossless.
5. **An owner has created `organized` curation:** forward fix is mandatory by default. Dropping `curation_status` loses user-created organization state; a schema reversal is not fully reversible without a separately approved preservation/reconciliation plan.

In every post-commit branch: quiesce the new fleet first, account for in-flight processing and current-attempt tokens, and obtain human approval before any recovery mutation.

## Backup and recovery prerequisite

No versioned production backup/restore procedure or verified recoverable-backup evidence was found. `docs/CURRENT_STATE.md` explicitly lists formal backup/restore and update runbooks as outstanding work.

**`HUMAN_BACKUP_PROOF_REQUIRED`: YES.** A sufficiently recent recoverable backup, with a human-verified recovery path appropriate to the target PostgreSQL database, is mandatory before authorizing this schema migration. Do not create a backup under F4.6.

## Production smoke plan (design only)

Execute after the new runtime is released and only under the future rollout gate.

| Smoke | Expected result | Creates/changes production data? |
| --- | --- | --- |
| Existing library | loads existing Reels with final lifecycle projections | no |
| Existing detail | loads an existing Reel without generic status dependency | no |
| New registration | new Reel starts `received / inbox / not_requested` | yes — explicit human approval required |
| Download | MGB-020 progresses `received→downloading→downloaded` | yes — uses approved test Reel/processing data; explicit approval required |
| Transcription | MGB-030 progresses `not_requested→queued→processing→completed|failed` | yes — creates attempts/results; explicit approval required |
| UI lifecycle | UI renders approved system and curation states | no, unless coupled to test registration |
| Curation forward | `inbox→organized` through owner session/CSRF | yes — explicit approval required |
| Curation reverse | `organized→inbox` through owner session/CSRF | yes — explicit approval required |
| Categories | category behavior remains independent of curation/lifecycle | may change categories; explicit approval required |
| Browser boundary | attempts to send download/transcription lifecycle fields are rejected | no, if negative request is used |
| Telegram source | source adapter registers/dispatches correctly | yes — explicit approval required |
| Web source | owner Web registration works | yes — explicit approval required |

## Hard abort conditions

Stop the rollout with no “continue anyway” path if any of the following occurs:

1. Any required runtime service is unhealthy/unavailable, or PostgreSQL is not ready.
2. Pre-migration bounded discovery reports unknown/null legacy status.
3. Migration preflight, mapping, constraint, or postcondition validation fails.
4. The post-migration Reel total or mapping aggregate differs from pre-migration capture.
5. The approved post-migration validation capability, backup proof, Web/n8n privilege proof, or authorized image-build proof is absent.
6. Workflow import/runtime behavior differs from reviewed lifecycle contract.
7. Backend/frontend schema/API compatibility fails, including missing lifecycle fields.
8. Authentication, ownership, CSRF, category isolation, or stale-attempt protection regresses.
9. Any unaccounted in-flight old writer/reader remains during the schema cutover.

## Human checkpoints

- **Checkpoint A:** pre-release health, legacy aggregate capture, verified recoverable backup/recovery proof, post-migration validation capability ready, and DB privilege proof.
- **Checkpoint B:** writers/readers quiesced and in-flight execution accounting complete.
- **Checkpoint C:** migration 005 applied once; post-migration metadata and aggregate invariants pass.
- **Checkpoint D:** matching MGB-020/MGB-030 and backend released; workflow import/activation reviewed by the operator.
- **Checkpoint E:** matching frontend released.
- **Checkpoint F:** approved smoke tests complete.
- **Checkpoint G:** writers resumed only after smoke acceptance.
- **Checkpoint H:** final lifecycle aggregates and runtime health captured and accepted.

## Required future authorization

This document grants no production authority. Once all blockers are resolved, the recommended separate human gate is:

`AUTORIZO_F4_PRODUCTION_ROLLOUT`

Until then, the correct disposition is `HUMAN_REMEDIATION_REQUIRED`.

## F4.6E immutable build-artifact preparation

**Repository verdict: `F4_6E_IMMUTABLE_ARTIFACT_PREPARATION_READY`.** The
repository now contains a human-operated exact-commit build contract at
`infra/release/f4/`, including a detached-worktree build script, offline bundle
verifier, manifest template, exact-commit SQL/workflow hashing, immutable
base-reference requirement, and OCI revision binding for Web and frontend.

This is preparation only. The human build evidence is still required before any
F4 rollout consideration: actual Python/Node base image digests, built image
IDs and archive SHA-256 values, n8n runtime compatibility anchor, and
PostgreSQL runtime compatibility anchor must be captured by the operator.
`docs/F4_IMMUTABLE_RELEASE_ARTIFACTS.md` is the release-artifact consumption
contract.

The existing `n8n` Compose reference is mutable and remains a compatibility
anchor, not an F4 artifact. No broad stack operation, n8n recreation, image
build, deployment, database migration, grants, credential change, workflow
import, or activation is authorized by this repository change. Overall F4
release readiness remains blocked pending the existing human checkpoints and
the new human immutable-build proof.
