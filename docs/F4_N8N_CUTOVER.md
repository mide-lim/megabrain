# F4 n8n Cutover — Human-Operated Procedure

## Status and authority boundary

`F4_6F_N8N_CUTOVER_PREPARATION_READY` means that this repository contains a
static, human-operated procedure. It is not an approval to cut over F4 and does
not change the overall `F4_6_RELEASE_READINESS_BLOCKED` verdict.

This procedure was prepared from the immutable source commit
`a7eb7aad2da922d65d840523b88c2adcb780fb47`, the reviewed workflow exports, and
human-provided runtime evidence. It made no production connection and performs
no production action. All production actions below require a separately
authorized human operator.

The procedure never authorizes access to production n8n or PostgreSQL,
credential access, password generation, role creation, role LOGIN, grants,
migration execution, workflow import/activation/deactivation, Docker actions,
image deployment, Git push, or merge.

## Immutable artifacts and sanitized-export boundary

| Logical workflow | Authoritative repository artifact | SHA-256 |
| --- | --- | --- |
| MGB-020 | `workflows/MGB-020-download-reel.json` | `1534ec7412447f0285223de54c8ff19e9b542d17e7e2e92b603a2771adc236ac` |
| MGB-030 | `workflows/MGB-030-enrichment-reel.json` | `f6b5974643926a42f1033560abb0293fb239fd7330c65a9d4a54d177c58e4695` |

The repository SHA-256 values match the immutable release-bundle values. A
human must independently re-hash the exact file selected for import; mismatch
is a stop condition.

The JSON exports intentionally omit or replace:

- credential IDs and credential names/bindings;
- credential secrets;
- private URLs and internal authentication values;
- production workflow IDs;
- node IDs and webhook runtime IDs;
- instance/version runtime IDs;
- activation state as production truth.

`active` in a sanitized file is reviewed logical content, not evidence of the
production activation state. `MGB-020` is logically active and `MGB-030` is
logically inactive in these exports; neither fact establishes the production
state.

Matching JSON SHA proves reviewed logical definition. It does not prove that
production has the correct credential binding, workflow ID, webhook identity,
activation state, or private endpoint values. The human rollout must verify
those separately.

## n8n 2.32.5 cutover model

The supplied runtime anchor is n8n `2.32.5`, image ID
`sha256:3647d2b986f03174a7c0c6a0cd57bc870a769ea7a5538838b94d9714b57e9057`, and
RepoDigest
`docker.n8n.io/n8nio/n8n@sha256:3647d2b986f03174a7c0c6a0cd57bc870a769ea7a5538838b94d9714b57e9057`.

Preferred model: B — import new inactive F4 workflow definitions alongside the
captured old workflows, bind each dedicated credential explicitly, inspect them,
and activate only after the old path is quiesced. This preserves old workflow
configuration as rollback evidence, avoids in-place editing against an
unknown production identity, and makes a credential switch observable.

This preference is conditional on `HUMAN_N8N_UI_PROOF_REQUIRED`. Before any
import, the operator must demonstrate in the actual n8n 2.32.5 UI/API that the
chosen import path:

1. creates a separate inactive workflow rather than silently overwriting an
   existing one;
2. exposes the resulting production workflow ID and node credential selectors;
3. permits reviewing all references and private values before activation; and
4. does not activate a trigger or duplicate webhook while the old workflow is
   retained.

Do not use model A (update in place) without a human-confirmed, reversible
identity-preserving operation. Do not use model C (overwrite/replace by known
production ID): the exports are logical artifacts, not production identity
backups, and no repository evidence establishes n8n overwrite behavior.

If the UI/API cannot prove separate inactive import without ambiguous overwrite
or trigger registration, stop before import: `HUMAN_REMEDIATION_REQUIRED`.

## Required production identity capture — read-only

Before closing entry points, the human operator records a timestamped inventory
from production n8n. This is evidence collection, not a workflow change.

For MGB-020 and MGB-030 separately capture:

- production workflow ID;
- current workflow name;
- current active state;
- each PostgreSQL node's credential display name and credential ID, if the UI
  exposes it without revealing a secret;
- all inter-workflow calls/references, recording node name, target ID, target
  name, and call mode;
- webhook IDs, webhook paths, and trigger identities where present;
- current execution inventory and exact displayed/API execution states.

Capture the upstream dispatch surfaces too:

