# F3.2 Source-Neutral Processing Core — Task Contract

## Status

APPROVED_FOR_LOCAL_IMPLEMENTATION

## Objective

Harden the shared Reel processing path so canonical Reel records from Telegram
and future Web registration can be processed without a canonical Telegram
runtime dependency.

## Risk

YELLOW. Production deploy, live n8n changes, production verification, recovery
and rollback remain RED and human-gated.

## Scope In

- backward-compatible Downloader request handling without Telegram metadata;
- explicit safe Downloader failure HTTP responses;
- MGB-020 input normalization, atomic claim, response validation and guarded
  persistence;
- optional nonfatal Telegram notifications sourced only from persisted Reel data;
- local Downloader and workflow-contract tests;
- F3.2 workflow documentation and active-task reconciliation.

## Scope Out

- Web ingestion or a public Add Reel flow;
- MGB-010 and MGB-030 changes;
- production databases, n8n, R2, Docker, deploys and recovery operations;
- FastAPI Web, frontend, Caddy, Compose, CI, migrations, grants and skills.

## Allowed Paths

- docs/TASK_CONTRACT_F3_2_PROCESSING_CORE.md
- docs/ACTIVE_TASK.md
- services/downloader/app/main.py
- services/downloader/tests/test_main.py
- workflows/MGB-020-download-reel.json
- workflows/tests/test_mgb020_contract.py
- workflows/README.md

## Forbidden Paths

- workflows/MGB-010-entrada-reel.json
- workflows/MGB-030-enrichment-reel.json
- services/web/**
- apps/web/**
- infra/postgres/**
- infra/Caddyfile
- infra/docker-compose.yml
- .github/workflows/**
- skills/**
- AGENTS.md
- docs/RISK_POLICY.md
- requirements files, .env files and secret-bearing files.

## Expected Files

The seven paths in Allowed Paths, and no other path.

## Acceptance Criteria

- Downloader canonical request has `item_id`, `shortcode` and `url`; legacy
  extra `telegram_chat_id` is ignored.
- Downloader success and failure payloads contain no Telegram metadata.
- Download acquisition failures are safe non-2xx envelopes; authentication and
  validation behavior remain 401 and 422 respectively.
- MGB-020 accepts canonical `reel_id` and temporary legacy `id` only.
- One statement atomically claims only `received` and `download_failed`; an
  unclaimed execution stops and never starts Downloader.
- Claim identity controls all later writes and correlation checks.
- Downloader success is validated before guarded `downloaded` persistence.
- Acquisition failures use bounded fixed messages and guarded
  `download_failed` persistence.
- Telegram is an optional nonfatal adapter; MGB-030 follows successful
  downloaded persistence directly.

## Required Tests

- `python -m unittest discover -s services/downloader/tests -p 'test_*.py' -v`
- `python -m unittest discover -s workflows/tests -p 'test_*.py' -v`
- repository workflow JSON validation from CI convention;
- `git diff --check` and exact allowed-path / forbidden-diff verification.

## Security Invariants

- No secrets, production configuration, live service, R2, Docker or database
  access.
- HTTP failure envelopes never expose raw exceptions, credentials, paths,
  headers or upstream bodies.
- MGB-020 never trusts Downloader identity for SQL targets or notification
  destinations.
- Error persistence uses only fixed, bounded allowlisted messages.
- Telegram destination is read only from claimed or persisted `app.reels` data.

## Runtime Compatibility

The new Downloader accepts old MGB-020 payloads because Pydantic v2 ignores
extra fields. The new MGB-020 sends only canonical media fields and remains
compatible with MGB-010 through temporary `id` input support. `telegram_chat_id`
may be NULL for future source-neutral records.

## Deployment Order

Prepare only; do not execute:

1. deploy the backward-compatible hardened Downloader;
2. verify health;
3. human-import, review and activate new MGB-020;
4. run Telegram regression;
5. run NULL-Telegram source-neutral regression;
6. confirm MGB-030 follows successful downloaded persistence.

## Rollback / Recovery

After MGB-020 changes, restore prior MGB-020 before rolling back Downloader,
because the new workflow sends no `telegram_chat_id` and the old Downloader
requires it. Do not manually reset `downloading` Reels as routine rollback.
Stuck production-state recovery requires separate human approval.

## Human Gates

Human/Product Owner approval is required for any production Downloader deploy,
health verification, n8n import/review/activation, production regression,
recovery or rollback. Local evidence does not authorize production rollout.

## Publication and Merge Authority

Publication: NONE. Push, pull request, merge and deployment are not authorized.
Merge remains human-only.
