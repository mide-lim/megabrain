# F5.1 — Production Promotion

## Status

PREPARED / PRODUCTION DEPLOYMENT NOT YET AUTHORIZED

F5.1 source implementation and QA are complete and merged into `dev`.

This document records the immutable frontend candidate and defines the
human-gated production promotion boundary.

Creating, reviewing, or merging this documentation does not authorize
production deployment.

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

## Current production baseline

Production remains on the sealed F4 frontend:

`sha256:deb256b6b6b9c622c6d4df9b1afaafc4135fb1381aab055d54753794c15f8c68`

Preparing this F5.1 release did not replace or restart the production frontend.

No database, n8n workflow, Caddy, backend, R2, or production lifecycle mutation
is part of the F5.1 frontend promotion.

## Intended promotion scope

The production change, when separately authorized, is limited to replacing the
`megabrain-frontend` runtime with the immutable F5.1 candidate.

The following components must remain unchanged:

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

## Pre-deployment gate

Before production replacement, the operator must prove:

- immutable release checksums pass;
- candidate image ID matches this document;
- production is still on the expected F4 image;
- production frontend is healthy;
- backend and workflow services are healthy;
- no nonterminal workflow execution is present;
- rollback image is locally available;
- public `/internal` boundaries remain closed.

Failure of any gate stops promotion.

## Production acceptance

After an explicitly authorized deployment, acceptance must include:

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

Production evidence must be sealed independently from the F4 evidence.

## Rollback

The rollback anchor is the currently deployed sealed F4 frontend image:

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

At the time this document is created, gates 1–4 are complete.

Production deployment has not occurred and is not authorized by this document.