| Artifact | Source-derived dispatch behavior | Required cutover action |
| --- | --- | --- |
| MGB-001 | Telegram trigger invokes MGB-010 by workflow ID placeholder | disable/pause before drain |
| MGB-010 | calls FastAPI `POST /internal/reels`; no direct MGB-020 call in the sanitized export | disable/pause before drain |
| MGB-015 | authenticated internal webhook invokes MGB-020 asynchronously by workflow ID placeholder | disable/pause and block its Web caller before drain |
| MGB-020 | after guarded `downloaded` persistence, executes MGB-030 by workflow ID placeholder | keep inactive until controlled activation |

MGB-020 → MGB-030: execute-workflow reference by workflow ID placeholder. After
an inactive import, the operator must explicitly select/rebind the imported
MGB-030 target only after confirming the imported workflow's production ID and
name. MGB-001 → MGB-010 and MGB-015 → MGB-020 have the same ID-placeholder
limitation. MGB-010's dispatch is indirect through FastAPI and then MGB-015;
its runtime endpoint/auth configuration is private and requires separate human
confirmation.

## Database credential transition

The current shared n8n credential is `MegaBrain → megabrain`. `megabrain` owns
the relevant schema objects. It is not an F4 runtime principal after cutover.

| Target n8n credential record | PostgreSQL principal | Allowed F4 workflow |
| --- | --- | --- |
| MegaBrain F4 MGB-020 | `megabrain_mgb020` | MGB-020 only |
| MegaBrain F4 MGB-030 | `megabrain_mgb030` | MGB-030 only |

The operator may adjust the display names, but each name must be unambiguous
and must encode the workflow/principal pairing.

After provisioning, each role must be exactly constrained to:

```text
LOGIN
NOSUPERUSER
NOCREATEDB
NOCREATEROLE
NOREPLICATION
NOBYPASSRLS
NOINHERIT
```

Secure human-only credential provisioning:

1. Use an approved privileged, interactive operator session that does not
   capture terminal input, screen recording, shell history, process arguments,
   environment dumps, repository files, or transcript logs containing a
   password.
2. Verify the existing role identity before changing it. Apply the required
   non-secret attributes and LOGIN only to the matching dedicated role.
3. Set the password through the database client's protected interactive password
   facility (for example, psql `\password`) or an approved secret-management
   integration. Never enter the password as SQL text, shell argv, shell
   environment, repository content, or n8n workflow JSON.
4. Create each n8n PostgreSQL credential through the n8n secret UI/store, bind
   only its matching principal, and never export or record its secret/ID here.
5. Verify connection and the established F4 positive/negative privilege proof
   through the approved human procedure before activation.

`MegaBrain → megabrain` must NOT be deleted during the initial cutover. It is
rollback evidence and may be used by unrelated workflows. Its global absence of
use is unproven.

Read-only owner-credential inventory: the operator lists every n8n workflow
node whose PostgreSQL credential selector resolves to `MegaBrain`, captures
workflow ID/name/active state/node name, and distinguishes MGB-020/MGB-030
from unrelated usage. The required target proof is
`OWNER_ROLE_USED_BY_F4_RUNTIME=NO`: zero MGB-020/MGB-030 PostgreSQL nodes bind
to `MegaBrain → megabrain`. Retain the credential until a later all-workflow
inventory and separate approval establishes deletion safety.

## Quiesce and INFLIGHT_ZERO

F4 is not rolling-compatible: migration 005 removes the old `status` contract.
The zero-count check is valid only after every source capable of new F4 work is
closed.

### Entry closure sequence

1. Close every F4 entry point and dispatch source: pause/deactivate MGB-001,
   MGB-010, and MGB-015; block their Telegram, internal-webhook, and FastAPI
   dispatch paths; stop Web registration and curation writes; and place old
   dynamic Reel reads behind maintenance.
2. Prove new entry is impossible: capture the disabled state of every upstream
   workflow plus the maintenance/route evidence that rejects Web writes and
   prevents old Reel API reads from reaching the old backend.
3. Deactivate/pause MGB-020 and MGB-030 after their upstream sources are
   closed. Do not assume deactivation terminates existing executions.
4. Drain/account for every existing execution and old Web write request. Each
   pre-closure execution must either finish in a terminal state or have a
   human-approved, recorded disposition; no execution may be silently ignored.
5. Confirm INFLIGHT_ZERO only after the preceding entry-closure evidence.
6. Run migration 005 exactly once only while INFLIGHT_ZERO remains true and the
   entry-closure controls remain in force.

