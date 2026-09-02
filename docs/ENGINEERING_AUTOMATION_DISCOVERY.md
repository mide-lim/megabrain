# Engineering Automation Discovery — B1

## Objective

Choose the safest and simplest future CI direction for MegaBrain: reduce manual bundle/test/check cycles while preserving the current production boundary. This is discovery only. It does not install CI, alter Git permissions, create staging, or authorize promotion.

## Current problem

The current repository uses a local bare remote at `/srv/git/megabrain.git`; the tracked worktree is on `agent/engineering-enablement-b1-ci-discovery`, and `origin` is the local bare remote. The documented handoff is still `agent/* -> bundle -> human import -> dev`. CI, staging, Playwright, and autonomous promotion do not currently exist.

The single VPS already hosts production Caddy, n8n, PostgreSQL, downloader, enricher, and Web. Compose exposes only Caddy ports 80/443; runtime services share an internal Docker bridge network. `.gitignore` excludes `.env`, `infra/.env`, and `infra/data/`. Existing service Dockerfiles run the application as UID 10001, but that is application-runtime hardening, not a CI isolation boundary.

Python tests are tracked for `services/enricher` and `services/web`. There is no tracked Python test configuration, Node manifest, CI workflow, or Playwright configuration.

Evidence sources:

- Repository configuration and documentation inspected for this B1 task.
- GitHub documents that private-repository hosted runners consume plan-dependent minutes and storage; cost must therefore be checked before adoption. https://docs.github.com/en/actions/learn-github-actions/usage-limits-billing-and-administration
- Forgejo documents that its runner should not share a machine with the Forgejo instance, and warns that LXC is not safe for potentially malicious job authors. https://forgejo.org/docs/v12.0/admin/actions/runner-installation
- Forgejo documents that Docker-in-actions requires an explicitly reachable daemon; the ordinary job container cannot reach `/var/run/docker.sock` by default. https://forgejo.org/docs/latest/admin/actions/docker-access
- Playwright documents that CI needs browser-capable agents and that reports/traces can contain credentials or source data and must be treated as sensitive. https://playwright.dev/docs/ci and https://playwright.dev/docs/ci-intro

## Constraints

- The current VPS is one production host with constrained, unknown capacity; no measured CPU, RAM, disk, or job quota was available in this repository.
- Hermes is unprivileged: no sudo, production Docker, production `.env`, secrets, runtime database, production workspace, push, merge, or deploy.
- Production remains human-gated under D012 and `docs/RISK_POLICY.md`.
- CI must accept that code and workflows from an `agent/*` branch are untrusted until reviewed.
- A future browser suite must not use a production browser, personal Chrome, production credentials, or production data.
- The solution must not imply that source migration, CI, staging, or remote write access exists today.

## Threat model and security boundary

### Trust levels

1. **Untrusted input:** commits, dependency files, CI workflow files, test fixtures, and build scripts in `agent/*`; an agent can intentionally or accidentally make any of them hostile.
2. **CI execution:** may read the checked-out commit and public package registries only. It must not hold production credentials, a production network path, a privileged Docker socket, or a token capable of merging/provisioning/deploying.
3. **Evidence/artifacts:** may contain source, logs, screenshots, traces, fixture data, and tokens accidentally printed by tests. They are confidential engineering records, not public logs.
4. **Review/promotion:** human reviewers decide whether a verified commit may reach a protected integration branch. Production is a separate Red human gate.
5. **Production:** Caddy, Compose runtime, `/var/run/docker.sock`, `infra/.env`, `infra/data/`, and runtime credentials remain outside the CI trust domain.

### Why CI access to production Docker is unacceptable by default

A mounted or reachable production `/var/run/docker.sock` gives a CI job control over the host Docker daemon. The job could start privileged containers, mount host filesystems, inspect or alter production containers/networks/volumes, read injected environment variables, consume host resources, or persist outside the checked-out worktree. A non-root process inside a CI container does not compensate for daemon authority. Therefore the path below is prohibited:

```text
agent-generated code -> CI job -> production /var/run/docker.sock -> production host/runtime/secrets
```

Do not solve build convenience by joining a CI user to the production `docker` group, mounting the socket, or running the runner in the production Compose stack.

### Required future controls

