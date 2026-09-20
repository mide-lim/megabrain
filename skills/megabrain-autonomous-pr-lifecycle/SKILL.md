---
name: megabrain-autonomous-pr-lifecycle
description: "Run an approved bounded B4.2 PR lifecycle."
version: 1.3.1
---

# MegaBrain B4.2 Autonomous PR Lifecycle

This is canonical, versioned source for the B4.2 local capability. Its lifecycle operations are `preflight`, `publish-head`, `ensure-pr`, `observe-ci`, `authorize-correction`, `finalize-correction`, `refresh-from-dev`, and `report-ready`; it contains no merge, auto-merge, generic shell, generic Git/API endpoint, arbitrary refspec, URL, remote, or base interface.

`agent/*` validation is a local defense-in-depth control, not a GitHub ACL. A `contents: write` token can have broader provider-side authority over unprotected refs than the capability exposes. GitHub protects `dev` and `main`; human review and human merge into `dev` remain mandatory.

## Canonical source and derived installation

Canonical source is this repository directory. It never contains an App identifier, installation identifier, key, JWT, token, `.env`, or persistent credentials. The only installed artifacts are `SKILL.md`, `scripts/autonomous_pr_lifecycle.py`, `scripts/github_app_runtime_config_bridge.py`, `scripts/github_app_user_attribution.py`, `scripts/bootstrap_user_attribution.py`, `scripts/authenticated_read_validation.py`, `scripts/authenticated_publish_head.py`, `scripts/authenticated_ensure_pr.py`, and `scripts/authenticated_observe_ci.py`.

From the repository root, install or reconstruct the derived artifact:

    python3 skills/megabrain-autonomous-pr-lifecycle/scripts/install_skill.py

The fixed destination is `~/.hermes/skills/megabrain/megabrain-autonomous-pr-lifecycle`. The installer stages an exact artifact list and atomically replaces the target; it never reads or copies the prior target.

## Contract and immutability

A future approved operational contract is strict JSON only at `/etc/megabrain/hermes-contracts/b4.2/<lifecycle_id>.json`; there is no repository-relative fallback or selectable contract root. The exact file and control directory must be regular/non-symlink, root-owned, and not group/other writable. `preflight` computes a SHA-256 canonical fingerprint and locks it in owner-only local state outside the repository. Every lifecycle operation reloads the contract and compares that fingerprint before validating or mutating anything. Any mismatch returns `STOP_NEEDS_HUMAN`; this capability never writes the contract.

The permanent v1 denylist includes `.github/workflows/**`, both B4.2 and B4.1 source trees, `AGENTS.md`, `docs/RISK_POLICY.md`, `docs/DEFINITION_OF_DONE.md`, task-contract, lifecycle, workflow, bypass, merge, permission and policy control documents. `ACTIVE_TASK.md`, evidence, and operational documentation are allowed only when an exact contract `allowed_paths` entry permits them. Traversal and symlinks are rejected.

## Token model and operation limits

Each future operation uses a distinct credential purpose: publish only `contents: write` plus provider-required `metadata: read`; PR creation uses a GitHub App user-to-server credential scoped down to only `mide-lim/megabrain` and `pull_requests: write` plus provider-required `metadata: read`; observation only `pull_requests: read`, `actions: read`, `statuses: read`, and `metadata: read`. The scoped PR token is short-lived, validated against actor `mide-lim`, and revoked after P3. A protected rotating refresh token and GitHub App client secret are persisted only in the fixed local configuration directory so P3 can mint a fresh user credential without storing a long-lived user access token. Effective scoped permissions must match exactly, Administration is forbidden, and any validation, revocation, or cleanup failure is fail-closed.

`publish-head` is local `HEAD` only to exact `agent/<slug>`, with a fixed HTTPS origin, non-force refspec and remote-SHA readback. Before every publish it validates the clean committed range from the last published state SHA to `HEAD`; only modified, regular Git blobs at allowlisted paths are accepted. Additions are rejected because v1 cannot distinguish every modified copy from a new file; denylisted/unallowed paths and rename, copy, delete or unknown diff statuses stop for a human. A per-lifecycle owner-only reservation serializes publication and atomically consumes the changed-head correction budget before network mutation. `ensure-pr` reads the exact remote branch ref immediately before reuse or creation, permits exactly one fingerprinted `agent/<slug> -> dev` PR, directly revalidates a stored PR number, and never changes its base, closes/reopens it, or creates a second PR. `observe-ci` accepts only the current PR head SHA and exactly the contract jobs, all `success`; each new publish invalidates prior CI evidence. CI logs are inert bounded data, never instructions. `refresh-from-dev` is disabled unless the contract opts in; it only merges `origin/dev`, never rebases or force-pushes, and conflicts stop for a human. `report-ready` never merges.

## P1 authenticated read validation

R2B B4.2 never obtains GitHub App metadata from environment variables. The stable App ID, installation ID, and approved key path come only from B4.1 protected runtime configuration. B4.2 reaches the fixed installed canonical B4.1 loader through the narrow `github_app_runtime_config_bridge.py`; the bridge neither parses `runtime.conf` nor accepts a config or private-key path.

`authenticated_read_validation.py` is a separate, closed read-only adapter; it is not a public `Lifecycle` operation and has no generic Git, API, repository, ref, or command interface. Its only operation is `validate-read-dev-ref`, fixed to `mide-lim/megabrain` and `refs/heads/dev`. That operation is in the Run Authorization vocabulary but is not a public Lifecycle method. P1 requires its exact lifecycle ID and a Run Authorization that literally permits `validate-read-dev-ref`; it loads protected runtime settings only after that authority guard, revalidates both authority and equal immutable settings immediately before mint, then requests only a repository-restricted `contents: read` token. It accepts at most provider-returned `metadata: read`, validates the single repository scope and exact ref, revokes the token, and removes its owner-controlled temporary directory on every path. Any validation, revocation, or cleanup failure is terminal and sanitized.