One zero-count query before entry closure is insufficient. The closed sequence
eliminates the race `zero check → new trigger → migration` by proving entry
closure before draining and by keeping it in force through migration/runtime
replacement.

### INFLIGHT_ZERO definition

`INFLIGHT_ZERO` is true only when all conditions below are simultaneously
recorded after entry closure:

1. no source can create a new Reel, dispatch MGB-020, invoke MGB-030, or submit
   an old Web write;
2. every MGB-001, MGB-010, MGB-015, MGB-020, and MGB-030 execution that could
   insert/dispatch a Reel, transition download lifecycle, invoke MGB-030, or
   update transcription lifecycle is terminal or individually accounted for;
3. every old Web registration/curation request is completed/terminated and no
   old dynamic Reel request can reach the incompatible backend;
4. n8n shows zero executions in every nonterminal state that can continue after
   entry closure; and
5. the operator repeats the count after the drain interval while entry closure
   is still effective.

`HUMAN_N8N_EXECUTION_STATE_PROOF_REQUIRED`: the repository does not establish
which exact labels/API values the installed n8n 2.32.5 instance exposes for
`running`, `waiting`, or a `new`/`pending` equivalent. The human must capture
those actual UI/API state labels, establish which are nonterminal, query/filter
each relevant workflow by them, and retain zero-result evidence. Do not invent
state names and do not treat deactivation alone as cancellation.

Any active nonterminal execution, unknown queue/pending representation,
unaccounted execution, or failure to prove entry closure is `STOP_NEEDS_HUMAN`.

## Web maintenance requirement

The repository contains no proven production maintenance-routing implementation
that can isolate static traffic from old Reel API reads/writes. The human
rollout must provide a narrow, pre-reviewed routing/deployment control that:

- rejects or maintenance-routes old registration and curation mutations;
- blocks old library/detail/dynamic Reel reads during the incompatible schema
  interval;
- allows unrelated static traffic only after proving that it cannot call the
  old Reel API contract; and
- remains active until the exact F4 backend/frontend pair has passed smoke.

Absence of that narrow routing proof is `HUMAN_REMEDIATION_REQUIRED`. Do not
implement production maintenance routing as part of F4.6F.

## Static PostgreSQL operation and grant review

MGB-020 static SQL review: PASS. Its three PostgreSQL nodes perform only:

| Node | Operations | Required dedicated authority |
| --- | --- | --- |
| DB — Reivindicar processamento | `UPDATE app.reels` claim; `SELECT` existing/returned Reel fields | `SELECT` reviewed Reel projection; `UPDATE` download-status, start/error/timestamp fields |
| DB — Marcar downloaded | guarded `UPDATE app.reels`; `RETURNING` Reel/download metadata | reviewed download terminal `UPDATE` columns and returned/read columns |
| DB — Registrar falha | guarded `UPDATE app.reels`; increments retry data; `RETURNING` | reviewed failure `UPDATE` columns and returned/read columns |

All MGB-020 columns used in `SET`, `WHERE`, CTEs, and `RETURNING` are within
`002_f4_runtime_grants.sql` for `megabrain_mgb020`; it uses no insert, delete,
DDL, sequence, transcription, curation, auth, category, or owner operation.

MGB-030 static SQL review: PASS. Its PostgreSQL nodes perform only:

| Node | Operations | Required dedicated authority |
| --- | --- | --- |
| DB — Localizar Reel elegível | `SELECT app.reels`; applicable-result `EXISTS` query | reviewed Reel and enrichment `SELECT` columns |
| DB — Enfileirar transcrição | guarded `UPDATE app.reels`; result existence check | reviewed Reel `SELECT` and transcription `UPDATE` columns; enrichment `SELECT` |
| DB — Criar tentativa processing | guarded Reel `UPDATE`; `INSERT app.reel_enrichment_attempts` | reviewed Reel select/update and attempt insert columns |
| DB — Persistir resultado e concluir tentativa | attempt `UPDATE`; result `INSERT`; guarded Reel `UPDATE` | reviewed attempt update, enrichment select/insert/sequence usage, and Reel select/update |
| DB — Registrar falha da tentativa | guarded attempt `UPDATE`; guarded Reel `UPDATE` | reviewed attempt and Reel select/update columns |

All MGB-030 columns used in projections, predicates, CTEs, `RETURNING`,
updates, and inserts are within `002_f4_runtime_grants.sql` for
`megabrain_mgb030`, including only `USAGE` on `app.reel_enrichments_id_seq`.
It has no download-status/curation update, delete, DDL, auth, category, or
owner operation.