- Hosted/ephemeral runner or a separately administered runner host; no runner on the production VPS.
- No production secret, Docker socket, SSH deployment key, cloud credential, private production route, or production-test target in pull-request/agent-branch jobs. Because provider-hosted workers have general internet egress, B2 must separately evaluate enforceable blocking of known public production endpoints; lack of a private route alone is not proof that a job cannot reach a public endpoint.
- Read-only, least-privilege repository token for validation; branch protection and human-only merge/promotion credentials.
- Explicit timeouts, concurrency limits, artifact size/retention limits, and cancellation of superseded jobs.
- Dependency pinning/lockfiles where available and pinning third-party CI actions to reviewed immutable revisions before privileged workflows are ever introduced.
- A separate later staging environment and staging-scoped credentials; never reuse production credentials for test execution.

## Options evaluated

### Option A. Private hosted Git service with managed external CI (GitHub Actions)

**Security boundary:** managed hosted workers run outside the production VPS. Agent-branch jobs remain untrusted and receive no production or staging secrets. This removes the production Docker socket and local host from the normal CI execution path.

**Integration and operation:** requires an explicitly approved move of the engineering source of truth to a private hosted repository, or a separately designed and reviewed mirror. GitHub-hosted CI provides run logs, statuses, artifacts, and standard browser-capable Linux workers; it avoids maintaining a runner daemon. The legacy bare repository can remain a read-only archive during a controlled migration, not a silent parallel source of truth.

**Resources/cost:** no CI CPU/RAM/browser/cache pressure on the production VPS. Private-repository minutes and artifact/cache storage are plan-dependent and may be billed; a B2 feasibility gate must confirm plan limits and set spend/retention limits.

**Playwright/staging:** compatible with headless Playwright and uploaded reports. Browser tests later target an isolated staging/fixture environment only.

**Failure/removal:** provider outage, quota exhaustion, artifact retention expiry, or hosted-source dependency can block validation but cannot directly alter production. Removal is a repository/workflow migration, not a production runtime teardown.

### Option B. Self-hosted Forgejo/Gitea service plus runner

**Security boundary:** a Git service and runner are distinct components. A runner that executes untrusted branch code is hostile-workload infrastructure, not production infrastructure. Putting Forgejo/Gitea and its runner on the current VPS creates persistent services and a new attack/resource boundary next to production.

**Integration and operation:** offers local control, Git UI, workflow logs, artifacts, and branch governance, but requires service backup, upgrade, TLS/authentication, runner registration, action compatibility, artifact storage, and incident handling. Docker-based execution risks pressure to expose a daemon; rootless execution reduces privilege but does not make a production-host runner equivalent to a separate host.

**Resources/cost:** persistent Git service, runner, images, browser binaries, build caches, and artifacts consume the single VPS. Monetary external cost can be low, but operational cost and production blast radius are high.

**Playwright/staging:** workable only on a non-production runner host with controlled artifact storage.

**Failure/removal:** requires migration/backup and runner cleanup. A compromised runner or a runaway browser job can affect the shared host.

### Option C. Custom isolated runner on the current production VPS

**Security boundary:** a dedicated Unix user, systemd sandbox, rootless container runtime, cgroups, and firewall rules improve containment but do not establish a sufficient boundary for hostile CI workloads on the production host. Kernel/runtime vulnerabilities, configuration mistakes, shared disk exhaustion, host-wide CPU/memory pressure, and access to local Git remain material risks.

**Integration and operation:** can retain the bare remote and avoid an external service, but requires custom trigger, queue, workspace cleanup, sandboxing, evidence upload, artifact retention, update, and alerting logic. It also has no mature hosted CI control plane by default.

**Resources/cost:** lowest direct spend but competes with Caddy/n8n/PostgreSQL/application services. Playwright browsers, image builds, and caches make the contention risk worse.

**Playwright/staging:** technically possible but unsuitable on the production VPS. Browser processes are particularly poor neighbours for the existing workload.

**Failure/removal:** custom operational code must be maintained and safely removed; a runaway job can still destabilize production.

### Option D. Keep the bare Git remote and add a separate isolated automation host

**Security boundary:** safe only if the execution host is separate from production and has no production credentials/network access. The bare remote remains local source of truth.

**Integration and operation:** needs a constrained polling or event bridge, a read-only clone credential for the runner, an artifact/evidence transport, deduplication, and an authenticated status path. A post-receive hook, webhook bridge, or polling agent would be new security-sensitive custom infrastructure. The runner must not require production Docker access merely to test service images.

**Resources/cost:** moves workload off the VPS if the host is actually separate, but adds a machine/provider and custom automation maintenance. Browser support is practical on the separate host.

