# F4.2 — Reel Lifecycle Persistence

## Scope

F4.2 replaces the overloaded `app.reels.status` download lifecycle with three
independent persisted dimensions:

| Column | Allowed values | Authority |
| --- | --- | --- |
| `download_status` | `received`, `downloading`, `downloaded`, `failed` | MGB-020 |
| `curation_status` | `inbox`, `organized` | authenticated owner action, introduced by F4.4 |
| `transcription_status` | `not_requested`, `queued`, `processing`, `completed`, `failed` | MGB-030; lifecycle synchronization is deferred to F4.3 |

F4.2 creates persistence and domain foundations only. It does not add a
browser mutation API, transfer processing authority, deploy workflows, or run a
production migration.

## Migration plan

`infra/postgres/migrations/005_f4_reel_lifecycle.sql` is a forward-only,
transactional artifact. Before changing schema it verifies that:

- `app.reels.status` and its known `reels_status_check` exist;
- none of the three new lifecycle columns already exist;
- every legacy row has exactly one approved legacy value.

Unknown or null legacy values raise an exception and roll back rather than being
coerced. The legacy mapping is explicit:

| Legacy `status` | `download_status` |
| --- | --- |
| `received` | `received` |
| `downloading` | `downloading` |
| `downloaded` | `downloaded` |
| `download_failed` | `failed` |

The migration renames the column, removes the legacy constraint, maps only
`download_failed`, adds the two new fields with explicit defaults, then verifies
all three constraints before committing. There is no permanent compatibility
column and no dual-write path.

Existing rows receive `curation_status = 'inbox'` because categories, source,
download state, and enrichment data do not imply manual organization. They
receive `transcription_status = 'not_requested'` because F4.2 must not infer
per-row transcription state from aggregate evidence or claim completed work
without authorized row-level reconciliation. F4.3 owns any later synchronization
with MGB-030.

A future production migration requires its own human authorization and a
coordinated deployment of the versioned MGB-020 and MGB-030 workflow definitions
that read/write `download_status`. F4.2 has not performed either action.

## Domain and authority boundaries

The FastAPI registration model now names the field `download_status`; both Web
and Telegram registration create `received` Reels through the same persistence
path. MGB-020 remains the only download lifecycle writer. MGB-030 now reads
`download_status = 'downloaded'` to preserve its existing eligibility boundary,
but does not write `transcription_status` in F4.2.

`curation_status` and `transcription_status` are database defaults only in this
stage. The browser request schemas accept no lifecycle fields, so neither
`download_status` nor `transcription_status` can be browser-controlled. The
future owner-authorized curation API remains F4.4 work.

Categories remain independent from every lifecycle dimension. F4.2 does not
infer, initialize, or mutate curation based on category assignment.

## Rollback and recovery

The migration is atomic: a preflight or constraint failure rolls back the whole
transaction. Once a separately authorized production migration has committed,
reversal must be a separately reviewed migration that first verifies all
`download_status` values, maps `failed` back to `download_failed`, drops the new
constraints/columns only when no dependent F4.3/F4.4 code exists, and renames
`download_status` back to `status`. That rollback is intentionally not bundled
with the forward migration to avoid a permanent dual semantic owner.
