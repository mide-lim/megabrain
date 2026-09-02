# Technical Specification — B1/B2 Engineering Automation Architecture

## Objective

Define an implementation-ready, non-deployed target for B2 that enables deterministic validation of `agent/*` commits without granting CI, Hermes, or agent-generated code access to production Docker, production secrets, production network paths, protected branches, merge, or deployment. This specification follows the B1 discovery recommendation; B2 remains unapproved until human review.

## Known context and assumptions

- The current source remote is a local bare repository at `/srv/git/megabrain.git`; bundle/review/manual integration is the current handoff.
- CI, staging, Playwright, and automated promotion are absent today.
- The production VPS runs Caddy, n8n, PostgreSQL, downloader, enricher, and Web. Only Caddy publishes host ports in the tracked Compose configuration.
- Production `.env`, `infra/data/`, Docker daemon, runtime database, and production workspace are out of agent scope.
- The recommended future provider is a private hosted Git repository with provider-hosted ephemeral CI workers. Provider identity, account, plan, and migration approval are UNKNOWN and human-gated.
- No numerical production VPS capacity evidence is available; B2 must not allocate CI workload to it.

## Scope

### In

- A controlled migration or one-way mirror plan to an approved private hosted engineering repository.
- Least-privilege agent branch write, protected integration branches, and human review.
- Managed ephemeral CI for deterministic unit, lint (when configured), integration, build, security, and documentation checks.
- Versioned `evidence.json`, bounded logs, and short-retention internal artifacts.
- A future isolated Playwright job design and future separate staging boundary.
- Limits, cleanup, failure handling, rollback/removal, validation, and human gates.

### Out

- Installing any Git service, runner, CI workflow, Playwright dependency, browser, staging environment, or artifact store.
- Changing local bare Git permissions, `infra/docker-compose.yml`, Caddy, Docker, application code, runtime infrastructure, secrets, databases, or production.
- Push, merge, deployment, automatic promotion, and production access.

## Affected components and target architecture

```text
[Hermes restricted Git principal]
  write: refs/heads/agent/* only
                  |
                  v
[Private hosted engineering Git repository]
  protected: dev/main; human-only review/merge
                  |
                  v
[Provider-hosted ephemeral CI worker]
  immutable SHA; no production socket/private network/secrets
                  |
                  +--> concise evidence.json + bounded internal artifacts
                  |
                  v
[Human review]
                  |
                  +--> future separate staging, when approved
                  |
                  v
[Human production gate]
                  |
                  v
[Existing production VPS — never a CI runner]
```

### Component responsibilities

| Component | Responsibility | Explicitly not allowed |
| --- | --- | --- |
| Hermes Git principal | Write only its own `agent/*` branch commits after provider ACL capability is verified; otherwise use an approved ingress/gateway | Protected branches/tags/settings, secrets, review, merge, deploy |
| Hosted Git control plane | Repository ACLs, branch protection, PR review state, CI status, artifact access | Production control plane |
| Ephemeral CI worker | Validate exactly one SHA in a disposable workspace | Production socket, deployment credentials, production/staging secrets, private production-network access, or production test traffic |
| Evidence producer | Emit schema-validated evidence from command exits | Set `ready` from log text or promote a commit |
| Human reviewer | Evaluate exact commit, evidence, artifacts, diff, risk, and contract | Treat CI pass as production authorization |
| Future staging | Isolated non-production integration/E2E target | Production credentials/data/runtime reuse |
| Production | Human-operated runtime | CI execution, runner storage, browser execution |

## Git flow and permissions

1. Product Owner approves a B2 source-of-truth transition before any remote change.
2. Human owner creates/configures the private hosted repository and protected `dev`/`main` policy.
3. Human owner first verifies the provider can enforce a repository- and `refs/heads/agent/*`-prefix-scoped principal, including tag denial. Only then may it create a dedicated Hermes principal with that scope; it has no administration, CI-secret, merge, or deployment permission. Protected-branch rules alone do not prove the prefix constraint. If the provider lacks it, B2 stops direct write and selects an approved untrusted-ingress repository or narrowly reviewed branch-write gateway.
4. Hermes pushes a commit to its allowed agent branch. The CI trigger records the full commit SHA and workflow revision.
5. Managed CI reports validation for that immutable SHA and publishes `evidence.json` plus permitted artifacts.
6. A human opens/reviews or approves the integration change according to the protected-branch policy. CI pass is necessary evidence, not merge authority.
7. Human merge/promotion occurs only through protected integration controls. Staging and production remain separate gates.

