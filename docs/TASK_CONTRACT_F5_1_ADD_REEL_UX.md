# Task Contract — F5.1: Add Reel UX

## Status

- Status: QA
- Risk Level: YELLOW

## Objective

Reconcile the F5.1 Add Reel UX candidate with its governance findings and locally remediate the frontend response boundary, dialog accessibility, and interactive test coverage without changing backend authority or any runtime infrastructure.

## User / Product Context

An authenticated owner needs a bounded UI entry point to submit a public Instagram Reel URL through the existing FastAPI ingestion contract. The initial implementation preceded this formal Task Contract and was authorized by `AUTORIZO_F5_1_ADD_REEL_UX_IMPLEMENTATION`; H1 subsequently recorded `VERDICT=BLOCKED`. This H2 round is authorized by `AUTORIZO_F5_1_H2_GOVERNANCE_AND_REMEDIATION` to reconcile governance and findings.

## Scope

### In

- Record the F5.1 Task Contract and reconcile the active-task record.
- Strictly validate the existing `POST /api/reels` success payload at the Next.js client boundary, including exact response shape, HTTP status, dispatch state, and lifecycle constraints.
- Improve the existing native Add Reel dialog's bounded error and pending accessibility behavior.
- Replace source-string UI evidence with interactive Node test + React DOM + jsdom coverage.
- Add only the exact jsdom development dependencies required for those DOM tests.

### Out

- FastAPI, backend API behavior, workflows, database, R2, Caddy, Compose, and production runtime changes.
- Merge into `dev` or `main`; merge is a separate human gate.
- Production deployment, production validation, or any production operation; deployment is a separate Red gate.
- Staging validation: staging does not exist.
- H2 CI, H3 review, or any claim that either has occurred.

## Acceptance Criteria

- `docs/TASK_CONTRACT_F5_1_ADD_REEL_UX.md` follows every canonical Task Contract section and records the actual F5.1/H1/H2 governance context.
- `docs/ACTIVE_TASK.md` identifies F4 production cutover as closed and F5.1 as the active Draft PR #44 candidate under H2 remediation/QA, unmerged and undeployed.
- The client accepts only exact allowed top-level, reel, and dispatch response keys; it rejects malformed, unknown, lifecycle-incompatible, dispatch-incompatible, and HTTP-status-incompatible success payloads.
- A new Reel is accepted only for `201`, `created=true`, `accepted` or `unconfirmed`, and `received` / `inbox` / `not_requested` lifecycle values.
- An existing Reel is accepted only for `200`, `created=false`, all three known dispatch states, and known lifecycle enums.
- The dialog exposes an inline stable error ID, error-only `aria-invalid` and `aria-describedby` association, and focuses the enabled input after an asynchronous error.
- Pending controls remain disabled, cancellation/Escape remain blocked, and pending is released through `try`/`catch`/`finally` with a bounded error code.
- Interactive DOM tests cover dialog opening, pending POST behavior, disabled controls, pending cancellation/Escape blocking, new/existing success, error semantics/focus, and reset after close.

## Architecture / Technical Plan

FastAPI remains the registration, normalization, deduplication, lifecycle, and dispatch authority. The client validates only the documented projection it receives before rendering it. The client component remains a Client Component because it owns local native-dialog, form, focus, and pending interaction state; it does not persist CSRF or session data. jsdom is used only in Node tests with React DOM and explicit browser-global cleanup.

## UX Specification Reference

- `docs/F5_1_ADD_REEL_UX.md`
- `docs/UI_SYSTEM.md` accessibility baseline

## Contracts Changed

No backend contract is changed. The frontend client now enforces the existing success-response projection more strictly:

- exact top-level keys: `reel`, `dispatch`;
- exact Reel keys: `id`, `shortcode`, `original_url`, `download_status`, `curation_status`, `transcription_status`, `created`;
- exact dispatch keys: `state`.

## Data / Migration Impact

N/A. No schema, data, migration, database, or persistence change is in scope.

## Security Impact

The existing owner session and CSRF flow remain intact. The browser obtains CSRF through `GET /api/auth/csrf`, sends it only in `X-CSRF-Token`, and does not write token or session data to browser storage. Strict response validation fails closed on unknown shapes and incompatible state combinations. No production secret, capability, or security boundary is changed.

## Expected Files / Components

- `docs/TASK_CONTRACT_F5_1_ADD_REEL_UX.md`
- `docs/ACTIVE_TASK.md`
- `apps/web/src/lib/reel-creation-api.ts`
- `apps/web/src/components/add-reel.tsx`
- `apps/web/tests/reel-creation.test.ts`
- `apps/web/package.json`
- `apps/web/package-lock.json`

## Required Tests

- `cd apps/web && npm test`
- `cd apps/web && npm run lint`
- `cd apps/web && npm run typecheck`
- `cd apps/web && npm run build`
- `git diff --check`

## Required Evidence

- Interactive React DOM + jsdom test output for the Add Reel dialog's pending, success, error, focus, and reset behavior.
- Unit-boundary test output for exact response keys and semantic state/status validation.
- Diff and allowed-path inspection showing no backend, workflow, infrastructure, or production change.

## Staging Requirements

N/A. Staging does not exist.

## Production Impact

No production impact is authorized or executed. Backend/workflow/database/R2/Caddy/Compose/production changes are out of scope. Any production deployment or operation remains Red and requires separate explicit human authorization; this contract grants no production authority.

## Rollback / Recovery

Revert this frontend/docs/dependency-only candidate from its feature branch before merge if QA identifies a regression. No migration, persistent data repair, or production rollback applies.

## Human Gates

- H2 remediation is authorized by `AUTORIZO_F5_1_H2_GOVERNANCE_AND_REMEDIATION` only within this local scope.
- Merge to `dev` remains a separate human gate.
- Production/deployment remains a separate Red human gate requiring explicit authorization.
- This contract grants neither merge nor production authority.

## Dependencies

- Existing FastAPI `POST /api/reels` and CSRF contracts.
- React 19 and React DOM already used by `apps/web`.
- Exact dev dependencies: `jsdom` and `@types/jsdom` for local interactive DOM tests.

## Open Questions

- Independent QA/reviewer decision remains pending after this remediation round.
- CI observation, merge, staging, deployment, and production evidence are outside this round.

## Final Evidence Summary

Current-round local evidence only: the new interactive DOM tests and strict response-boundary tests were added, and `cd apps/web && npm test` completed with 48 passing tests and 0 failures. This is local validation only; no H2 CI or H3 review is claimed. The task remains `QA`, unmerged, undeployed, and subject to the listed human gates.