No workflow operation requires owner authority. A discovered source/grant
mismatch is `F4_6F_BLOCKED`; do not broaden grants automatically.

## Human checkpoint procedure

The controls below are ordered from static/recovery evidence through controlled
re-entry. “STOP” means halt the cutover and retain the recorded evidence; do
not continue despite a mismatch.

| Checkpoint | Human action | Precondition and exact expected evidence | Stop condition | Rollback / forward-fix disposition |
| --- | --- | --- | --- | --- |
| A — immutable anchors | Re-verify exact source/bundle/runtime identities. | Source commit and two workflow SHA-256 values match; n8n is 2.32.5 with supplied image ID/RepoDigest; PostgreSQL is 16.14; backend image ID is `sha256:3845bfd52b65856b35d84bf3202952a3589a44ebbf666ab1bd2619a3296b592f`; frontend image ID is `sha256:deb256b6b6b9c622c6d4df9b1afaafc4135fb1381aab055d54753794c15f8c68`. | wrong workflow hash → STOP; wrong runtime n8n image/version → STOP; OCI image revision mismatch → STOP. | No mutation: correct evidence before resuming. |
| B — capture state | Perform the read-only identity, owner-credential, execution, and upstream inventory. | Every required MGB-020/MGB-030 identity field and every `MegaBrain` PostgreSQL node reference is recorded. | Missing identity, active state, credential binding, reference, or execution-state evidence → STOP. | No mutation: recapture evidence. |
| C — close entry | Close upstream Telegram, FastAPI/internal dispatch, Web writes, and old dynamic Reel reads; pause MGB-001/MGB-010/MGB-015. | UI/routing proof shows each entry disabled or blocked; no open path can create F4 work. | Any entry remains reachable or proof is ambiguous → STOP. | Restore old controls only before migration, then investigate. |
| D — drain | Pause MGB-020/MGB-030 and drain. | Entry closure remains proved; HUMAN_N8N_EXECUTION_STATE_PROOF_REQUIRED is satisfied; INFLIGHT_ZERO evidence is captured twice after drain. | in-flight execution exists → STOP; unaccounted execution/state → STOP. | Before migration, old runtime/workflow controls can be restored deliberately. |
| E — backup/trust | Revalidate approved recoverable backup, migration preflight capability, and human D2 proof availability. | Current backup/recovery proof, aggregate preflight capture, and post-migration aggregate validator are accepted. | Missing/failed backup, preflight, or validator → STOP. | No mutation: remediate evidence/control. |
| F — structural roles | If not already human-proven, run reviewed `001_f4_runtime_roles.sql` only. | D confirms quiesce; roles do not already conflict; expected result is restrictive dedicated `NOLOGIN` structures only. | Unexpected existing role state or SQL result → STOP. | Before credential provisioning, dedicated structures can be removed only through approved human recovery. |
| G — migration | Run migration 005 exactly once. | D/E remain valid; exact legacy shape, aggregate preflight, and migration transaction preconditions pass. | migration preflight mismatch → STOP; transaction/postcondition failure → STOP. | Before commit, transaction rollback. After commit, keep all old writers/readers closed. |
| H — grants/verifier | Run reviewed `002_f4_runtime_grants.sql`, then catalog-only `003_f4_runtime_grants_verify.sql`. | Migration committed; all verifier assertions return `PASS`, including no owner/runtime ownership boundary violation. | role verifier FAIL → STOP. | Do not broaden grants. Forward-fix privilege configuration under separate human review; do not enable runtime. |
| I — dedicated credentials | Provision `megabrain_mgb020` and `megabrain_mgb030` with required restrictive LOGIN attributes and create the two n8n credential records. | H passed; secure interactive password method is available; no secret will be logged/versioned. | Attribute/connection/privilege proof mismatch → STOP. | Quiesce; disable the dedicated logins only through approved recovery. Do not delete `MegaBrain`. |
| J — backend | Deploy only exact verified backend image. | New schema, H verifier, and I credentials are proved; writers remain closed. | Image ID/revision mismatch or targeted deployment cannot be proved no-build → STOP. | After migration, do not resume old backend against new schema; forward-fix or separately approved reverse migration only before new writes. |
| K — inactive workflows | Import new MGB-020/MGB-030 only as inactive, separate identities after HUMAN_N8N_UI_PROOF_REQUIRED. | B captured old identities; A hashes match; import path proves no overwrite/activation. | Ambiguous overwrite, unexpected activation, or hash mismatch → STOP. | Keep old workflows intact and remove/disable only the newly imported inactive copy under human control. |
| L — bind and inspect | Bind MGB-020 only to MegaBrain F4 MGB-020 and MGB-030 only to MegaBrain F4 MGB-030; inspect SQL nodes and workflow references. | Every PostgreSQL node has the matching dedicated credential; MGB-020 target points to intended new MGB-030; upstream references are recorded and remain closed. | workflow still bound to owner credential → STOP; missing/private endpoint or target reference mismatch → STOP. | Keep writers closed; correct new inactive configuration, never reactivate owner-bound old workflows. |
| M — frontend | Deploy only exact verified frontend image. | J/L pass; targeted no-build deployment is proven; n8n/PostgreSQL are not recreated. | Image mismatch, broad stack operation, n8n recreate, or PostgreSQL recreate → STOP. | Keep maintenance; forward-fix matching frontend/runtime pair. |
| N — smoke closed | Run approved read-only/mutation-safe smoke while writers remain closed. | New backend/frontend load existing Reel lifecycle projections; owner/session/CSRF and static isolation evidence passes; no old-contract read reaches runtime. | Smoke failure → STOP. | Maintain quiesce and forward-fix; do not resume old runtime on migrated schema. |
| O — controlled activation | Activate new MGB-030 and MGB-020 only after L/N, in an operator-recorded order that cannot duplicate a trigger. | Both dedicated bindings, target workflow IDs, and owner-credential invariant are proved; upstream stays closed. | Activation creates duplicate trigger/call, owner binding, or unexpected execution → STOP. | Deactivate newly activated F4 processing; do not re-enable old owner-bound workflow against migrated schema. |
| P — controlled intake | Reopen upstream entry points in controlled order: dispatch path, then accepted intake; retain execution monitoring. | O stable; every source points only to intended F4 workflow identity. | New execution fails lifecycle/credential/endpoint proof → STOP. | Close entry again and forward-fix; no legacy workflow reactivation. |
| Q — final health | Capture final runtime health, lifecycle aggregates, execution inventory, and owner-credential inventory. | Post-migration aggregate mapping/counts and final F4 lifecycle projection validation pass; INFLIGHT_ZERO is no longer required because controlled traffic is intentionally open. | Aggregate/health/owner-binding mismatch → STOP. | Quiesce F4 writers and prefer forward-fix; recovery mutation requires separate approval. |

