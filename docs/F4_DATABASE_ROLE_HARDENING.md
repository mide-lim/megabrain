# F4 Database Role Hardening

## Scope and authority

This is a build-and-review artifact for a future human-authorized rollout. It does not authorize or perform PostgreSQL access, role creation, grants, revokes, migration 005, n8n credential work, workflow changes, deployment, or container operations.

The reviewed production evidence is human-provided, not re-probed by this stage:

| Runtime | Current principal | State |
| --- | --- | --- |
| Web | `megabrain_web` | dedicated runtime principal |
| MGB-020 | `megabrain` | owner credential reused |
| MGB-030 | `megabrain` | owner credential reused |

`megabrain` owns schema `app` and the F4 relations. The current model is functionally sufficient but fails the F4 database least-privilege boundary because both n8n workflow authorities share the owner credential.

## Target topology

| Principal | Steady-state responsibility | Must not own |
| --- | --- | --- |
| `megabrain` | schema/table/sequence owner and migration operator | no runtime credential attachment after cutover |
| `megabrain_web` | Web registration, library/detail, authentication, categories, and curation | F4 relations/sequences |
| `megabrain_mgb020` | MGB-020 download lifecycle only | F4 relations/sequences |
| `megabrain_mgb030` | MGB-030 transcription/enrichment lifecycle only | F4 relations/sequences |

`001_f4_runtime_roles.sql` creates the two dedicated roles as `NOLOGIN`, `NOSUPERUSER`, `NOCREATEDB`, `NOCREATEROLE`, `NOREPLICATION`, `NOBYPASSRLS`, and `NOINHERIT`. It is noninteractive and contains neither a password command nor a `LOGIN` transition. It neither grants ownership nor commits a password literal.

This structural artifact is intentionally usable through noninteractive psql stdin for the disposable integration proof. A test superuser can `SET ROLE megabrain_mgb020` or `SET ROLE megabrain_mgb030` without either role having a login password. The roles cannot authenticate until a later human production credential-provisioning step enables login and sets each password outside Git.

Do not pass secrets through shell history, standard input transcripts, environment dumps, or process arguments. In particular, `psql --set=...password=...` and `CREATE/ALTER ROLE ... PASSWORD ...` expose plaintext values through process argv or PostgreSQL statement logging and are not approved invocations. After the structural/grant proof, an authorized human must use an interactive protected prompt such as psql's `\password`, or an approved secure operator mechanism, to provision each production credential and enable `LOGIN`. No password or credential ID is stored in Git.

## Source-derived authority matrix

Column lists include PostgreSQL `SELECT` requirements from projections, `WHERE`, `RETURNING`, joins, CTEs, correlated predicates, and `UPDATE` right-hand sides. `UPDATE` is granted only for assigned columns.

### Web

| Relation | Final privilege |
| --- | --- |
| `app` | `USAGE`; no `CREATE` |
| `app.reels` | `SELECT` on `id, shortcode, original_url, source, download_status, curation_status, transcription_status, telegram_chat_id, telegram_user_id, telegram_message_id, raw_message, received_at, title, creator, caption, duration_seconds, filename, mime_type, file_size_bytes, storage_provider, storage_bucket, object_key, downloaded_at`; `INSERT` on `shortcode, original_url, source, download_status, telegram_chat_id, telegram_user_id, telegram_message_id, raw_message, received_at`; `UPDATE (curation_status)` only |
| `app.reels_id_seq` | `USAGE` |
| `app.reel_enrichments` | `SELECT` on `id, reel_id, completed_at, media_duration_seconds, outcome, transcript_text, transcript_language` |
| `app.categories` | `SELECT (id, name)`, `INSERT (name)`, `USAGE` on `app.categories_id_seq` |
| `app.reel_categories` | `SELECT (reel_id, category_id)`, `INSERT (reel_id, category_id)`, table-level `DELETE` |
| `app.auth_transactions` | `SELECT (transaction_hash, state_hash, nonce, pkce_verifier, return_path, expires_at, consumed_at)`, `INSERT (transaction_hash, provider, state_hash, nonce, pkce_verifier, return_path, created_at, expires_at, consumed_at)`, `UPDATE (consumed_at)` |
| `app.auth_users` | `SELECT (id, provider_issuer, provider_subject, disabled_at, email)`, `INSERT (provider, provider_issuer, provider_subject, email, email_normalized, created_at, updated_at, last_login_at, disabled_at)`, `UPDATE (email, email_normalized, updated_at, last_login_at)`, `USAGE` on `app.auth_users_id_seq` |
| `app.auth_sessions` | `SELECT (token_hash, user_id, expires_at, revoked_at)`, `INSERT (token_hash, user_id, created_at, expires_at, revoked_at)`, `UPDATE (revoked_at)` |
| `app.reel_enrichment_attempts` | no access |

