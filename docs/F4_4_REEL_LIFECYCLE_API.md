# F4.4 — Reel Lifecycle Read API and Owner Curation

## Scope and operational boundary

F4.4 exposes the persisted Reel lifecycle dimensions through authenticated
browser APIs and adds the only browser-authorized lifecycle mutation. This is
repository code only. It does not execute migration
`infra/postgres/migrations/005_f4_reel_lifecycle.sql`, deploy services, restart
containers, mutate PostgreSQL, or import, activate, or modify n8n workflows.

## Browser authority table

| Field | Read | Browser write | Authority |
| --- | --- | --- | --- |
| `download_status` | Yes | No | MGB-020 |
| `transcription_status` | Yes | No | MGB-030 |
| `curation_status` | Yes | Yes — authenticated owner plus CSRF | authenticated owner |

`transcription_attempt_id`, workflow identifiers, Telegram identifiers, internal
errors, and storage configuration are not browser projections.

## Read contracts

Authenticated `GET /api/reels` library records and authenticated
`GET /api/reels/{reel_id}` detail records each expose the independent:

- `download_status`
- `curation_status`
- `transcription_status`

There is no generic lifecycle `status` compatibility alias in these browser
contracts. The registration response returns the same three explicit lifecycle
fields for its registered Reel projection. This does not authorize caller input:
registration remains strict and rejects lifecycle fields.

## Curation mutation contract

`PATCH /api/reels/{reel_id}/curation` accepts exactly this JSON contract:

```json
{"curation_status":"organized"}
```

The allowed values are `inbox` and `organized`. The endpoint is idempotent:
setting the current state returns the same bounded lifecycle projection. A
successful response includes only:

```json
{
  "id": 42,
  "download_status": "downloaded",
  "curation_status": "organized",
  "transcription_status": "completed"
}
```

The endpoint requires the existing owner session and the existing same-origin
API CSRF contract: the opaque `__Host-csrf_token` cookie must match the
`X-CSRF-Token` request header. Anonymous requests are denied before lifecycle
work. A missing or invalid CSRF token is denied before the Reel lookup. An
unknown Reel uses the existing `404 Reel not found` contract after owner and
CSRF gates.

MegaBrain is a single-owner application: `auth_users` has the persisted
single-owner uniqueness invariant and its session resolver only resolves that
owner identity. F4.4 therefore reuses the established owner-session boundary;
it does not add a per-Reel ownership table or a second identity system.

The repository mutation is a parameterized targeted `UPDATE` that writes only
`curation_status` and returns the explicit lifecycle projection. It does not
write `download_status`, `transcription_status`, `transcription_attempt_id`, or
categories. It has no source predicate, so Telegram-created and web-created
Reels have identical curation semantics. The curation and category JSON models
forbid unknown fields, so lifecycle fields cannot be smuggled through either
browser mutation route.

## Independence and presentation boundary

Category assignment and removal remain independent from curation. Curation does
not add, remove, or require categories, and category operations do not organize
a Reel. Curation also has no download or transcription side effect.

F4.5 owns final lifecycle presentation and interactive UI. F4.4 only aligns
backend and frontend contract types required for these API fields; it does not
add the final visual lifecycle experience.
