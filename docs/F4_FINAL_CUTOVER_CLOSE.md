# F4 Final Production Cutover Close

Date: 2026-09-18

## Result

The F4 production cutover completed its controlled runtime acceptance.

The final proof covered:

- Google OIDC owner authentication;
- authenticated Web Reel registration;
- MGB-015 internal dispatch;
- MGB-020 download lifecycle ownership;
- Cloudflare R2 persistence;
- R2 size and SHA-256 integrity;
- MGB-030 transcription/enrichment lifecycle ownership;
- Google Speech-to-Text execution;
- explicit lifecycle convergence;
- authenticated Library, detail, and video playback.

The controlled production Reel converged to:

- `download_status=downloaded`
- `curation_status=inbox`
- `transcription_status=completed`

## Owner-auth authority reconciliation

The production OIDC smoke identified a least-privilege mismatch in the original
F4 PostgreSQL Web-role contract.

The existing owner UPSERT uses:

`ON CONFLICT (provider) DO UPDATE`

and reads the `EXCLUDED.email_normalized` projection.

The production-proven minimal additional authority is therefore:

`SELECT(provider, email_normalized)`

on `app.auth_users` for `megabrain_web`.

Table-wide `SELECT` remains denied.

The canonical F4 runtime grants and verifier now describe this proven contract.
Dedicated forward and rollback artifacts record the operational reconciliation.

## Immutable release preservation

The original immutable release:

`a7eb7aad2da922d65d840523b88c2adcb780fb47`

remains unchanged.

Its original verifier is retained as a historical trust artifact and therefore
reports the expected `EFFECTIVE_COLUMN_ALLOWLIST` drift against the reconciled
production authority.

The reconciled source supersedes that historical allowlist for future F4
reproduction.

## Production evidence

F4.6P-R2 owner-query privilege reconciliation:

`f30e2cb0eeada329be9ba1fc3f207c28b35cae10f8ad4d42f9844ff5cce4951d`

F4.6P owner OIDC production smoke:

`7fe9b3b95d52ba354503d2014602c1391469b693f1960a9276eb4b48936c249e`

F4.6Q controlled Reel end-to-end proof:

`7093dd50b2f14de410f782e15a5aba5aca7a9b4e146c7ea230e28afe188c154b`

## Final runtime authority boundaries

- Web owns authenticated owner-facing operations and curation.
- MGB-020 owns download lifecycle writes.
- MGB-030 owns transcription/enrichment lifecycle writes.
- Categories remain independent from lifecycle ownership.
- MGB-001/Telegram remains outside the Web ingestion path.
- No generic lifecycle-status dual-write is reintroduced.