The table-level `DELETE` on `app.reel_categories` is retained because PostgreSQL does not support column-scoped `DELETE`; it is required by the current category-removal SQL. No table-wide `SELECT`, `INSERT`, or `UPDATE` is retained for `app.reels`.

Web may write `curation_status`. It may not write `download_status`, `transcription_status`, or `transcription_attempt_id`.

### MGB-020

| Relation | Final privilege |
| --- | --- |
| `app` | `USAGE`; no `CREATE` |
| `app.reels` `SELECT` | `id, shortcode, original_url, telegram_chat_id, download_status, filename, file_size_bytes, storage_bucket, object_key, downloaded_at, error_message, retry_count` |
| `app.reels` `UPDATE` | `download_status, download_started_at, error_message, updated_at, title, creator, caption, duration_seconds, filename, mime_type, file_size_bytes, sha256, storage_provider, storage_bucket, object_key, downloaded_at, retry_count, last_error_at` |

MGB-020 has no `INSERT`, `DELETE`, `TRUNCATE`, DDL, ownership, sequence, auth-table, category, curation, transcription-status, or transcription-attempt authority. The column list is derived from the three final SQL nodes in `workflows/MGB-020-download-reel.json`: claim, downloaded terminal persistence, and failure terminal persistence.

### MGB-030

| Relation | Final privilege |
| --- | --- |
| `app` | `USAGE`; no `CREATE` |
| `app.reels` `SELECT` | `id, shortcode, object_key, sha256, file_size_bytes, download_status, transcription_status, transcription_attempt_id` |
| `app.reels` `UPDATE` | `transcription_status, transcription_attempt_id, updated_at` |
| `app.reel_enrichment_attempts` `SELECT` | `attempt_id, reel_id, source_object_key, expected_sha256, expected_size_bytes, pipeline_version, contract_version, language_hint, status, retryable, error_code, error_stage` |
| `app.reel_enrichment_attempts` `INSERT` | `attempt_id, reel_id, source_object_key, expected_sha256, expected_size_bytes, pipeline_version, contract_version, language_hint, retry_of_attempt_id, status, started_at` |
| `app.reel_enrichment_attempts` `UPDATE` | `status, finished_at, enricher_version, stt_provider, stt_model, provider_request_id, error_code, error_stage, error_message, retryable` |
| `app.reel_enrichments` `SELECT` | `id, reel_id, source_attempt_id, source_object_key, source_sha256, pipeline_version, outcome` |
| `app.reel_enrichments` `INSERT` | `reel_id, source_attempt_id, source_object_key, source_sha256, source_size_bytes, pipeline_version, completed_at, container_format, media_duration_seconds, video_codec, video_width, video_height, audio_present, audio_codec, audio_sample_rate_hz, audio_channels, audio_duration_seconds, transcription_audio_format, transcription_audio_sample_rate_hz, transcription_audio_channels, transcription_audio_duration_seconds, outcome, transcript_text, transcript_language` |
| `app.reel_enrichments_id_seq` | `USAGE` only |

MGB-030 has no download-status or curation-status write, `DELETE`, `TRUNCATE`, DDL, ownership, auth-table, or category authority. The sole sequence grant supports the identity `id` generated by the result insert; no workflow insert uses another sequence.

## SQL artifact sequence

1. `infra/postgres/security/f4/001_f4_runtime_roles.sql` — transactionally creates the two restrictive `NOLOGIN` role structures only. It is safe to prepare before migration 005 because it grants no F4-column authority.
2. `infra/postgres/security/f4/002_f4_runtime_grants.sql` — transactionally validates the final schema/identity sequences, removes direct grants to the three F4 runtime roles on the reviewed objects, and restores exact source-derived grants.
3. `infra/postgres/security/f4/003_f4_runtime_grants_verify.sql` — catalog-only privilege proof. All rows must say `PASS`.
4. `infra/postgres/security/f4/004_f4_runtime_grants_rollback.sql` — dedicated-role privilege rollback only, gated by a human credential-detachment acknowledgement with the affirmative value `true`; it commits both dedicated roles as `NOLOGIN` before checking active sessions in the separate destructive phase.

