# F6 Incident I1-B — Legacy Lifecycle Compatibility

## Symptom and investigation

A historical Reel can already have an accepted enrichment while its F4 lifecycle
projection remains `not_requested` or `queued`. Before I1-B, the Web request
endpoint could accept `not_requested` or `failed` and persist `queued`; MGB-030
then correctly refused its claim because an accepted enrichment already existed
for the same immutable input. That left the Reel queued without work that MGB-030
was permitted to claim.

The investigation confirmed F4 projection drift, not an MGB-030 failure.
Migration 005 intentionally initialized legacy transcription lifecycle values
conservatively and did not reconcile historical enrichment evidence. MGB-030's
exact applicable-enrichment guard remains correct and is unchanged.

## Applicable enrichment identity

An enrichment is applicable only when all four values match the current Reel and
current I1-B pipeline:

```text
reel_enrichments.reel_id = reels.id
reel_enrichments.source_object_key = reels.object_key
reel_enrichments.source_sha256 = reels.sha256
reel_enrichments.pipeline_version = sprint-3-v1
```

This is an exact source tuple. It does not use shortcode, Reel ID alone, a latest
result approximation, outcome-only matching, or fuzzy source matching.

## Migration 006

`infra/postgres/migrations/006_f6_i1_b_legacy_transcription_reconciliation.sql`
is a forward, transactional, schema-preconditioned data migration. It selects
only downloaded Reels whose transcription status is `not_requested` or `queued`,
whose `transcription_attempt_id` is NULL, and for which an applicable enrichment
exists according to the exact tuple above.

For those rows only, it sets:

```text
transcription_status = completed
updated_at = NOW()
```

It does not create or rewrite attempts or enrichments, transcript text or
language, source identity, pipeline version, or any terminal evidence. The
predicate excludes already completed rows; after the first reconciliation, the
same rows no longer qualify. A second execution therefore produces zero
lifecycle changes for already reconciled data.

`empty_transcript` is an accepted terminal enrichment outcome. It reconciles to
`completed` under the same tuple rule; it is not converted to `failed`, and the
migration does not predicate on `outcome`.

The production audit's expected candidate count is rollout evidence only, never
mutation selection authority. Migration 006 contains no hard-coded Reel IDs.

## Web prevention and compatibility outcome

`services/web/app/reels.py` declares
`CURRENT_TRANSCRIPTION_PIPELINE_VERSION = "sprint-3-v1"`. The atomic Web queue
transition now includes `NOT EXISTS` for the same applicable-enrichment tuple
and binds the pipeline version as a SQL parameter.

The fallback lifecycle read also evaluates `has_applicable_enrichment` with the
same tuple. When a downloaded Reel has `not_requested` or `failed`, a NULL
attempt identity, and applicable terminal evidence, Web returns the domain
outcome `reconciliation_required` without writing `queued`.

`services/web/app/main.py` maps that outcome to HTTP 409 with the frozen API
error:

```text
code: transcription_lifecycle_reconciliation_required
message: Reel transcription lifecycle requires reconciliation
```

Web remains request authority only: normal downloaded `not_requested|failed`
Reels without an applicable enrichment still transition to `queued` and return
HTTP 202. MGB-030 remains processing authority for
`queued -> processing -> completed|failed`; I1-B does not bypass or weaken it.

## Least-privilege Web authority

The guarded Web query needs three additional column-scoped reads on
`app.reel_enrichments`:

```text
source_object_key
source_sha256
pipeline_version
```

The reviewed F4 Web Reel SELECT allowlist does not include `app.reels.sha256`.
Because PostgreSQL requires SELECT authority for the digest comparison in the
guarded UPDATE and fallback read, the same overlay grants that one additional
column-scoped Reel identity read. `007_i1_b_web_applicable_enrichment_read_grant.sql`
therefore grants only `app.reels.sha256` plus the three enrichment columns to
`megabrain_web`. It grants no table-wide SELECT, attempt access, enrichment
writes, sequence access, schema-wide rights, role membership, or PUBLIC access.

`008_i1_b_web_applicable_enrichment_read_verify.sql` is catalog-only. It proves
the positive identity-read grants, the exact effective Reel and enrichment
SELECT allowlists, and the continued absence of enrichment writes, attempt
access, sequence access, table-wide SELECT, unexpected memberships, and PUBLIC
authority. `009_i1_b_web_applicable_enrichment_read_rollback.sql` is
acknowledgement-gated and revokes exactly the I1-B four-column delta.

## Human-gated production rollout

This repository change is source-only. Production execution remains
human-gated and is not authorized by I1-B implementation approval. The later
order is:

1. apply the additive Web identity-read privilege overlay;
2. run the read-only privilege verifier;
3. deploy the guarded Web request code;
4. execute migration 006 exactly once under separate production authorization;
5. perform the approved read-only reconciliation audit.

That later audit must verify that expected candidates became completed, no
processing attempt was created by reconciliation, no enrichment was rewritten,
healthy completed controls remained unchanged, and no matching legacy divergence
remains.

## I1-C boundary

I1-B does not change language behavior. The known adapter behavior remains
`language_hint NULL -> pt-BR`. I1-C is the separate change for Chirp 3 automatic
language detection when the hint is NULL while preserving explicit language
hints. I1-B does not modify MGB-030, the enricher media path, Google STT, or
related language tests.
