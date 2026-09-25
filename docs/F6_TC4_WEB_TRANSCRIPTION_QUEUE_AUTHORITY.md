# F6 TC4 — Web Transcription Queue Authority

## Scope and production status

This is a source-only security authority overlay. It does not apply PostgreSQL
privileges, deploy the Web service, modify Docker or n8n, inspect secrets, or
perform a cutover.

Production status:

```text
production = NOT APPLIED
deployment = NOT PERFORMED
cutover = NOT PERFORMED
TC5 = NOT COMPLETE
```

Future production work remains separately human-gated by:

`TC4-WEB-QUEUE-AUTHORITY`

## Intentional authority evolution

F4 authority:

- Web owned authenticated-owner curation only.
- `megabrain_web` could update `curation_status` and could not request or
  process transcription.

F6 authority:

- Web additionally owns the explicit authenticated user-request queue
  transition.
- This is an intentional F6 authority evolution, not an F4 bug. F4 correctly
  represented the authority required by its curation-only Web source contract.
  The later owner-authenticated transcription request adds one bounded user
  intent without transferring processing ownership to Web.

The authority split is exact:

```text
Web / owner-authenticated API
  not_requested|failed → queued

MGB-030
  queued → processing → completed|failed
```

Web does not become the processing consumer. MGB-030 remains responsible for
claiming queued work, creating attempts, processing, provider execution,
reconciliation, terminal persistence, and cleanup. This overlay adds no Web to
MGB-030 dispatch, queue service, webhook, stored procedure, trigger, API,
table, lifecycle state, or schema migration.

## Exact F6 database delta

The canonical Web request query assigns only:

```text
transcription_status = 'queued'
transcription_attempt_id = NULL
updated_at = NOW()
```

When the guarded update does not transition a row, the fallback lifecycle query
reads `transcription_attempt_id`. PostgreSQL therefore requires the explicit
F6 read authority as well as the three assigned-column update authorities.

`001_f6_web_transcription_queue_grant.sql` adds only:

```sql
GRANT SELECT (transcription_attempt_id)
ON TABLE app.reels
TO megabrain_web;

GRANT UPDATE (
    transcription_status,
    transcription_attempt_id,
    updated_at
)
ON TABLE app.reels
TO megabrain_web;
```

The effective `megabrain_web` Reel UPDATE allowlist after F6 is exactly:

```text
curation_status
transcription_status
transcription_attempt_id
updated_at
```

The effective Reel SELECT allowlist remains the reviewed F4 allowlist plus
`transcription_attempt_id`; no unrelated SELECT column is added. The overlay
does not grant table-wide SELECT or UPDATE, `download_status` update, Reel
DELETE, attempt-table authority, enrichment-result write authority, DDL,
schema CREATE, role membership, password changes, or LOGIN changes.

Classification:

```text
schema migration required: NO
runtime security authority delta required: YES
```

The F6 SQL files are controlled security/cutover artifacts. They are not
automatic application-startup migrations.

## F4 → F6 verifier succession

Before the F6 Web queue-authority overlay:

`infra/postgres/security/f4/003_f4_runtime_grants_verify.sql`

describes the valid historical F4 authority boundary.

After the F6 overlay is applied:

`infra/postgres/security/f6/002_f6_web_transcription_queue_verify.sql`

is the authoritative verifier for the evolved Web transcription queue boundary.

The historical F4 checks:

```text
WEB_CAN_WRITE_TRANSCRIPTION = FALSE
WEB_CAN_WRITE_TRANSCRIPTION_ATTEMPT = FALSE
```

are intentionally no longer valid as post-F6 assertions because F6 explicitly
grants the Web role the narrow user-request queue transition.

The F4 artifact must remain unchanged as historical release evidence. It must
not be used alone to decide post-F6 rollout success.

## Verifier and rollback

`002_f6_web_transcription_queue_verify.sql` is catalog-only and mutation-free.
It uses effective privilege checks so unexpected direct, PUBLIC, or
membership-derived authority fails rather than being accepted. It proves the
positive F6 columns, preserved F4 curation update, the exact effective Reel
SELECT/UPDATE allowlists, and the negative download, table-wide, DELETE,
attempt, enrichment-result write, enrichment-result sequence, PUBLIC, and
membership boundaries.

The PUBLIC boundary covers schema `app`, the table and column ACLs for
`app.reels`, `app.reel_enrichment_attempts`, and `app.reel_enrichments`, and
`app.reel_enrichments_id_seq`. It uses `aclexplode(...)` with `grantee = 0`;
PUBLIC is not a `pg_roles` row.

`003_f6_web_transcription_queue_rollback.sql` requires the affirmative psql
acknowledgement variable `f6_web_transcription_queue_rollback_ack=true`. It
revokes only the F6 SELECT delta on `transcription_attempt_id` and the F6
UPDATE delta on `transcription_status`, `transcription_attempt_id`, and
`updated_at`.

It preserves F4 curation, registration, authentication, category, and owner
query hotfix authority, and it does not alter MGB-020 or MGB-030. After this
rollback, the F6 `Transcrever` request endpoint can no longer function with
`megabrain_web`.

## Future human production gate

Before any future application of this reviewed overlay, the human gate must
prove:

1. active Web principal = `megabrain_web`;
2. expected prior privileges are present;
3. no unexpected PUBLIC authority exists;
4. no unexpected role memberships exist;
5. only then, apply the exact reviewed F6 overlay;
6. then execute the exact F6 verifier and require every assertion to report
   `PASS`.

These source artifacts do not grant permission to run those actions now.
