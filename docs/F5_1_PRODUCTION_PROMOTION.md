# F5.1 — Production Promotion

## Status

DEPLOYED / ACCEPTED / EVIDENCE SEALED

F5.1 source implementation and QA are complete and merged into `dev`.

The immutable frontend candidate was explicitly authorized, deployed and
accepted in production on 2026-09-19.

This document records the completed production promotion, acceptance evidence
and rollback boundary.

This closeout record does not grant authority for any future production
mutation.

## Product change

F5.1 introduces an authenticated owner-facing **Adicionar Reel** flow in the
Next.js application.

The browser:

1. obtains CSRF through the existing authenticated FastAPI boundary;
2. submits a public Instagram Reel URL through `POST /api/reels`;
3. receives the canonical Reel and dispatch result;
4. presents bounded success, existing-Reel, dispatch-unconfirmed, and error
   states.

FastAPI remains the authority for:

- authentication and session;
- CSRF;
- URL validation and normalization;
- Reel registration and deduplication;
- lifecycle initialization;
- internal processing dispatch.

The frontend remains presentation and owner interaction only.

## Source anchor

Canonical source revision:

`de3f59b03826ea23a51b7d07e035904dee653cbe`

This revision contains merged PR #44 and includes the F5.1 implementation,
review remediation, CI compatibility remediation, and merge into `dev`.

## Validation

The canonical Node.js 20.9.0 validation completed successfully against a full
disposable repository snapshot.

Results:

- `npm ci`: PASS;
- frontend tests: 48 passed / 0 failed;
- lint: PASS;
- typecheck: PASS;
- Next.js production build: PASS;
- source worktree remained clean;
- production was not changed.

The frontend image was subsequently built through the repository Dockerfile
using its production Node.js base.

## Immutable candidate

Candidate frontend image:

`sha256:9a8af64f45d6eff9b60a052f08e5043434abb49440eaf47f84b351b99c284c04`

Pinned Node base:

`node@sha256:aadf416b2cdce311a8811ba3f0608a61b77dbf997500e2eafe781b51f6a0b019`

Exported image archive SHA-256:

`6abcbb845b21c7fccfbb7beb75c2716c4ceef3533a67a9443d86ec726cb63fc2`

Local release fingerprint:

`a65d77478c48c5e91f48e60618efe1d514d17147a0ead021a75033e06d17eb92`

Operator release location:

`/home/megabrain/releases/f5.1/de3f59b03826ea23a51b7d07e035904dee653cbe`

The exported image archive is an operational release artifact and is not
committed to Git.

## Current production state

Production runs the immutable F5.1 frontend:

`sha256:9a8af64f45d6eff9b60a052f08e5043434abb49440eaf47f84b351b99c284c04`

The production frontend is running and healthy at source revision:

`de3f59b03826ea23a51b7d07e035904dee653cbe`

The previous sealed F4 frontend remains locally available as the rollback
anchor:

`sha256:deb256b6b6b9c622c6d4df9b1afaafc4135fb1381aab055d54753794c15f8c68`

The runtime promotion did not redeploy or reconfigure PostgreSQL, n8n, Caddy,
FastAPI Web, Downloader, Enricher, or R2 infrastructure. The controlled
acceptance test intentionally created one Reel and its normal pipeline data
through the existing production contracts.

## Promotion scope and result

The explicitly authorized production change was limited to replacing the
`megabrain-frontend` runtime with the immutable F5.1 candidate.

The following components were not redeployed or reconfigured by the frontend
promotion:

- PostgreSQL;
- FastAPI Web;
- n8n;
- MGB-001;
- MGB-010;
- MGB-015;
- MGB-020;
- MGB-030;
- Downloader;
- Enricher;
- Cloudflare R2;
- Caddy routing and TLS.

## Pre-deployment gate — completed

Before production replacement, the operator proved:

- immutable release checksums pass;
- candidate image ID matches this document;
- production is still on the expected F4 image;
- production frontend is healthy;
- backend and workflow services are healthy;
- no nonterminal workflow execution is present;
- rollback image is locally available;
- public `/internal` boundaries remain closed.

Failure of any gate would have stopped promotion.

All pre-deployment checks passed before explicit human deployment authorization.

## Production acceptance — completed

After the explicitly authorized deployment, acceptance included:

- frontend health;
- public login route;
- authenticated Inbox;
- Library;
- Categories;
- Settings;
- Reel Detail;
- owner session continuity;
- CSRF continuity;
- lifecycle read behavior;
- Add Reel dialog;
- one controlled real Reel submission;
- FastAPI registration;
- MGB-015 dispatch;
- MGB-020 download lifecycle;
- MGB-030 enrichment lifecycle;
- zero unintended lifecycle authority changes.

Production acceptance completed successfully.

The controlled real Web submission created:

- Reel ID: `26`;
- shortcode: `DdcX68ZRQun`;
- lifecycle: `downloaded | inbox | failed`;
- source-neutral Web ingestion: PASS;
- R2 object presence and size validation: PASS;
- MGB-015 execution `123`: success;
- MGB-020 execution `124`: success;
- MGB-030 execution `125`: success;
- pre-existing 15 Reel lifecycle hash unchanged: PASS;
- final nonterminal n8n executions: `0`.

The MGB-030 workflow completed successfully, while the enrichment attempt
recorded terminal transcription failure
`STT_SYNC_RECOGNIZE_UNSUPPORTED | transcription | retryable=false`. This is a
known synchronous Speech-to-Text limitation and does not invalidate the F5.1
Add Reel path.

Human UI acceptance also passed for Inbox, Library, Categories, Settings, Reel
Detail and the Add Reel dialog.

## Production evidence

The F5.1 acceptance evidence is sealed independently from the F4 evidence:

`/home/megabrain/backups/f5.1-release/evidence/f5-1-production-acceptance-20260919.txt`

Evidence SHA-256:

`e7dc4b42ddab75f6da1e992afdef0000d3109e1092645aec8964c307d6347d9d`

The sealed evidence must not be appended to or rewritten.

## Rollback

The rollback anchor remains the previously deployed sealed F4 frontend image:

`sha256:deb256b6b6b9c622c6d4df9b1afaafc4135fb1381aab055d54753794c15f8c68`

If the F5.1 frontend fails its production acceptance criteria, rollback is
limited to restoring the previous frontend image/runtime.

F5.1 introduces no schema migration and therefore requires no database rollback.

Rollback execution remains a human-gated production action.

## Human gates

The following actions are distinct gates:

1. source implementation;
2. CI and review;
3. merge into `dev`;
4. immutable release preparation;
5. promotion documentation / PR;
6. production preflight;
7. explicit human deployment authorization;
8. production deployment;
9. production acceptance;
10. evidence sealing and closeout.

Completion of one gate never implies authorization for the next.

Gates 1–10 completed on 2026-09-19, including explicit deployment
authorization, production acceptance and independent evidence sealing.

PR #45 synchronizes this production closeout back into `dev`; merging that PR is
a source-governance action only and does not authorize another production
deployment.

Any future production action remains separately human-gated.
