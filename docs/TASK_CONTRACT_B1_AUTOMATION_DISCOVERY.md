# Task Contract — B1: CI / Automation Architecture Discovery

## Status

- Status: READY
- Risk Level: GREEN

## Objective

Produce an evidence-grounded Discovery and implementation-ready SDD for the safest/simplest future CI and automation direction, without implementing CI, altering production boundaries, or approving B2.

## User / Product Context

MegaBrain is a personal/small-project production system on one VPS. Current branch handoff uses bundles and human integration. The project needs deterministic validation and future browser regression without turning production infrastructure into a CI runner or weakening its human gates.

## Scope

### In

- Read-only discovery of current repository, Git, documentation, Compose/Caddy, Dockerfiles, test structure, and available Git/CI configuration.
- Comparison of external CI, self-hosted forge/runner, custom local runner, and bare-Git plus separate automation.
- Threat model, recommended direction, Git handoff, CI isolation, evidence model, Playwright/staging/resource implications.
- `docs/ENGINEERING_AUTOMATION_DISCOVERY.md` and `docs/ENGINEERING_AUTOMATION_SDD.md`.
- This Task Contract, `docs/ACTIVE_TASK.md`, validation, independent review, and local commit.

### Out

- CI/Git/runner/Playwright/staging installation or configuration.
- Git permission or bare-repository modification.
- Docker/Caddy/Compose/application/runtime/deployment/database/secret/production access.
- Push, merge, bundle, or production action.

## Acceptance Criteria

- Discovery covers the required options and requested decision dimensions.
- Direct production Docker-socket exposure from CI is rejected as an unacceptable default.
- A single recommended future direction is selected, with rejected alternatives and known unknowns.
- SDD describes a buildable future target without claiming it exists today.
- The B1 evidence model distinguishes pass/fail/skipped/not-run and binds results to an immutable commit SHA.
- Future Playwright uses an isolated CI/staging/fixture path, never production/personal browser credentials.
- `ACTIVE_TASK.md` distinguishes B1 completion from B2 and Sprint 5 approval.
- Only documentation/task-contract-related files change; no secrets or runtime/infra/application changes are made.
- Documentation DoD passes: accuracy, concise scope, no contradictory current-state claim, no secret, `git diff --check` clean, independent review PASS.

## Architecture / Technical Plan

Discovery recommends a private hosted engineering Git source with provider-hosted ephemeral CI workers, no production VPS runner, no production Docker socket/secrets/network, provider-proven scoped Hermes `agent/*` writes (or a separately approved ingress/gateway), protected human-reviewed integration branches, SHA-bound machine-readable evidence, and later separate staging/Playwright. `docs/ENGINEERING_AUTOMATION_SDD.md` is the implementation-ready target; B2 must receive human approval before any implementation or source migration.

## UX Specification Reference

N/A. No interface is designed. Future browser regression follows `docs/UI_SYSTEM.md` only after an approved UI/test task.

## Contracts Changed

No runtime API, service, database, template, workflow, or Git contract changed. B1 proposes a future evidence contract only.

## Data / Migration Impact

N/A. No database, runtime data, data migration, or production data access.

## Security Impact

The documents specify future least privilege and reject CI access to production `/var/run/docker.sock`, production secrets, production network paths, and protected refs. No live security control is changed by B1.

## Expected Files / Components

- `docs/TASK_CONTRACT_B1_AUTOMATION_DISCOVERY.md`
- `docs/ENGINEERING_AUTOMATION_DISCOVERY.md`
- `docs/ENGINEERING_AUTOMATION_SDD.md`
- `docs/ACTIVE_TASK.md`

## Required Tests

- Documentation scope inspection.
- `git diff --check`.
- Diff review for secrets, unintended runtime/infra/application changes, and current-vs-future wording.
- Independent review of requirements, contract, discovery, SDD, diff, and collected validation evidence.

## Required Evidence

- Git branch/status before and after changes.
- Read-only inspection of required project context and repository configuration.
- Discovery and SDD documents at the named paths.
- Clean `git diff --check` result.
- Independent reviewer PASS.
- Final inspected diff/file scope and local commit hash.

## Staging Requirements

N/A for B1. A separate staging boundary is a future B2/later task requirement, not a current capability.

## Production Impact

None. B1 is GREEN documentation only. Future CI/staging/production implementation requires its own risk evaluation; production actions remain RED and human-gated.

## Rollback / Recovery

Revert the local documentation commit to return to the previous governance state. This does not affect any runtime system. B2 rollback/removal is specified in the SDD and is not executed here.

## Human Gates

- Product Owner must approve or reject the B1 recommendation before B2 begins.
- Product Owner must approve any B2 source-of-truth/credential/CI-provider decision and all Red production actions.
- Independent reviewer must pass B1 before this contract is READY.

## Dependencies

- Existing governance documents, repository configuration, and official vendor documentation cited in the Discovery.
- No installed CI/provider account/runner/staging dependency is assumed or created.

## Open Questions

- Hosted Git/CI provider, account, cost ceiling, and source-of-truth migration decision.
- Human ownership of protected branch reviews, credential rotation, billing, and incident response.
- Future separate staging/data/Playwright scope.

## Final Evidence Summary

- Required context, infrastructure configuration, Git remote/configuration, Dockerfiles, tracked test layout, and available Git/CI configuration were inspected read-only.
- No existing CI/staging/Playwright workflow/configuration was found; the existing remote is local `/srv/git/megabrain.git` and tracked tests are Python tests under `services/enricher/tests` and `services/web/tests`.
- Discovery and SDD were authored at the expected paths; `ACTIVE_TASK.md` records the Phase B/B1 state.
- Validation before commit: staged `git diff --check` passed; staged scope contains only the four declared `docs/` files; staged secret-pattern scan found no hard-coded credential or private-key pattern.
- Independent review (second pass): PASS with no blocking issue. The reviewer confirmed the public-production endpoint/egress and provider ref-prefix ACL risks remain explicit B2 verification gates. Non-blocking suggestion: capture provider-specific egress-control and public-destination-block evidence before selecting B2.
- Local commit hash and clean post-commit status are recorded in the delivery evidence after the commit is actually created.
