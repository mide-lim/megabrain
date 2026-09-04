# Task Contract — B4.1: GitHub Auth Bootstrap

## Status

- Status: COMPLETE / HUMAN GATE FINAL
- Risk Level: YELLOW approved on 2026-09-03 for repository-side canonicalization,
  derived local helper installation/reinstallation, hermetic no-credential
  validation, and one separately authorized historical real-App probe; no
  further authenticated operation is authorized.

## Objective

Make the existing `megabrain-hermes` GitHub App lifecycle reusable as a narrow,
Hermes-profile-local capability without persisting credentials or expanding the
GitHub authority boundary.

## User / Product Context

Future agent work must not require manual reconstruction of JWT creation,
installation-token minting, temporary `GIT_ASKPASS`, and cleanup. The capability
is a prerequisite for B4.2 Autonomous PR Lifecycle, but B4.2 is not included.

## Source Documents

- `docs/GITHUB_APP_AUTH_BOOTSTRAP_DISCOVERY.md`
- `docs/GITHUB_APP_AUTH_BOOTSTRAP_SDD.md`
- `docs/RISK_POLICY.md`
- `docs/DEFINITION_OF_DONE.md`

## Scope

### In

- document and approve the versioned canonical source under
  `skills/megabrain-github-app-auth/` and a derived profile-local installation;
- reconstruct or reinstall only `SKILL.md` and `scripts/github_app_auth.py` at
  `~/.hermes/skills/megabrain/megabrain-github-app-auth` from repository source,
  without reading, copying, or versioning credentials or Hermes configuration;
- generate JWTs only in memory with RS256 and sub-ten-minute lifetime;
- validate the expected baseline permission map of the existing installation
  with the App JWT, including absence of `administration`;
- mint a repository-restricted installation token only per operation with the
  minimum B4.1 permission request, `contents: read`;
- require the probe token to contain only `contents: read` and, if returned by
  GitHub, `metadata: read`, then observe its installation repository scope;
- provide a fixed read-only probe for `refs/heads/dev` through temporary
  `GIT_ASKPASS`;
- revoke the token and remove temporary state on every path;
- add hermetic tests before a new real-App probe.

### Out

- changing GitHub App permissions, installation, repository settings, rulesets,
  bypass, Administration, or workflows;
- persistent JWTs, tokens, keys, PATs, SSH credentials, or credential helpers;
- Git write, branch publication, tag creation, pull-request creation, merge,
  deploy, production access, or production secrets by the B4.1 helper;
- B4.2 and all autonomous PR lifecycle behavior.
- the first execution of the new helper that generates a JWT or installation
  token.

## Acceptance Criteria

- The authorized B4.1 self-test remains recorded only through sanitized evidence:
  installation scope was `mide-lim/megabrain`, `administration` was absent,
  read-only Git auth passed, revocation returned HTTP 204, and cleanup passed.
- The planned helper has one fixed B4.1 read-only operation and no arbitrary
  command, URL, ref, or API-path interface.
- The helper validates exact HTTPS origin and restricted key file mode before
  minting a token.
- The helper checks the expected installation baseline through the App JWT and
  rejects `administration` before token minting. It then rejects a probe token
  with any write or unexpected permission, and rejects unexpected installation
  scope before Git runs.
- Generated JWT/token, key material, authorization headers, askpass path/content,
  raw errors, and traces never reach output, logs, repository files, or
  persistent profile configuration.
- The temporary helper is `0700`, child-process-only, and removed after success,
  error, and timeout.
- Every minted token is revoked on success and cleanup attempts revocation after
  any subsequent failure; no token is kept for retry.
- Hermetic tests cover success, origin rejection, permission/scope rejection,
  Git failure, revocation failure, and cleanup.
- No GitHub configuration, repository, ruleset, production system, or product
  code changes occur.

## Architecture / Technical Plan

Implement the SDD design as a repository-versioned canonical skill and small
Python helper under `skills/megabrain-github-app-auth/`. Its installer creates a
derived profile-local artifact from that source only; it never reads or copies a
profile installation. The helper uses the existing key only as signer input,
makes fixed GitHub API calls for mint/scope/revoke, and executes only the fixed
B4.1 `git ls-remote` probe through a temporary askpass helper. A later B4.2
contract must define any agent-branch write operation separately.

## UX Specification Reference

N/A.

## Contracts Changed

No repository, product, API, database, or runtime contract changes. The only
new contract is the planned local helper result schema described in the SDD.

## Data / Migration Impact

N/A.

## Security Impact

The task handles an existing GitHub App private key and ephemeral installation
tokens, so it is Yellow despite no intended GitHub write. It preserves least
privilege by validating the installation baseline and absence of
`administration` with the App JWT, repository-restricting the probe-token
request to `contents: read`, rejecting any probe-token write permission,
requiring exact scope, refusing unexpected remotes, isolating credentials to
the Git subprocess, revoking tokens, and sanitizing every result.

The App installation baseline may contain write permissions for separately
authorized repository workflows, but B4.1 neither requests nor accepts them in
its probe token. This does not prove a general provider-enforced `agent/*`
write boundary; that remains an explicit B4.2 validation question.

## Expected Files / Components

- `skills/megabrain-github-app-auth/SKILL.md`
- `skills/megabrain-github-app-auth/scripts/github_app_auth.py`
- `skills/megabrain-github-app-auth/scripts/install_skill.py`
- `skills/megabrain-github-app-auth/tests/test_github_app_auth.py`
- derived profile-local `~/.hermes/skills/megabrain/megabrain-github-app-auth`
  installation containing only the skill document and executable helper

