---
name: megabrain-github-app-auth
description: "Use when an explicitly authorized B4.1 read-only GitHub App probe is required."
version: 1.0.0
---

# MegaBrain GitHub App Auth Bootstrap

## B4.1 boundary

This versioned source provides exactly one B4.1 operation:

```text
probe-read-dev
```

It validates the fixed HTTPS origin `https://github.com/mide-lim/megabrain.git`,
uses an App JWT and installation token only in process memory, validates the
expected installation permissions and the exact `mide-lim/megabrain` scope, and
runs only `git ls-remote --heads origin refs/heads/dev` from an isolated empty
temporary directory. It then revokes the token and removes the temporary
askpass helper.

B4.1 is read-only. It has no Git write, push, branch, tag, pull-request, merge,
ruleset, bypass, administration, deployment, production, PAT, SSH, or arbitrary
Git/API/command interface. B4.2 is explicitly excluded and requires its own
contract and approval.

`--operational-gate-approved` is a process guardrail that records the caller's
acknowledgement of a separately approved operation. It is **not** a technical
security boundary and does not replace fresh human authorization. Do not run a
real operation without that authorization.

## Canonical source and installation

This repository directory is canonical source. It contains no App ID,
installation ID, private key, JWT, installation token, `.env`, or persistent
configuration. The installed profile skill is a derived artifact, never a
source of truth.

From the repository root, install or reinstall the exact derived artifact with:

```sh
python3 skills/megabrain-github-app-auth/scripts/install_skill.py
```

The default target is exactly:

```text
~/.hermes/skills/megabrain/megabrain-github-app-auth
```

The installer reconstructs only `SKILL.md` and `scripts/github_app_auth.py` from
this directory, atomically replacing an existing target. It does not read from
or copy from `~/.hermes`, does not read secret files, and does not create any
credential or configuration file. Reinstallation is the supported way to
refresh the derived artifact after an approved source update.

## Runtime interface

Run only from the checked-out MegaBrain repository after a fresh operational
authorization:

```sh
MEGABRAIN_GITHUB_APP_ID=... \
MEGABRAIN_GITHUB_APP_INSTALLATION_ID=... \
MEGABRAIN_GITHUB_APP_KEY_PATH=... \
python3 skills/megabrain-github-app-auth/scripts/github_app_auth.py \
  --operation probe-read-dev --operational-gate-approved
```

Supply these three values only through the runtime environment:

- `MEGABRAIN_GITHUB_APP_ID`
- `MEGABRAIN_GITHUB_APP_INSTALLATION_ID`
- `MEGABRAIN_GITHUB_APP_KEY_PATH`

Do not place them in a repository file, `.env`, Hermes configuration, command
history, output, or log. The key must be an existing regular file with no group
or other permissions (mode no broader than `0600`). The helper signs RS256 JWT
payload bytes through `openssl` without writing a JWT or token to disk.

The helper emits a single sanitized JSON result. It never prints the App ID,
installation ID, key path/content, JWT, token, authorization header, raw HTTP
response, askpass path/content, Git output, exception, or traceback.

## Hermetic validation

No credentials, network, real JWT, token, or GitHub operation are needed:

```sh
python3 -m unittest discover -s skills/megabrain-github-app-auth/tests -v
python3 -m py_compile \
  skills/megabrain-github-app-auth/scripts/github_app_auth.py \
  skills/megabrain-github-app-auth/scripts/install_skill.py \
  skills/megabrain-github-app-auth/tests/test_github_app_auth.py
```

The unit tests install and reinstall into a new temporary directory, compare
source/destination bytes and executable modes, and assert that the artifact set
contains no secret or configuration files. They mock signing, HTTP, and Git, so
no real credential or authenticated behavior is exercised.

## Failure and rollback

After a token is minted, the helper attempts revocation once in `finally`; a
revocation or temporary-askpass cleanup failure is reported as a sanitized
failure. It does not retain a token for retry. To remove a derived installation,
first confirm no helper is active, then remove only the target skill directory.
Do not alter the GitHub App, installation, repository configuration, rulesets,
or protected branches.
