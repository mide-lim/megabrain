# B4.1 — GitHub App Auth Bootstrap Discovery

## Status

DISCOVERY COMPLETE — Yellow gate approved on 2026-09-03 for Hermes-local
installation and hermetic validation without a real credential. The first test
of the new capability that generates a JWT or installation token remains
unapproved and must stop for a separate operational gate.

## Objective

Transform the already-existing `megabrain-hermes` GitHub App authentication
sequence into a reusable Hermes-local capability. The capability must mint a
short-lived JWT and installation token only for an individual operation, use a
temporary `GIT_ASKPASS` when Git authentication is necessary, revoke the token,
and remove all temporary state without changing GitHub configuration.

B4.1 is the authentication foundation only. It does not implement B4.2
Autonomous PR Lifecycle.

## Current State

### Proven by versioned documentation

- GitHub `mide-lim/megabrain` is the development source of truth.
- Hermes may publish `agent/*` and open pull requests, while `dev` and `main`
  remain protected and human-gated.
- Hermes has no authority for administration, rulesets, bypass, merge, deploy,
  production, or production secrets.
- The project currently has no `gh` CLI dependency and uses HTTPS `origin`.

Sources: `AGENTS.md`, `docs/ACTIVE_TASK.md`, `docs/DEVELOPMENT_WORKFLOW.md`,
and D017 in `docs/DECISIONS.md`.

### Proven by the authorized operational self-test

The controlled B4.1 self-test completed in this session with sanitized output:

- JWT was generated only in process memory from the pre-existing App identity;
- a repository-scoped installation token was minted only in process memory;
- the installation exposed only `mide-lim/megabrain`;
- effective permissions observed were `actions: read`, `contents: write`,
  `metadata: read`, `pull_requests: write`, `statuses: read`, and
  `workflows: write`;
- `administration` was absent;
- a `0700` temporary `GIT_ASKPASS` authenticated a read-only
  `git ls-remote --heads origin refs/heads/dev` probe;
- token revocation returned HTTP 204;
- the temporary helper was removed and the parent authentication environment
  was clean.

The test performed no Git write, API configuration change, ruleset operation,
merge, deployment, or production action.

### Not yet proven

- A client-side branch allowlist is not proof of a provider-enforced general
  Git write-prefix ACL. The self-test did not and must not test writes to
  protected refs, tags, or other branches.
- A reusable local helper/skill has not been implemented or locally tested.
- B4.2 has not defined or approved an autonomous pull-request lifecycle.

## Problem and Constraints

The established App flow required manual reconstruction for each task. Repeating
it encourages inconsistent cleanup and increases the chance of exposing a token
in a command, log, configuration file, or long-lived process environment.

The solution must preserve all of these constraints:

- no change to GitHub App permissions, installation, rulesets, bypass, or
  repository configuration;
- no `Administration` permission;
- no PAT, owner-level SSH credential, production secret, deployment, merge, or
  direct update of `dev` or `main`;
- no token, JWT, key material, authorization header, or helper content in
  stdout, logs, repository files, or persistent configuration;
- no persistence of a generated token or JWT;
- token revocation and cleanup on success, failure, and timeout;
- HTTPS remote pinned to `https://github.com/mide-lim/megabrain.git` before a
  token can be supplied to Git.

## Paths Considered

### 1. Repeat task-specific manual commands

Rejected. The sequence is already known but has no reusable contract, makes
cleanup easy to omit, and couples every future Git task to credential-handling
instructions.

### 2. Persist an App token, PAT, or owner-level SSH credential

Rejected. A persistent token violates the requested ephemeral model; PAT and
owner-level SSH are explicitly out of scope and exceed the least-privilege
boundary.

### 3. Add an external credential manager or `gh` dependency

Rejected for B4.1. It adds installation, configuration, and another persistence
surface without solving the precise lifecycle requirement. `gh` is not currently
available in the workspace.

### 4. Hermes-profile-local skill backed by a narrow helper

Recommended. A local skill documents one audited procedure, while a small
helper uses Python standard library, `openssl`, and `git`, which are already
available. The key remains at its pre-existing local protected location and is
never copied into the repository, a skill, or environment file.

## Recommended Architecture

Create a profile-local `megabrain-github-app-auth` skill with a companion helper
outside the repository. Its public interface must be narrow, not a generic
shell or GitHub API proxy.

1. Validate the exact HTTPS `origin` before minting a token.
2. Check that the existing key is a regular file with no group/other access.
3. Build an RS256 JWT in memory with a lifetime under ten minutes.
4. Request an installation token restricted to `megabrain`.
5. Verify the effective permission map, absence of `administration`, and exact
   installation repository scope before invoking Git.
6. Create a `0700` `GIT_ASKPASS` helper in a system temporary directory.
7. Supply the token only to the immediate Git child process through a minimal
   environment and disable terminal prompts and configured credential helpers.
8. Provide only explicitly designed operations: the B4.1 read-only probe and,
   later under B4.2, a separately designed `agent/*` publish operation. Do not
   accept arbitrary commands, refs, remote URLs, or API paths.
9. Revoke the token using the installation token, remove the helper, clear
   in-process references, and emit a structured sanitized result from `finally`.

B4.2 may reuse this lifecycle but must independently define branch validation,
PR creation, CI observation, error handling, and human merge gates. B4.1 does
not grant those capabilities.

## Risks and Trade-offs

- The observed `contents: write` and `workflows: write` permissions make local
  operation allowlists essential but do not substitute for GitHub-side
  protections. No write behavior is exercised in B4.1.
- The private key and ephemeral token are security-sensitive even though they
  are not production secrets; failures must be sanitized and cleanup must be
  fail-safe.
- Revocation depends on GitHub API availability. The helper must report a
  revocation failure without revealing token material and must never persist the
  token for retry.
- A profile-local helper is intentionally not versioned with product code. Its
  implementation and operational validation therefore require a narrow,
  explicit Yellow gate and a documented rollback.

## Recommendation

Approve implementation of the profile-local narrow helper and skill as a Yellow
change. Validate it first with hermetic unit tests using mocked signing, HTTP,
and Git execution. A second operational test of the new helper requires explicit
scope approval because it would mint another installation token, even though it
remains read-only.

## Next Step

Implement and hermetically validate the local B4.1 helper/skill under the
approved Yellow gate. Stop before its first real-App probe: that probe would
mint a new installation token and requires a separate operational authorization.
No GitHub permission, repository, ruleset, or production action is authorized.
