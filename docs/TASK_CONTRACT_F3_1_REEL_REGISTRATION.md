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