**Playwright/staging:** compatible when the separate host is browser-capable and staging is separate.

**Failure/removal:** avoids source migration but leaves a bespoke bridge that must be monitored, upgraded, and removed. A bridge credential becomes a high-value target.

## Comparison matrix

| Criterion | A: hosted Git + managed CI | B: self-hosted Forgejo/Gitea + runner | C: custom runner on production VPS | D: bare Git + separate automation host |
| --- | --- | --- | --- | --- |
| Production Docker exposure | None by design | Must be prevented; easy to misconfigure | High default risk | None if host/credentials are isolated |
| Production workload impact | None for CI execution | High if on current VPS | High | None if separate host |
| New operational components | Low | High | High/custom | Medium-high/custom bridge |
| Git handoff change | Source migration or managed mirror | New Git service migration | None initially | Bridge/polling design |
| Secrets on agent branches | None | Must be configured | Must be engineered | Must be engineered |
| Logs/artifacts | Managed | Service storage to operate | Custom storage | Custom/hosted storage to operate |
| Playwright suitability | Strong | Strong only off production host | Poor on current VPS | Strong on separate host |
| Direct monetary cost | Plan-dependent | Hosting/storage plus time | Low direct, high risk | Separate-host/provider cost |
| External dependency | Yes | Lower service dependency, higher self-operation | Low | Separate host/provider and custom tooling |
| Rollback/removal | Revert workflows/migration | Decommission service/runner | Remove custom service; residual host risk | Remove bridge/runner and revoke credentials |

## Recommendation

**Recommended direction: Option A — a private hosted Git repository with managed external CI, using only provider-hosted ephemeral workers for untrusted validation.**

This is the simplest option that keeps untrusted execution and eventual browser workloads off the production VPS without asking a small project to operate a Git forge, runner, artifact system, and browser fleet. It deliberately introduces a hosted dependency, but that dependency substitutes for a materially more dangerous and maintenance-heavy production-adjacent runner. The alternative of putting a self-hosted runner on the current VPS is rejected even if run rootless.

This is a direction, not an approved B2 implementation decision. B2 requires Product Owner approval of the source-of-truth transition, provider/plan/cost, repository privacy, credential model, protected branch policy, and later staging design. If a hosted Git source is rejected, Option D is the fallback to specify and threat-model before implementation; it must use a genuinely separate runner host, not the production VPS.

## Rejected alternatives

- **B as a current-VPS deployment:** rejected because a persistent forge and runner co-located with production increase attack surface, operations, and resource contention. Self-hosting is not intrinsically safer.
- **C:** rejected because rootless/sandboxed local execution does not justify running agent-generated workloads beside production services; it fails the desired blast-radius and resource-isolation goal.
- **D as the primary path:** deferred as a fallback because preserving the local bare source costs a custom bridge, evidence transport, and credential-management surface. It is appropriate only if the human owner rejects hosted source migration after evaluating the trade-off.

## Git handoff direction

Target flow after an approved B2 implementation:

```text
Hermes restricted principal
  -> refs/heads/agent/* only in private engineering repository
  -> managed CI at immutable commit SHA
  -> deterministic evidence + artifacts
  -> human review of protected integration PR
  -> separate staging gate when available
  -> human production promotion gate
```

The desired Hermes principal is limited to creating/updating only its own `refs/heads/agent/*` namespace. It must not create tags, alter protected `dev`/`main`, change repository settings, administer CI secrets, approve reviews, merge, or deploy. B2 must verify that the selected provider actually enforces that ref-prefix/tag restriction: protected-branch rules alone are not evidence of a general Git write-prefix ACL. If the provider cannot enforce it, do not give Hermes a direct write credential; use a separately approved untrusted-ingress repository or a narrowly reviewed branch-write gateway instead. The repository must protect integration branches and require human review. The current local bare remote must not be changed during B1. B2 must choose either a single hosted source of truth with a retained read-only legacy archive, or a precisely one-way mirror with an explicit authoritative side; two writable sources are prohibited.

## CI isolation direction

Use provider-hosted ephemeral workers for pull-request and agent-branch validation. Each job checks out one SHA in a disposable workspace; it has no mounted host Docker socket, no production/staging secret, no private production route, and a read-only repository token. It must not target production endpoints; B2 must validate an enforceable block for known public production destinations where the provider and network controls permit, rather than assuming internet-hosted workers cannot reach them. Image builds and service integration tests must use the runner's disposable environment, not the production daemon. A later deployment workflow, if ever approved, is separate from validation and runs only after protected-branch review plus the applicable human gate.

