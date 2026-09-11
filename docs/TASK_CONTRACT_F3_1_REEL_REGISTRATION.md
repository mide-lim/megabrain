# F3.1 Source-Neutral Reel Registration — Task Contract

## Status

APPROVED_FOR_LOCAL_IMPLEMENTATION

## Risk

YELLOW

Production execution remains RED and human-gated.

## Objective

FastAPI-owned source-neutral registration of Instagram Reels.

## Scope In

- migration 004;
- URL normalization;
- `register_reel` domain operation;
- optional Telegram adapter metadata;
- create-or-return-existing behavior;
- natural-identity conflict protection;
- hermetic Web service tests;
- `ACTIVE_TASK` reconciliation;
- operator grant template/documentation.

## Scope Out

- public `POST /api/reels`;
- internal registration HTTP endpoint;
- n8n;
- Downloader;
- frontend;
- Caddy;
- Compose;
- R2;
- auth/CSRF changes;
- production execution.

## Allowed Paths

- docs/TASK_CONTRACT_F3_1_REEL_REGISTRATION.md
- docs/ACTIVE_TASK.md
- infra/postgres/migrations/004_f3_web_reel_ingestion.sql
- services/web/app/reel_ingestion.py
- services/web/tests/test_reel_ingestion.py

## Forbidden Paths

- apps/web/**
- services/downloader/**
- workflows/**
- services/web/app/main.py
- services/web/app/auth/**
- services/web/app/csrf.py
- infra/Caddyfile
- infra/docker-compose.yml
- skills/**
- .github/workflows/**
- AGENTS.md
- docs/RISK_POLICY.md
- historical Task Contracts
- .env / secret-bearing files

## Acceptance Criteria

- canonical Instagram Reel normalization;
- source-neutral create-or-return-existing;
- optional Telegram metadata;
- no duplicate insertion;
- explicit natural-identity conflict;
- registration requires only `SELECT` + `INSERT` + sequence `USAGE`;
- no `UPDATE`;
- migration alters only the three Telegram-ID nullability constraints;
- no public/internal HTTP registration route in F3.1;
- no downstream dispatch;
- service-scoped tests pass.

## Required Tests

- F3.1 reel-ingestion service tests;
- F3.1 migration contract tests.

## Expected Files

- docs/TASK_CONTRACT_F3_1_REEL_REGISTRATION.md
- docs/ACTIVE_TASK.md
- infra/postgres/migrations/004_f3_web_reel_ingestion.sql
- services/web/app/reel_ingestion.py
- services/web/tests/test_reel_ingestion.py

## Migration Impact

- compatibility-only;
- three Telegram IDs become nullable;
- historical data unchanged;
- migration execution in production remains Red.

## Security Invariants

- WEB_DB_USER only;
- no owner fallback;
- no secrets;
- no public ingestion;
- no n8n/downloader/R2 access;
- no auth/CSRF changes;
- least privilege.

## Rollback / Recovery

- application callers can be rolled back;
- nullable Telegram columns remain compatible;
- routine rollback must NOT blindly restore `NOT NULL`;
- `SET NOT NULL` would require proving no `NULL` rows and separate Red approval.

## Human Gates

Human/Product Owner approval is required before:

- production migration;
- production `GRANT`;
- production deploy;
- production rollback/reverse migration.

Merge remains human-only.

## Runtime and persistence boundary

F3.1 is source-neutral at the ingress boundary and remains Instagram-only.
FastAPI owns the domain registration operation. It has no public or internal
registration HTTP route and does not dispatch downstream processing.

Migration 004 is a compatibility-only local artifact. Production migration,
grant, and deployment execution are not authorized by this contract.

## Future operator-owned production grant

The following statements are documentation for a human operator. They must not
be added to migration 004 and are not authorized for execution by this task.

```sql
GRANT INSERT ON TABLE app.reels TO megabrain_web;
GRANT USAGE ON SEQUENCE app.reels_id_seq TO megabrain_web;
```

The intended F3.1 runtime target is:

- `app.reels`: `SELECT`, `INSERT`;
- `app.reels_id_seq`: `USAGE`.

No `UPDATE`, `DELETE`, ownership, or unrelated privileges are intended.

## Publication and merge

Publication: NONE.

Merge: human-only.

Production: not authorized.
