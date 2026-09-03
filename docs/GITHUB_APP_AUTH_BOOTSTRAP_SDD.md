# Technical Specification — B4.1 GitHub App Auth Bootstrap

## Objective

Implement a reusable Hermes-profile-local authentication capability that safely
executes the existing GitHub App lifecycle: in-memory JWT, repository-scoped
installation token, temporary `GIT_ASKPASS`, immediate Git child operation,
token revocation, and guaranteed cleanup. The capability must be usable by a
future B4.2 PR lifecycle without implementing it now.

## Known Context and Assumptions

- `origin` is the HTTPS repository `https://github.com/mide-lim/megabrain.git`.
- The pre-existing GitHub App identity, installation, and protected private key
  already exist outside this repository.
- The authorized self-test observed one installation repository,
  `mide-lim/megabrain`, and no `administration` permission.
- Python 3, `openssl`, `curl`, and `git` are available; `gh` is unavailable.
- The Yellow gate approved Hermes-local installation and hermetic validation on
  2026-09-03, but not the first real-App execution that would generate a JWT or
  installation token; no Git write is authorized.

## Scope

### In

- a Hermes-profile-local skill and narrow helper, outside this repository;
- in-memory RS256 JWT generation with lifetime below ten minutes;
- installation-token minting restricted to `megabrain`;
- effective-permission and repository-scope validation;
- a B4.1 read-only `ls-remote` probe using a temporary `GIT_ASKPASS`;
- deterministic cleanup and sanitized machine-readable results;
- hermetic local unit tests for success and failure cleanup paths.

### Out

- GitHub App permission, installation, ruleset, bypass, repository-setting, or
  workflow changes;
- arbitrary GitHub API calls or arbitrary shell-command execution;
- Git write, push, branch creation, pull-request creation, merge, tag, deploy,
  production access, PAT, and owner-level SSH;
- B4.2 Autonomous PR Lifecycle;
- persistence of the private key, JWT, installation token, or askpass helper.

## Affected Components and Architecture

No product application component is affected. The planned local component has
three bounded layers:

1. `megabrain-github-app-auth` skill: usage boundaries, supported operations,
   evidence schema, and incident/rollback procedure.
2. `github_app_auth.py` helper: owns validation, JWT signing, REST calls, Git
   subprocess construction, revocation, cleanup, and redaction.
3. Existing local App key: read only for the `openssl` signing subprocess; it is
   never copied or serialized by the helper.

Execution flow:

```text
validated fixed HTTPS origin
  -> key type/mode precheck
  -> in-memory JWT (RS256, <10 min)
  -> installation token limited to megabrain
  -> permission + repository-scope assertion
  -> 0700 temporary GIT_ASKPASS
  -> fixed read-only Git probe
  -> DELETE /installation/token
  -> remove helper and clear references
  -> sanitized result
```

All error and timeout paths enter the same cleanup routine. If token minting
succeeds but any later stage fails, cleanup attempts revocation once and then
reports only a symbolic failure code and cleanup state.

## Contracts

### Supported B4.1 operation

`probe-read-dev` is the only initial operation. It validates the configured
`origin`, then executes the fixed probe from a new empty temporary directory:

```text
git -C <empty-temp-dir> \
  -c remote.origin.url=https://github.com/mide-lim/megabrain.git \
  -c credential.helper= ls-remote --heads origin refs/heads/dev
```

It validates the configured `origin` before minting a token and rejects any
origin other than the fixed HTTPS repository. The Git child uses only a small
explicit environment: `PATH`, `GIT_ASKPASS`, `GIT_TERMINAL_PROMPT=0`, the
ephemeral token variable, and Git configuration isolation that disables global
and system configuration and prevents repository discovery outside the empty
temporary directory. The parent process environment is not modified.

### Result contract

The helper may emit JSON containing only non-sensitive status fields:

- operation status and symbolic failure code;
- origin-validation result;
- repository-scope result;
- non-secret permission map and explicit `administration` absence;
- Git-probe result;
- revocation HTTP status class/result;
- temporary-helper cleanup result.

It must never emit a JWT, installation token, private-key path/content,
authorization header, raw API response, askpass filename/content, command
stderr, or exception traceback.

### Future B4.2 integration

B4.2 must use a new explicit operation, not pass arbitrary arguments through
this helper. That operation must validate `agent/*` locally, reject protected
refs and tags, preserve the fixed origin, and remain subject to independent
human gates. Local validation is defense in depth, not evidence of a
provider-enforced general ref-prefix ACL.

## Data and Migration Impact