During transition, B2 must select exactly one authoritative source:

- Preferred: private hosted repository becomes engineering source of truth; old local bare repository is retained read-only as archive until removal is approved.
- Fallback: the existing bare repository remains authoritative and a separately specified one-way mirror/bridge is built. The bridge must be reviewed as a security-sensitive component and must not create two writable sources.

## Execution and CI job lifecycle

1. **Admission:** accept only an approved repository event for an `agent/*` SHA. Cancel or supersede outdated runs for the same branch.
2. **Isolated checkout:** create a disposable workspace for the pinned SHA. Use a read-only, minimum-scope repository token.
3. **Validation:** run explicit deterministic commands selected from the repository manifest. Initially, this includes documentation checks and the existing Python test paths; lint/security checks must report `not-run` with a reason until configured rather than pretending to pass.
4. **Build/integration:** when B2 adds it, use the worker's disposable build environment. Never bind the VPS Docker socket, production Compose files, production environment file, or `infra/data/`.
5. **Evidence:** collect exit statuses, durations, command identifiers, and artifact manifest; generate schema-versioned JSON without parsing human-oriented logs.
6. **Publication:** upload only approved artifacts with digest, sensitivity, size, and retention metadata. Publish a small job status that links to evidence rather than copying large logs into review.
7. **Cleanup:** always delete workspace/temp credentials, cancel child processes on timeout, prune job-local artifacts per provider policy, and retain only the declared artifact set.
8. **Review handoff:** CI status binds to the SHA; reviewer compares the Task Contract, SDD, diff, and evidence for the same SHA.

## Isolation mechanism and security controls

- Use provider-hosted ephemeral workers for all untrusted branch validation. No self-hosted runner is permitted on the production VPS.
- Do not mount or forward `/var/run/docker.sock`; do not add CI identities to the production Docker group; do not run a runner in the production Compose project.
- CI receives no production credentials, SSH key, Docker registry credential capable of publishing runtime images, Caddy credential, database credential, R2 credential, or `.env`. It has no private production route and must not target public production endpoints; B2 must determine and verify an enforceable destination block rather than assuming general internet egress cannot reach a public endpoint.
- Agent-branch workflows use read-only tokens and cannot access protected environments. Any later deployment/staging token is available only in a separate protected workflow after review and the relevant human gate.
- Pin/review third-party actions and package sources; record action/runtime image revisions in evidence where the provider supports it.
- Permit only required egress for source/dependency retrieval and artifact publication; staging egress is disabled until staging is explicitly introduced.
- Enforce one concurrent run initially, provider job timeout, artifact maximum size, artifact retention, cache budget, and cancellation of obsolete runs.
- Redact secrets from logs; treat screenshots/traces/reports as internal and short-retention because they can carry source or credentials.

## Contracts

### Evidence contract

The authoritative CI handoff is `evidence.json` with a versioned schema. Required top-level fields are `schema_version`, `task_id`, `repository`, `commit`, `ref`, `risk`, `run`, `checks`, `artifacts`, `policy`, and `ready`.

Each `checks[]` entry has `name`, `status` (`pass`, `fail`, `skipped`, `cancelled`, `not-run`), `required`, and either `summary` or `reason`. `ready` is true only when every required check passed, the recorded policy permits readiness, and all corresponding data refer to the same immutable SHA. It is never a merge, staging, deployment, or production-approval flag.

Each artifact declaration has `name`, provider URI or identifier, SHA-256 digest, size, retention period, and sensitivity classification. Logs are referenced, not embedded. Schema validation failure makes the run fail.

### Git/review contract

- Agent credential: repository- and branch-namespace-scoped only after B2 proves provider enforcement; no protected-ref/tag/settings write. If that enforcement is unavailable, no direct credential is issued and the approved ingress/gateway becomes the contract.
- CI token: read-only checkout/status/artifact permissions necessary for the provider; no merge/deploy/admin.
- Reviewer: human approval on protected integration branch and recorded review of the evidence SHA.
- Production: explicit Product Owner authorization per `docs/RISK_POLICY.md`; no CI success can satisfy it.