The grant script does not change `PUBLIC` grants or inherited-role membership. That scope is intentionally excluded to avoid silently changing unrelated authority. The verifier fails if either mechanism still creates an authority boundary violation.

## Required rollout ordering

| Phase | Human-only action |
| --- | --- |
| A — pre-migration | Create dedicated `NOLOGIN` role structures using `001`, if approved. The roles cannot authenticate at this point. Do not apply final F4 grants yet. |
| B — quiesce | Pause/drain old incompatible readers and writers: MGB-001/MGB-010/MGB-015 dispatch, MGB-020, MGB-030, Web writes, and old Web Reel reads. Account for in-flight work. |
| C — schema | Execute migration 005 exactly once under its separate authorization. |
| D — final authority | Execute `002`; execute `003`; remediate every verifier `FAIL` before enabling runtime. |
| E — credential switch | After the structural/grant proof, the human provisions each production `LOGIN` credential outside Git, then creates two new n8n PostgreSQL credentials with the dedicated principals, assigns MGB-020 to `megabrain_mgb020` and MGB-030 to `megabrain_mgb030`, and verifies each F4 PostgreSQL node. |
| F — matching release | Import/review/activate the matching F4 workflows and deploy the matching runtime under separate authorization. Resume only after smoke and authority proof. |

Migration 005 changes legacy `status` to `download_status` and adds F4 lifecycle columns. Applying final grants before that migration is intentionally rejected by `002`.

## Credential rotation plan

Current assignment:

| Workflow | Credential | Principal |
| --- | --- | --- |
| MGB-020 | `MegaBrain` | `megabrain` |
| MGB-030 | `MegaBrain` | `megabrain` |

Target assignment:

| Workflow | Credential | Principal |
| --- | --- | --- |
| MGB-020 | newly created dedicated n8n PostgreSQL credential | `megabrain_mgb020` |
| MGB-030 | newly created dedicated n8n PostgreSQL credential | `megabrain_mgb030` |

Human procedure:

1. Create dedicated credentials using the new role secrets outside Git. Do not record credential IDs or secrets in this repository.
2. During the quiesced cutover, assign each credential only to the matching MGB-020 or MGB-030 PostgreSQL nodes.
3. Confirm connection and execute the approved positive/negative privilege proof before activation.
4. Inventory all F4 workflow nodes and prove zero MGB-020/MGB-030 nodes still use the `MegaBrain` owner credential.
5. Retain the old credential until a separate all-workflow inventory establishes that it has no remaining legitimate use. This stage never authorizes deletion.

The post-cutover invariant is `OWNER_ROLE_USED_BY_F4_RUNTIME=NO`. It is an n8n configuration fact, not something PostgreSQL catalogs can prove; the human must document the node/credential inventory in the future rollout evidence.

## Verification and eventual integration proof

`003` verifies catalog authority without application data. It checks required source columns, rejects table-wide and excess effective Reel privileges, rejects effective runtime access to every auth relation, and detects any membership granted to a dedicated runtime role. Its dedicated-role attribute checks deliberately do not require `LOGIN`, so the structural/grant verifier also passes in the disposable `NOLOGIN` proof before human credential provisioning. `has_*_privilege` resolves direct, `PUBLIC`, and applicable inherited authority, so a pre-existing broad grant becomes a `FAIL` rather than a silent exception. Required invariant rows include:

| Invariant | Required result |
| --- | --- |
| `MGB020_CAN_WRITE_DOWNLOAD` | `PASS` |
| `MGB020_CAN_WRITE_TRANSCRIPTION` | `PASS` with expected `false` |
| `MGB020_CAN_WRITE_CURATION` | `PASS` with expected `false` |
| `MGB030_CAN_WRITE_TRANSCRIPTION` | `PASS` |
| `MGB030_CAN_WRITE_DOWNLOAD` | `PASS` with expected `false` |
| `MGB030_CAN_WRITE_CURATION` | `PASS` with expected `false` |
| `WEB_CAN_WRITE_CURATION` | `PASS` |
| `WEB_CAN_WRITE_DOWNLOAD` | `PASS` with expected `false` |
| `WEB_CAN_WRITE_TRANSCRIPTION` | `PASS` with expected `false` |

