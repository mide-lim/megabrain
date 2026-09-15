# F4.3 — Reel Lifecycle Authority Synchronization

## Scope and deployment boundary

F4.3 connects the F4.2 persisted lifecycle dimensions to their runtime owners
in the versioned repository only. It does not execute migration
`005_f4_reel_lifecycle.sql`, import or activate n8n workflows, deploy services,
or write production lifecycle values.

Because migration 005 has not been deployed, F4.3 amends that forward migration
rather than creating a later migration. The amendment adds the current
transcription attempt identity needed to make lifecycle projection updates safe;
it does not create a compatibility column or a permanent dual-write path.

## State ownership

| Field | Authoritative writer | Initializer | Readers |
| --- | --- | --- | --- |
| `download_status` | MGB-020 only | registration (`received`) | MGB-030 eligibility, FastAPI/Web, frontend, Telegram notifications |
| `transcription_status` | MGB-030 lifecycle path only | registration/database default (`not_requested`) | FastAPI/Web, frontend, MGB-030 eligibility and attempt history |
| `curation_status` | future F4.4 authenticated owner-only API | registration/database default (`inbox`) | FastAPI/Web and frontend |

Registration initializes lifecycle defaults only. Browser request schemas do not
accept `download_status`, `transcription_status`, or `curation_status`.
Category operations do not write a lifecycle field. The frontend remains a
reader. F4.3 adds no curation mutation and no automatic `inbox -> organized`
transition.

## Download lifecycle — MGB-020

```text
registration
  -> received
       |
       | MGB-020 atomic claim
       v
downloading
  |              |
  | success      | failure
  v              v
downloaded      failed
                    |
                    | explicit existing redispatch/retry
                    v
                 downloading
```

MGB-020 atomically claims only `received` and `failed` Reels, then writes
`downloading`. Its success and failure writes each require the same Reel to
still be `downloading`; duplicate or stale callbacks therefore cannot change a
completed or newer lifecycle. `download_failed` is no longer emitted by runtime
code or workflow exports. It remains only in the unapplied migration's legacy
input mapping and in historical F4.2 documentation/tests required to transform
pre-F4 rows.

The existing retry contract is preserved: retrying a failed Reel redispatches
MGB-020, which performs `failed -> downloading`; registration itself does not
re-register or silently transition a Reel.

## Transcription lifecycle — MGB-030

```text
not_requested -- MGB-030 accepted dispatch --> queued
failed        -- approved retry dispatch ----> queued
queued        -- atomic attempt creation ----> processing
processing    -- accepted outcome ------------> completed
processing    -- current attempt failure -----> failed
```

MGB-020 writes `downloaded` before it invokes MGB-030 and never writes a
transcription lifecycle field. MGB-030 owns `queued` at the first lifecycle
synchronization query after its workflow invocation has entered the eligible
path. This is the narrowest reliable queue boundary in the current topology:
a successful MGB-030 delivery can queue work, while a failure to start MGB-030
leaves transcription `not_requested` (or its prior terminal state) rather than
claiming a queue that was never accepted.

MGB-030 atomically advances `queued -> processing` while inserting the
processing attempt. The same statement records the generated attempt UUID in
`app.reels.transcription_attempt_id`. Migration 005 enforces that a Reel has a
non-null current attempt identity exactly while its lifecycle is `processing`,
and the composite foreign key binds that UUID to the same Reel's enrichment
attempt.

A valid MGB-030 response with any existing accepted enrichment outcome
(`transcribed`, `no_audio`, or `empty_transcript`) completes the attempt,
persists its detailed result in `app.reel_enrichments`, then projects
`transcription_status = completed`. These are all terminally successful
processing outcomes; the outcome detail remains in `reel_enrichments`, so F4.3
creates no additional Reel-level status values.

A normalized MGB-030 failure first transitions its attempt from `processing` to
`failed`, then projects `transcription_status = failed` only when that exact
attempt UUID is still the Reel's active lifecycle identity. A retry must pass
the existing retry-of failed-attempt eligibility checks and moves through
`failed -> queued -> processing` again.

## Concurrency and idempotency rule

`transcription_attempt_id` is the current lifecycle event token. MGB-030's
completion and failure SQL require both `transcription_status = processing` and
that token to match the attempt being finalized. Repeated terminal callbacks
become no-ops after the attempt is terminal. An old attempt can record only its
own history/result according to existing attempt constraints; it cannot regress
a Reel that a newer current attempt has completed, failed, or is processing.

The queue update accepts only `not_requested` or `failed`, requires no current
attempt token, and rejects Reels that already have an applicable enrichment
result. The processing update and attempt insert are one statement. This
prevents duplicate delivery from creating a second current lifecycle event and
prevents a failed attempt insert from leaving a Reel falsely marked
`processing`.

## Download-to-transcription handoff

1. MGB-020 guarded persistence sets `download_status = downloaded` first.
2. It then invokes MGB-030. On MGB-030's eligible accepted path, MGB-030 sets
   `transcription_status = queued`, then atomically creates the processing
   attempt and sets `processing`.
3. If the MGB-030 dispatch/invocation does not start, the successful download is
   never rolled back. No false queue is written; transcription remains its prior
   state. A later explicit eligible MGB-030 dispatch may advance it.

The dimensions remain independent: `downloaded` combined with
`not_requested`, `queued`, `processing`, `completed`, or `failed` is valid.
Download completion alone never claims transcription completion, and curation
is not encoded in either processing dimension.

## Historical execution truth

`app.reel_enrichment_attempts` remains the detailed execution source of truth,
and `app.reel_enrichments` remains the result/outcome source of truth.
`app.reels.transcription_status` is a guarded lifecycle projection, not a
replacement for either table. F4.3 does not infer lifecycle terminal state from
arbitrary historical rows and does not reconcile existing F4.2 defaults.