## Data and migration impact

N/A for B1 documentation. B2 should not access, copy, restore, or mutate production PostgreSQL/R2/n8n data. A later staging design must define synthetic/fixture data and any approved sanitization/reset procedure before E2E tests exist.

## Playwright placement

A later Playwright job runs on a hosted ephemeral worker or a separate non-production runner. It uses an isolated fixture app or separate staging environment, non-production account, no personal browser profile, and no production URL/credentials/data. It executes headless with a bounded timeout and concurrency; failure artifacts are restricted, redacted where feasible, and short-retention. The initial suite should cover only approved critical regression paths after a separate task chooses fixtures and staging. Browser Harness/agent tooling is exploratory QA only, not a deterministic gate.

## Future staging placement

Staging is a separately provisioned non-production environment with its own network endpoints, credentials, database/storage, observability, lifecycle, and cleanup. It must not share the production Compose project, Docker daemon, runtime database, R2 credentials, or host path. B2 does not create it. A later Yellow/Red contract specifies which checks require staging and the human gate before staging deployment.

## Failure handling, logging, and observability

- A failed/cancelled/timeout/schema-invalid run sets `ready: false`, preserves only permitted failure artifacts, and reports the exact SHA/check identifier.
- Missing evidence, mismatched SHA, unavailable artifact, or failed digest is a validation failure, not a pass with a warning.
- Provider outage/quota exhaustion is `not-run`/failed according to the check policy; it cannot be replaced by an assertion that CI passed.
- Logs are structured around run ID, SHA, check name, exit status, duration, and artifact ID; omit secret values and request payloads.
- Initial observability is provider run status, evidence artifact availability, artifact retention usage, job duration/timeout count, cancellation count, and monthly minutes/storage spending. Define alert thresholds before enabling branch automation.

## Dependencies

- Product Owner decision on hosted source-of-truth migration versus a separately specified bare-Git bridge.
- Approved private hosted Git/CI provider account, billing limit, repository privacy, and access model.
- Hosted workflow syntax/action-version policy and a provider-supported artifact mechanism.
- Existing Python requirements/test commands; B2 must discover actual commands before encoding them.
- Future separate staging and Playwright task contracts.

## UX handoff

N/A. This task adds no user interface. Future browser regression follows `docs/UI_SYSTEM.md` and requires a separate UX/product task when it changes user-visible behavior.

## Acceptance criteria and Definition of Done

### B1 documentation acceptance criteria

- Discovery compares Options A–D across the requested security, operations, cost, Git, runner, secret, Docker, Playwright, artifact/log, staging, resource, failure, and removal dimensions.
- Discovery explicitly rejects CI-to-production-Docker-socket exposure and selects one target direction with alternatives/reasons.
- SDD defines trust boundaries, component responsibilities, Git and execution flow, evidence/artifact lifecycle, failure/cleanup, limits, security controls, observability, dependencies, validation, rollback/removal, risk, and human gates.
- Task Contract records B1 evidence and reaches `READY` only after independent review passes.
- Documentation distinguishes verified current capability from future/unknown capability and exposes no secrets.
- Only documentation/task-contract files change; `git diff --check` passes.

### B2 implementation acceptance criteria (not evidence for B1)

- Human-approved authoritative-source migration/bridge and a provider-proven branch-prefix-restricted Hermes credential (or approved ingress/gateway) are demonstrated without protected-ref/tag write.
- A provider-hosted ephemeral job validates one immutable agent SHA without production Docker, secrets, workspace, private-network access, or production test traffic; the public-endpoint blocking posture is verified and recorded.
- CI outputs schema-validated evidence tied to that SHA; required check failures/not-runs make readiness false.
- Resource/cost/artifact limits and cleanup are enforced and testable.
- A human protected-branch review is required; CI cannot merge/deploy.
- Staging/Playwright are absent unless separately approved and satisfy their own contract.

## Required validation strategy

