---
name: megabrain-existing-branch-fast-forward
description: "Authorize one exact existing-branch direct-child fast-forward."
version: 1.0.0
---

# MegaBrain Existing-Branch Fast-Forward Adapter

This source is a dedicated, closed adapter for one future transition only. It does not run the transition during source installation or validation.

The compiled transition tuple is immutable:

    repository: mide-lim/megabrain
    origin: https://github.com/mide-lim/megabrain.git
    expected_dev_sha: 68282465b0393c7e140c363ff4b68d85e917afd8
    target_branch: agent/f6-i1-b-a1-installer-rollback-hardening
    target_ref: refs/heads/agent/f6-i1-b-a1-installer-rollback-hardening
    expected_old_sha: 9fa26a31dd6e384fee6bfdfe3b31119cf2f18af8
    authorized_new_sha: e4c7de42b416766e65bccc4fdf1ff49ba170474f
    authorized_new_tree: 21a88423d9ffa344dd97a75e23d423b28e14a5e5
    authorized_new_parent: 9fa26a31dd6e384fee6bfdfe3b31119cf2f18af8

There are no tuple CLI arguments and no environment overrides. The adapter accepts no CLI arguments at all.

## Authorization artifact

A future operational run requires this fixed, separate artifact:

    /etc/megabrain/hermes-authorizations/f6-i1-b-b4-existing-branch-fast-forward/f6-i1-b-b4-existing-branch-fast-forward-v1.json

It must be a regular `0600` file, root-owned, with every directory from `/` to its parent root-owned, non-symlinked, and not group/world writable. It is not created by this source, installer, test suite, or any source-validation command.

Strict JSON is required. Duplicate keys, unknown fields, non-UTC timestamps, an expiration outside the maximum 24-hour window, expiration at or before the current UTC time, and every deviation from the compiled tuple fail closed as `STOP_SOURCE_DRIFT`.

Exact schema, with no wildcard values and no operations array:

    {
      "version": 1,
      "authorization_id": "f6-i1-b-b4-existing-branch-fast-forward-v1",
      "repository": "mide-lim/megabrain",
      "target_ref": "refs/heads/agent/f6-i1-b-a1-installer-rollback-hardening",
      "expected_old_sha": "9fa26a31dd6e384fee6bfdfe3b31119cf2f18af8",
      "authorized_new_sha": "e4c7de42b416766e65bccc4fdf1ff49ba170474f",
      "authorized_new_tree": "21a88423d9ffa344dd97a75e23d423b28e14a5e5",
      "authorized_new_parent": "9fa26a31dd6e384fee6bfdfe3b31119cf2f18af8",
      "expected_dev_sha": "68282465b0393c7e140c363ff4b68d85e917afd8",
      "issued_at": "YYYY-MM-DDTHH:MM:SSZ",
      "expires_at": "YYYY-MM-DDTHH:MM:SSZ"
    }

## Future execution boundary

A future run first proves the workspace identity, exact HTTPS origin, checked-out target branch and exact local commit, tree, one direct parent, clean worktree, clean index, and live `origin/dev` SHA. It then reads the exact remote target ref without credentials.

Remote outcomes are closed:

    expected old SHA  -> preparation may continue
    authorized new SHA -> ALREADY_AT_AUTHORIZED_HEAD, no token and no push
    missing ref        -> STOP_REMOTE_BRANCH_MISSING
    any other SHA      -> STOP_REMOTE_DRIFT

Only after all preflight checks, the adapter loads the established fixed B4.1 runtime configuration, mints one repository-restricted GitHub App installation token for `contents: write` (provider-required `metadata: read` is the only optional returned permission), validates its one-repository scope, and uses a temporary `GIT_ASKPASS`. No token, JWT, private key, header, or raw provider response is printed or persisted.

The sole write is exactly one command equivalent to:

    /usr/bin/git push --porcelain \
      --force-with-lease=refs/heads/agent/f6-i1-b-a1-installer-rollback-hardening:9fa26a31dd6e384fee6bfdfe3b31119cf2f18af8 \
      origin \
      e4c7de42b416766e65bccc4fdf1ff49ba170474f:refs/heads/agent/f6-i1-b-a1-installer-rollback-hardening

    force_with_lease: YES
    unconditional_force: NO
    authorized_result_fast_forward: YES

The local commit is transferred to a fresh temporary staging repository by a fixed local Git fetch, then its SHA, tree, and sole parent are independently rechecked before the write. The source workspace is never mutated. There is one write attempt maximum. After a successful write, the adapter re-reads the exact target ref and `origin/dev`; either mismatch is terminal and cannot trigger a corrective push. The ephemeral token is revoked when the established API supports revocation.

The adapter never creates/deletes a branch, writes a tag or another ref, changes a PR, merges, updates workflows, changes App permissions, deploys, or uses a generic Git, repository, ref, SHA, URL, shell, or API interface.

## Installation

The only install target is:

    /home/megabrain-hermes/.hermes/skills/megabrain/megabrain-existing-branch-fast-forward

The root-only installer has no CLI options. It requires the destination to be absent and refuses overwrite. Before copying, it requires a separate fixed root-owned source-identity record under `/etc/megabrain/hermes-skill-source-identities/`; that record binds the reviewed repository, commit, tree, and exact blobs for this skill source. The installer verifies it against the canonical repository before it creates the destination. It copies only `SKILL.md` and the adapter script, sets root ownership with the Hermes group read/execute access needed for runtime, and removes only its freshly created destination if copying fails.

The installer does not create the source-identity record, the operational authorization artifact, credentials, GitHub state, or remote refs.

## Local validation

    python3 -m unittest discover -s skills/megabrain-existing-branch-fast-forward/tests -v
    python3 -m py_compile skills/megabrain-existing-branch-fast-forward/scripts/*.py

Hermetic validation does not contact GitHub, mint credentials, execute the installer, or execute the adapter's future mutation path.