## Artifact consumption restrictions

Consume only the already-proven images:

| Artifact | Required image ID |
| --- | --- |
| Backend | `sha256:3845bfd52b65856b35d84bf3202952a3589a44ebbf666ab1bd2619a3296b592f` |
| Frontend | `sha256:deb256b6b6b9c622c6d4df9b1afaafc4135fb1381aab055d54753794c15f8c68` |

No build during cutover.

No broad docker compose up.

No n8n pull/recreate.

No PostgreSQL pull/recreate.

The human deployment proof must show a targeted Web/frontend-only no-build
switch. It must not pull, recreate, or alter n8n, PostgreSQL, Caddy, downloader,
or enricher.

## Rollback boundary

| Boundary | Disposition |
| --- | --- |
| Before migration | Full workflow/runtime rollback is available: keep or restore the legacy runtime only while legacy schema remains intact. |
| Post-migration, pre-write | Old runtime cannot simply resume because the legacy `status` contract is absent. Keep writers/readers closed; a separately reviewed reverse migration may be considered only if no dependent F4 runtime/write has occurred. |
| Post-F4 write | Prefer forward-fix. New F4 lifecycle/transcription/curation data makes a reverse migration semantically unsafe without an approved preservation/reconciliation plan. Never use workflow rollback to re-enable an old owner-bound workflow against migrated schema. |

## Required remaining human proofs

- `HUMAN_N8N_UI_PROOF_REQUIRED`: inactive separate import, identity, activation,
  webhook/trigger behavior, credential selectors, and reference rebinding on
  n8n 2.32.5.
- `HUMAN_N8N_EXECUTION_STATE_PROOF_REQUIRED`: exact UI/API nonterminal states
  and zero-execution filtering/accounting.
- recoverable backup/recovery, migration preflight/post-migration aggregate
  validator, and final PostgreSQL verifier evidence.
- secure dedicated credential provisioning and connection/privilege proof.
- exact targeted no-build backend/frontend deployment proof and narrow Web
  maintenance-routing proof.
- human execution of all cutover checkpoints under a distinct rollout gate.