## Required Tests

- hermetic unit tests for every success/failure cleanup path, including origin,
  permission, repository-scope, key-mode, Git, revocation, and gate rejection;
- a hermetic clean-install and reinstall test that compares source/destination
  SHA-256 bytes and modes and asserts only the two derived artifacts exist;
- output and temporary-directory redaction assertions;
- no authenticated test is required or authorized for canonicalization.

## Required Evidence

- sanitized unit-test results;
- inspection showing no repository or secret/configuration files changed;
- sanitized real-App probe result, if separately authorized;
- `git diff --check` and scope inspection for the documentation delivery.

## Staging Requirements

N/A. A real credential must not be added to repository CI or staging.

## Production Impact

None. No production endpoint, runtime, Docker resource, data store, secret, or
deployment is accessed or modified.

## Rollback / Recovery

Before implementation: no rollback is required beyond reverting this planning
documentation.

After an approved implementation: remove only the new profile-local helper and
skill after confirming cleanup; do not alter the App, installation, permissions,
rulesets, or repository. If token revocation fails, stop use of the helper and
allow the short-lived token to expire without storing it.

## Human Gates

1. Yellow gate: approved on 2026-09-03 for installation of the profile-local
   helper/skill and hermetic no-credential validation only.
2. Operational gate: approved for and completed as one real-App test of the
   newly installed helper; no further authenticated operation is authorized.
3. B4.2 gate: define and approve any Git write or PR behavior independently.
4. Final delivery gate: a human reviews the canonical-source Pull Request and
   decides whether to merge it into `dev`; no automated merge is permitted.

No gate in this contract authorizes Administration, rulesets, bypass, merge,
deployment, production, PAT, owner-level SSH, or persistent credentials.

Publication and review of this canonical-source delivery use the already
approved repository GitHub workflow for `agent/*`; they are not B4.1 helper
operations and do not extend the helper's read-only interface or authorize B4.2.

## Dependencies

- Existing GitHub App identity, installation, and protected local private key;
- Python 3, `openssl`, GitHub HTTPS API, and `git`;
- named human owner/reviewer for future profile-local helper changes.

## Open Questions

- Whether GitHub can provider-enforce the general `agent/*` write restriction
  for this App beyond protected `dev` and `main`.
- The named owner and review cadence for future profile-local skill/helper
  modifications.

## Final Evidence Summary

The completed authorized self-test was read-only and passed: it generated the
JWT and installation token in memory, observed only the expected repository,
observed no `administration`, authenticated one `git ls-remote` of `dev` through
temporary askpass, received HTTP 204 on token revocation, removed the helper,
and left the parent authentication environment clean. It did not test Git
writes or prove provider-side ref-prefix enforcement. A later local security
correction separates verification of that historical installation baseline from
the downscoped B4.1 probe token; no new authenticated execution is authorized
by this correction.

This documentation checkpoint records the approved local implementation scope
before installation. No Git write, GitHub configuration change, or production
action is authorized; the first real-App helper probe remains pending a separate
operational gate.

The approved local installation subsequently completed with static compilation
and hermetic tests only. The tests used mocked signing, HTTP, and Git execution
to cover success, cleanup, origin rejection, permission and `administration`
rejection, repository scope, Git failure, revocation failure, key mode, and the
operational-gate refusal. No real credential, JWT, installation token, network
request, Git write, configuration change, or production action occurred.

The separately authorized real `probe-read-dev` then passed with only
sanitized evidence: expected origin, scope, permissions and absence of
`administration`; read-only `dev` probe; token revocation; and askpass cleanup.
Post-operation checks found no sensitive parent-environment residue, helper
process, capability temporary file, local credential helper, local `core.askpass`,
or local `http.extraheader`. It made no Git write, push, pull request, merge,
ruleset, bypass, App change, deployment, or production action. No further
authenticated operation is authorized.

## Final corrected-capability live downscope evidence

After a new explicit one-time authorization, the corrected and installed B4.1
capability completed its sole `probe-read-dev` operation successfully. The App
JWT installation-baseline validation passed; the repository-restricted probe
token requested only `contents: read`. GitHub provider-validated the returned
probe-token permission map as read-only, with no write or `administration`;
the exclusive `mide-lim/megabrain` scope and read-only `refs/heads/dev` Git
probe were also accepted. The token was revoked successfully and temporary
askpass cleanup succeeded.

The post-probe checks found zero transient token/askpass environment residues,
zero capability temporary artifacts under `/tmp`, zero active helper or askpass
processes, and no local, global, or system `credential.helper`, `core.askpass`,
or `http.extraheader` configuration. The working tree was clean before this
local evidence update. No Git write, push, pull request, merge, ruleset,
bypass, App change, deploy, or production action occurred. This is the final
authorized authenticated operation; no remote publication was performed.

Canonical source reproducibility is complete: the versioned
`skills/megabrain-github-app-auth/` source reconstructed and re-reconstructed a
fresh temporary derived destination using only repository files. The hermetic
unit suite passed 13 tests, including byte-for-byte SHA-256 source/destination
comparison, `0700` executable helper verification, exact derived-artifact-set
verification, and absence of `.env`, `.pem`, and `.key` artifact names. It used
mocked signing, HTTP, and Git and supplied no credential, JWT, token, network,
or authenticated probe. The default installer target remains a derived artifact
at `~/.hermes/skills/megabrain/megabrain-github-app-auth`.