## Future machine-readable evidence model

Every CI run should publish a small `evidence.json` artifact plus links to bounded logs/artifacts. The schema must be versioned, tied to the exact commit, and distinguish pass, fail, skipped, cancelled, and not-run; `ready` must never hide a skipped required check.

```json
{
  "schema_version": 1,
  "task_id": "B2-CI-IMPLEMENTATION",
  "repository": "owner/megabrain",
  "commit": "full-immutable-sha",
  "ref": "refs/heads/agent/example",
  "risk": "YELLOW",
  "run": {
    "provider": "github-actions",
    "workflow": "ci",
    "run_id": "provider-run-id",
    "started_at": "RFC3339",
    "finished_at": "RFC3339",
    "result": "pass"
  },
  "checks": [
    {"name": "unit", "status": "pass", "required": true, "summary": "..."},
    {"name": "lint", "status": "not-run", "required": false, "reason": "not configured"},
    {"name": "integration", "status": "pass", "required": true, "summary": "..."},
    {"name": "build", "status": "pass", "required": true, "summary": "..."},
    {"name": "security", "status": "pass", "required": true, "summary": "..."}
  ],
  "artifacts": [
    {"name": "test-results", "uri": "provider-artifact-uri", "sha256": "...", "retention_days": 14, "sensitivity": "internal"}
  ],
  "policy": {
    "required_checks_passed": true,
    "human_review_required": true,
    "staging_required": false,
    "production_approved": false
  },
  "ready": false
}
```

`ready` means only that the declared validation policy for that exact commit is satisfied; it never means merged, staged, deployed, or production-approved. The CI workflow must generate the document from actual command exit statuses rather than text parsing. Logs must be bounded and redacted; artifact manifests should record digest, retention, and sensitivity. Hermes can consume the concise JSON, then link a reviewer to exact logs/artifacts when needed.

## Playwright future integration

Playwright belongs in a dedicated, provider-hosted CI job or a later separate non-production runner, never on the production VPS or a personal browser profile. The job uses fixture data or a future isolated staging environment, a dedicated non-production account, and staging-only credentials supplied only to the protected/staging path. It runs headless with timeout/concurrency limits and captures screenshots, traces, videos, and HTML reports only on failure or as policy requires. Those artifacts are restricted and short-retention because Playwright warns that they can contain credentials or source data. Agentic browser tooling may support exploratory QA but is not CI evidence.

## Staging implications

Staging is not implemented. When approved, it needs an independently provisioned environment and credentials: no shared production Compose runtime, database, R2 credentials, auth secret, Docker socket, or public production hostname. CI validation can remain fully isolated until staging exists; a later risk policy must state which Yellow changes require a staging gate. A staging deployment remains a separate, human-gated workflow in the initial rollout.

## Resource implications

The preferred direction keeps build, dependency-cache, browser, and artifact pressure off the production VPS. It still requires policy limits: one concurrent repository run initially, bounded job timeout, bounded artifact sizes, short retention, cancellation of stale runs, and monthly hosted-provider spend/storage review. No numerical VPS capacity allocation is recommended because this repository contains no capacity measurements. If hosting limits prove inadequate, provision a separate runner host; do not fall back to the production VPS.

## Open questions requiring human decision

1. Approve or reject a private hosted Git source-of-truth migration; if rejected, approve a B2 specification for Option D instead.
2. Identify the approved provider/account/region, private-repository policy, billing cap, and acceptable external-dependency posture.
3. Define who owns the human review, branch protection, agent credential rotation/revocation, and incident response.
4. Decide whether the legacy local bare repository becomes an immutable archive or a one-way mirror, and which side is authoritative.
5. Define a future separate staging host/data-reset method and the first Playwright-critical regression flows.
6. Establish actual VPS and provider budget/retention limits before B2.

## Evidence classification

- **Verified in repository:** local bare remote; no CI/staging/Playwright config; tracked Python tests; production Compose/Caddy shape; ignored secret/data paths; permanent agent and production restrictions.
- **Verified by official vendor documentation:** hosted-runner billing model, Forgejo runner/Docker caveats, and Playwright CI/artifact caveats cited above.
- **Recommended design:** hosted private Git plus managed CI and all target controls in this document. None is deployed or approved merely by this B1 discovery.