N/A. No application data, schema, migration, database, R2 object, or production
runtime is read or modified.

## Security and Operational Impact

- Maintain least privilege: reject any non-absent `administration` permission
  and unexpected installation repository scope before Git runs.
- Use an installation-token request restricted to the expected repository.
- Create the askpass file at mode `0700`, using a randomized system temporary
  name; remove it in `finally`.
- Disable interactive prompts and configured credential helpers for the Git
  child process to prove the ephemeral askpass path is used.
- Never retain credentials in shell history, repository files, profile config,
  output, logs, or parent environment.
- Treat revoked-token failure and cleanup failure as operation failure. Do not
  retain the token for retry.
- B4.1 contains no administrative, merge, bypass, ruleset, deploy, or
  production behavior.

## Dependencies

- Existing GitHub App identity and installation;
- existing protected App private key;
- Python 3, `openssl`, GitHub HTTPS API, and `git`;
- the approved Yellow gate for local installation and no-credential validation;
- a separate operational gate before the first real-App execution.

## UX Handoff

N/A. This is a non-interactive local operational capability.

## Acceptance Criteria and Definition of Done

- The helper supports only the documented `probe-read-dev` operation.
- The helper refuses unexpected origin URLs before minting a token.
- JWT and token are created only in process memory and are absent from all
  output and persistent files.
- Effective permissions and repository scope are checked before Git runs, and
  any `administration` permission blocks the operation.
- The temporary askpass helper is mode `0700` and is removed after both success
  and injected failure paths.
- The Git probe succeeds only with `GIT_ASKPASS`, non-interactive prompting, and
  disabled configured credential helpers.
- A minted token is revoked on success and best-effort revoked on each later
  failure path; a revocation failure produces a sanitized failure result.
- Unit tests validate cleanup, origin rejection, permission rejection,
  repository-scope rejection, Git failure, and revocation failure without a
  real key or network.
- No repository, GitHub configuration, rule, permission, production system, or
  product code changes occur.
- Documentation passes `git diff --check` and contains no secret material.

## Required Tests and Validation Strategy

Before an operational test of the newly implemented helper:

1. Run hermetic unit tests with temporary files and mocked signer, HTTP client,
   clock, and Git subprocess.
2. Assert that captured stdout/stderr and temporary directory contents contain
   no test fixture standing in for key, JWT, token, or askpass content.
3. Inspect the profile-local diff and permissions; confirm no secret/configuration
   file was introduced.
4. Only with fresh explicit authorization, run `probe-read-dev` once against
   the real App, then retain only its sanitized result.

CI/staging are N/A because this component resides outside the repository and
must not inject a real credential into repository CI.

## Rollback / Recovery

Rollback is deletion of the newly installed profile-local skill and helper after
confirming no active child process, temporary helper, JWT, or token remains.
It does not alter GitHub App configuration, App permissions, installation,
rulesets, repository state, or production. If a token revocation failure is
reported, stop use of the helper and let the short-lived token expire; do not
persist it or attempt a broader credential workaround.

## Technical Risks

- A token has effective write permissions even though B4.1 never uses them.
  Mitigation: one fixed read-only operation, no arbitrary command interface,
  exact remote validation, and future B4.2 gates.
- An exception can occur after minting. Mitigation: single cleanup path with
  best-effort revocation and guaranteed temporary-file removal.
- GitHub API availability can prevent revocation. Mitigation: fail closed,
  report a sanitized symbolic result, and never retain token material.
- The private key is local sensitive material. Mitigation: mode/type precheck,
  direct signer input only, no copy, no serialization, and no log output.

## Risk Classification and Human Gates

- Documentation and the authorized read-only self-test: GREEN.
- Installing the reusable local authentication helper/skill: YELLOW because it
  creates a persistent credential-handling path, even though it stores no
  credential and makes no GitHub configuration change; this Yellow gate is
  approved for local installation and hermetic validation only.
- The first execution of the new helper that generates a JWT or installation
  token remains operationally unapproved and must stop for a separate gate.
- Any future Git write is not authorized by this specification and requires its
  own B4.2 scope, validation, and gate.
- Administration, rulesets, bypass, merge, deployment, and production remain
  outside the capability and require separate authority where applicable.

## Open Questions

- Can GitHub enforce a general Git write prefix restricted to `agent/*` for the
  App, beyond the protections on `dev` and `main`? B4.2 must not assume this;
  it needs provider evidence or a separately approved constrained ingress.
- What review cadence and owner will approve profile-local helper changes after
  B4.1? This must be named before implementation.