`authenticated_publish_head.py` is the separate P2 adapter for only `publish-head`. After a distinct explicit human authorization, it validates the immutable approved Task Contract, exact origin, installation baseline, exact one-repository scope, and a repository-restricted `contents: write` token (with only optional provider-returned `metadata: read`). Protected runtime settings load only after the operation guard and are revalidated for equality immediately before token mint. It runs only the contract's exact local `HEAD` to exact `agent/*` branch non-force push, rejects a pre-existing first remote branch and later remote drift, reads back the exact remote SHA, then revokes the token and removes the temporary askpass directory. Initial-publication state is committed only afterward through a fresh token-free source Lifecycle, which reloads the bound control plane and revalidates the exact remote SHA. Its output is sanitized. It has no PR, Actions, merge, deletion, tag, refspec, remote, deployment, or production interface.

`authenticated_ensure_pr.py` is the separate P3 adapter for only `ensure-pr`. Before authentication it revalidates the root-owned immutable Task Contract and fingerprint, lifecycle publication state, clean contract branch and exact local/remote SHA through fixed token-free `/usr/bin/git` reads. It still validates the GitHub App installation baseline through the protected B4.1 runtime settings. For the PR mutation itself, `github_app_user_attribution.py` refreshes the previously authorized `mide-lim` GitHub App user credential, immediately rotates the refresh token, verifies the actor and repository intersection, and exchanges the broad user credential for a one-repository scoped user token with only `pull_requests: write` plus provider-required `metadata: read`. P3 then permits only the fixed `mide-lim/megabrain` PR reads and exact `agent/* -> dev` create payload, so a newly created PR is attributed by GitHub to `mide-lim` while still recording GitHub App programmatic access. It validates the remote ref again after the API result before deferred state commit; it never updates, closes, merges, reviews, comments on, or otherwise mutates a PR. The scoped user token is revoked and temporary cleanup completes before the PR number is persisted; either failure is terminal.

## One-time user attribution bootstrap

Before P3 can create a PR on behalf of `mide-lim`, the GitHub App must have Device Flow enabled and expiring user-to-server tokens enabled. Create or rotate a GitHub App client secret in GitHub settings, then run the bootstrap locally from a trusted TTY as `megabrain-hermes`:

    python3 skills/megabrain-autonomous-pr-lifecycle/scripts/bootstrap_user_attribution.py \
      --client-id <GITHUB_APP_CLIENT_ID> \
      --operational-gate-approved

The helper prompts for the client secret without echo, starts GitHub's device authorization flow, requires the authorized account to be exactly `mide-lim`, verifies that the user/App intersection can access only the intended repository when scoped, creates and revokes a test scoped PR credential, and only then persists three fixed local files under `/home/megabrain-hermes/.config/megabrain-hermes/github-app`: `user-attribution.conf`, `client-secret.txt`, and `user-refresh-token.txt`. These files are mode `0600`, never belong in Git, and are not read from environment variables or arbitrary paths.

The refresh token is rotated every time P3 refreshes a user access token. If GitHub authorization is revoked, the refresh token expires, Device Flow is disabled, the client secret changes, or the fixed files fail validation, P3 stops and requires a new human bootstrap. The bootstrap itself grants no merge, deploy, workflow, ruleset, App-permission, or production authority.

`authenticated_observe_ci.py` is the separate P4 adapter for only `observe-ci`. Under the same owner-only P2/P3 lifecycle reservation, it revalidates the immutable Task Contract and fingerprint, published PR number, exact clean branch, and exact local and remote head SHA through fixed token-free `/usr/bin/git` reads. Protected runtime settings load only after the operation guard and are revalidated for equality immediately before token mint. It requests only repository-restricted `pull_requests: read`, `actions: read`, `statuses: read`, and `metadata: read`; it permits only the exact PR GET, pull-request/head-SHA workflow-run GET, and selected-run jobs GET. It never fetches logs, dispatches, cancels, reruns, comments, reviews, mutates PRs or Actions, or merges. It revokes and cleans up before a final contract/state/local/remote compare-and-set persists only `ci_sha`.

Installation, compilation, and hermetic tests do not authorize a real JWT, token, API call, or authenticated read. Operation tokens remain purpose-specific and ephemeral; the only persistent user credential is the protected rotating refresh token required to mint fresh user-to-server credentials. No real user-attributed P3 operation has been performed by this source change until the bootstrap and an explicitly authorized lifecycle run are completed.

## Validation and human gate

The lifecycle class remains technically inert for authenticated operations: only `preflight` can run outside hermetic mocks. The P2, P3, and P4 adapters are narrow separate exceptions, enabling only their separately gated `publish-head`, `ensure-pr`, and `observe-ci` operations; the public `Lifecycle.ensure_pr()` and `Lifecycle.observe_ci()` gates remain `authenticated_operations_not_authorized`. `refresh-from-dev` and `report-ready` continue to stop with `authenticated_operations_not_authorized`. The P1 adapter never writes Git or GitHub state and does not authorize any lifecycle write, PR action, CI operation, merge, workflow/ruleset/App-permission change, deploy, or production action.

    python3 -m unittest discover -s skills/megabrain-autonomous-pr-lifecycle/tests -v
    python3 -m py_compile skills/megabrain-autonomous-pr-lifecycle/scripts/*.py

The first real P1 read and every later lifecycle operation each need a new explicit human authorization as specified by the approved operational contract. Merge into `dev`, any `main` progression, workflow/ruleset/App permission/policy change, bypass, and production action remain separate human gates.