For B1, validate only the actual documentation delivery: inspect permitted file scope, scan the diff for secret-like additions, run `git diff --check`, review status/diff, and obtain an independent review against the B1 task requirements, contract, discovery, SDD, and evidence. Application tests and CI runs are not required because B1 does not change application/runtime code and no CI exists.

For B2, use an approved disposable test repository/branch to prove permission denial for protected refs, absence of production credentials/socket/mounts, evidence schema validation, required-check semantics, timeout/cancellation, artifact retention, and manual review gate. Do not use production as a test target.

## Implementation sequence for B2 (unapproved)

1. Human approves provider, cost ceiling, source authority, and B2 Task Contract risk/gates.
2. Create a private hosted repository and protected branches, or approve a separately reviewed one-way bridge; retain only one writable authority. Verify whether the provider enforces a Git ref-prefix/tag allowlist before designing agent access.
3. Create/revoke-test the branch-restricted Hermes credential only when provider enforcement is proven; otherwise implement/review the approved ingress/gateway. Document rotation and incident response.
4. Add a minimal hosted CI workflow for deterministic repository checks only, with read-only tokens, timeout/concurrency/artifact caps, no secrets, and `evidence.json` schema validation.
5. Verify isolation in a disposable branch, including intentional protected-ref denial and proof that no production Docker/socket/environment is visible.
6. Add existing unit tests and deterministic build/integration checks incrementally; record absent lint/security checks as not configured until they are actually added.
7. Add protected review/status requirements and validate the review/merge separation.
8. In a later approved task, create separate staging and then limited Playwright regression jobs.
9. Review resource/cost/error evidence after a bounded pilot before widening agent-branch use.

## Rollback/removal strategy

Before merge/deployment, disabling the CI workflow, revoking the Hermes credential, disabling repository write, and removing status requirements returns to the documented manual bundle/review path without touching production. If a hosted-source migration is aborted, maintain only the previously designated source of truth and delete/revoke the unused mirror credentials. A suspected CI compromise requires disabling workflow triggers, revoking CI/agent tokens, preserving minimal forensic evidence, reviewing branch history, and human approval before re-enablement. No rollback action may operate production containers, data, or secrets from CI.

## Technical risks

| Risk | Mitigation |
| --- | --- |
| Agent code attempts host/container escape | Hosted ephemeral workers; no production runner/socket/network/secrets; no privileged jobs |
| Hosted source/CI account compromise | Least privilege, MFA/human ownership, protected branches, scoped/rotated credentials, audit review |
| Unbounded spend/artifact growth | Concurrency, timeout, artifact/cache/retention caps and monthly review |
| Workflow/supply-chain compromise | Read-only untrusted jobs, pin/review actions, lock dependencies where available, no protected secrets |
| False confidence from incomplete evidence | SHA-bound schema, explicit not-run/skipped semantics, reviewer checks exact evidence |
| Migration creates two writable sources | One-authority decision and human-approved cutover/rollback plan |
| Provider cannot enforce agent ref-prefix scope | Prove capability before credential issuance; otherwise no direct write and use a separately approved ingress/gateway |
| Future E2E leaks data or touches production | Separate staging/fixtures/accounts; restricted short-retention artifacts; no production credentials |

## Risk classification and human gates

- **B1 risk: GREEN.** Documentation/discovery/specification only; no runtime, permission, secret, or production action is performed.
- **B2 baseline risk: YELLOW.** It introduces CI configuration, credentials, branch/write pathways, and external provider integration. Any change to production infrastructure, Docker permissions, network exposure, production secrets, source-of-truth authority, or deployment is reclassified as RED and requires explicit Product Owner approval before execution.
- **Human gates:** approve recommended direction/provider/cost/source authority before B2; approve branch protections and credential scopes; review B2 security/validation evidence before enabling broader use; approve staging separately; approve every production promotion/action explicitly.

## Open questions

1. Which provider/account/region and billing cap are acceptable?
2. Is hosted private Git approved as source of truth, or must B2 design the separate-host bare-Git bridge instead?
3. Which existing Python commands and integration build strategy should be encoded after B2 repository inspection?
4. Who is the named owner for protected branch reviews, credential rotation, provider billing, and incident response?
5. What is the separate staging environment and fixture-data model for the first Playwright task?