A disposable PostgreSQL execution test was not feasible in this build: the repository has no tracked `app.reels` baseline DDL or migration runner, no local PostgreSQL server binaries/harness, and Docker control is prohibited. Static contract tests prove the committed source/artifact boundary, not PostgreSQL runtime semantics.

`HUMAN_ROLE_INTEGRATION_PROOF_REQUIRED`: an authorized future gate must apply the schema and artifact sequence to a disposable or approved human-controlled PostgreSQL environment, execute the final workflow SQL using the dedicated principals, and retain command/result evidence.

### Negative probes for that future gate

Run as the stated dedicated login in a disposable test database or an approved quiesced rollout environment. Each must be denied by PostgreSQL, not merely return zero rows:

| Principal | Probe |
| --- | --- |
| MGB-020 | `UPDATE app.reels SET transcription_status = transcription_status WHERE FALSE;` |
| MGB-020 | `UPDATE app.reels SET transcription_attempt_id = transcription_attempt_id WHERE FALSE;` |
| MGB-020 | `UPDATE app.reels SET curation_status = curation_status WHERE FALSE;` |
| MGB-020 | `DELETE FROM app.reels WHERE FALSE;` and `CREATE TABLE app.f4_privilege_probe (id integer);` |
| MGB-030 | `UPDATE app.reels SET download_status = download_status WHERE FALSE;` |
| MGB-030 | `UPDATE app.reels SET curation_status = curation_status WHERE FALSE;` |
| MGB-030 | `DELETE FROM app.reels WHERE FALSE;` and `CREATE TABLE app.f4_privilege_probe (id integer);` |
| Web | `UPDATE app.reels SET download_status = download_status WHERE FALSE;` |
| Web | `UPDATE app.reels SET transcription_status = transcription_status WHERE FALSE;` |
| Web | `UPDATE app.reels SET transcription_attempt_id = transcription_attempt_id WHERE FALSE;` |
| Web | `DELETE FROM app.reels WHERE FALSE;` |

Use a transaction and rollback for allowed test writes; do not use production content as a fixture. The `CREATE TABLE` tests must be expected to fail before any object is created.

### Positive proof model for that future gate

Execute the unmodified reviewed SQL paths with controlled fixture data and roll back the test transaction:

- Web: registration insert and identity fallback, library/detail select, curation update.
- MGB-020: claim `received|failed → downloading`, mark downloaded, mark failed.
- MGB-030: eligibility read, queue, processing activation and attempt insert, attempt completion/failure terminal update, enrichment result insert, and terminal Reel projection.

A privilege design is not accepted merely because negative probes fail; all allowed operations must complete under the dedicated login while their guards and constraints remain in force.

## Privilege rollback

This is a privilege/credential-transition rollback, not a full F4 schema rollback.

- Before the credential switch, confirm both new roles are unused, then `004` may revoke their reviewed-object rights and drop them.
- After a credential switch, first quiesce the affected workflows. Restore the approved previous assignment only if the schema/runtime compatibility decision explicitly permits it. Verify zero F4 nodes use either dedicated credential, then execute `004` with `f4_dedicated_credentials_detached=true`. It first commits both roles as `NOLOGIN`, then in a separate destructive phase terminates any residual dedicated-role sessions and rechecks before revoking and dropping. If session termination, the recheck, or the destructive phase fails, the roles intentionally remain disabled; human recovery must account for that state. It still fails closed if unrelated dependencies remain.
- After migration/new runtime writes, prefer a forward fix. Do not use role rollback to imply that an F4 schema rollback is safe.

`004` does not touch `megabrain_web`, does not reassign ownership, and does not alter unrelated roles.

## Preexisting hardening debt

Historical documentation (`docs/SPRINT_4_SECURITY.md`) used table-level Web `SELECT` and table-level `INSERT` templates. The reviewed current Web source has explicit column projections/targets, so `002` replaces direct grants on reviewed objects with exact column grants. The only intentionally table-level current Web operation is category-link `DELETE`, because PostgreSQL does not support a column-scoped alternative.

Repository evidence cannot prove the deployed privilege state beyond the supplied live evidence for `megabrain_web` on `app.reels`. Any unexpected pre-existing `PUBLIC`, membership-derived, table-wide, ownership, or unrelated-role authority is `PREEXISTING_HARDENING_DEBT` unless it blocks the verifier; a failing verifier blocks the future rollout until a separately reviewed human remediation resolves it.
