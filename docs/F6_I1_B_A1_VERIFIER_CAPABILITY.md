# F6 I1-B A1 Verifier Capability

## Purpose

This source-only capability is the narrow future production-read path for the
corrected F6 I1-B authority verifier:

```text
infra/postgres/security/f6/008_i1_b_web_applicable_enrichment_read_verify.sql
```

It exists only to report the exact I1-B Web authority boundary. It is not a
generic PostgreSQL client, Docker gateway, migration runner, grant tool,
rollback tool, deployment tool, or production shell.

## Status and explicit non-authority

This repository change is source only.

```text
SOURCE IMPLEMENTED != INSTALLED
INSTALLED != VERIFIER EXECUTED
VERIFIER PASS != MIGRATION AUTHORIZED
MIGRATION AUTHORIZED != WEB DEPLOY AUTHORIZED
```

It does not install `/usr/local` files, modify `/etc/sudoers.d`, invoke sudo,
access Docker, connect to PostgreSQL, execute verifier 008, reapply grant 007,
execute migration 006 or rollback 009, alter n8n, or deploy Web.

The existing A1 gateway at `/usr/local/sbin/megabrain-hermes-ro` remains
untouched. Its `runtime-status`, `postgres-health`, and
`prod-schema-discovery` capabilities are unchanged.

## Why a separate Option B executable

The installed A1 dispatcher is root-owned, mode 700, and intentionally opaque
to `megabrain-hermes`; no tracked implementation or installer source exists.
Adding a capability to it would create an unnecessary regression path through
its three established operations.

The selected Option B design instead creates one future dedicated launcher:

```text
/usr/local/sbin/megabrain-hermes-i1-b-authority-verify
```

Its future sudo rule accepts only that executable with an empty argument list.
There is no generic `python`, `psql`, Docker, shell, path, SQL, container, or
environment parameter authority.

## Exact source pin

The source verifier is pinned to:

```text
canonical dev SHA:  29f314c06351d2f420aa1df54eea90d3d1b7396b
canonical dev tree: 49ee708df6ecc790c0e77e011a5d0d6a10f7f994
verifier Git blob:  b6651e8e9136bcd11faa4912e39df1c8c0099a22
```

The future installer must fetch only the canonical repository identity into a
root-owned staging clone. It must extract the verifier from the verified Git
object, never from the `megabrain-hermes` workspace.

At runtime, the launcher rejects the installed verifier unless it is a regular,
non-symlink root:root file with mode 0600 and its SHA-1 is computed using
canonical Git blob framing:

```text
SHA1("blob " + decimal byte length + NUL + file bytes)
```

The result must equal the pinned verifier blob before any Docker or PostgreSQL
operation starts.

## Fixed boundary

The public launcher CLI accepts zero arguments. It builds a minimal fixed
environment and does not inherit caller `PATH`, Docker, PostgreSQL, dynamic
loader, Python, or other authority-changing variables.

The future fixed Docker target is only:

```text
megabrain-postgres
```

The direct argv is fixed. A constant in-container shell fragment is used only
to expand `POSTGRES_USER` and `POSTGRES_DB` from the container's pre-existing
runtime environment. It accepts no caller content, prints neither value, and
uses `psql --no-password`. The installation gate must prove this fixed local
container authentication path works without adding or exposing credentials.

## One-session transaction model

Verifier 008 contains psql meta-commands, including `\set`, `\gset`, `\echo`,
`\if`, `\else`, and `\quit 3`. The launcher therefore streams all input to one
psql session:

```text
BEGIN TRANSACTION READ ONLY;
<exact pinned verifier bytes>
ROLLBACK;
```

On PASS, psql reaches the explicit `ROLLBACK` and exits 0. On a verifier
assertion failure, `\quit 3` terminates psql and its open read-only transaction
is rolled back on connection termination. SQL, Docker, parser, source-identity,
or audit failures are non-success.

## Output, exit, and audit contracts

The launcher accepts only the fixed named-check report grammar emitted by
verifier 008. Output is bounded to 16 KiB. Raw Docker and psql stderr is never
relayed. Unexpected, malformed, or oversized output fails closed.

```text
0   PASS
3   VERIFIER_ASSERTION_FAILURE from verifier 008 semantics
64  BOUNDARY_FAILURE
65  SOURCE_IDENTITY_FAILURE
70  OUTPUT_GRAMMAR_FAILURE
71  AUDIT_FAILURE
72+ RUNTIME_FAILURE or other non-success
```

The future root-controlled audit record contains only timestamp, operation
name, pinned verifier blob, result class, named check PASS/FAIL statuses, and
child exit status. It never records SQL, credentials, DSNs, environment,
container environment, raw stderr, or business rows. Audit write failure is
non-success.

## Future installation gate

A separate human authorization is required before executing
`install_i1_b_authority_verify.py`. The installer must:

1. require root and root-owned source staging;
2. verify canonical origin, dev SHA, tree, verifier path, and verifier blob;
3. stage the verifier from the verified Git object only;
4. install root:root launcher mode 0700, verifier mode 0600, and an empty
   root:root mode-0600 dedicated audit log atomically;
5. install the root:root mode-0440 exact sudoers fragment only after
   `visudo -cf` succeeds;
6. preserve the existing gateway and its sudo rules;
7. verify no Docker-group change, generic SQL path, generic Docker path, or
   host psql authority exists for `megabrain-hermes`;
8. use the same exact runtime-file identity checks for installation-failure
   cleanup that public rollback uses.

The only support directories the installer may create, if absent, are:

```text
/usr/local/lib/megabrain-hermes-ro
/usr/local/lib/megabrain-hermes-ro/i1-b
/var/log/megabrain-hermes-ro
```

They are dedicated root:root mode-0700 real directories. Existing valid
support directories are preserved and never repermissioned. Existing invalid
support directories fail closed. The installer never creates, repermissions,
or removes `/`, `/usr`, `/usr/local`, `/usr/local/sbin`, `/usr/local/lib`,
`/etc`, `/etc/sudoers.d`, `/var`, or `/var/log`.

## Pristine-install rollback and failure cleanup

Rollback is limited to a pristine, unexecuted installation. It may delete only
the four dedicated runtime files: the launcher, verifier, sudoers fragment, and
dedicated audit log. Public rollback is all-or-nothing with respect to
validation: before the first deletion, it validates that all four artifacts are
present, non-symlink regular root:root files with their exact expected modes
and content identities. Launcher, verifier, and sudoers identity use canonical
Git blob framing; the audit log must be exactly empty. A missing or invalid
member refuses the entire rollback and leaves every runtime artifact untouched.
A non-empty audit log is operational evidence that blocks the entire public
rollback, not merely deletion of the audit file. Each target is revalidated for
identity immediately before its unlink; a detected change stops later deletions.

Installation-failure cleanup applies the same checks and considers only files
published by that installer invocation. It prevalidates the complete
current-invocation published set before deleting any member, then deletes that
validated bounded set in reverse publication order. If a published target
changed after publication, cleanup refuses to unlink every published target.
Support directories created by that same failed invocation may be removed only
when they remain root:root, mode 0700, real, and empty; removal proceeds
deepest first. Public rollback has no later creation provenance and leaves
support directories in place.

Installing this capability does not execute verifier 008 and does not authorize
production verifier execution.

## Future execution gate

A later human gate must separately authorize exactly the dedicated zero-
argument launcher. Only that later lifecycle may execute verifier 008 against
production. A verifier PASS clears only the verifier blocker; it does not
authorize migration 006 or Web deployment.

## Hermetic security matrix

The dedicated unit suite uses fake process boundaries and simulated metadata;
it does not require root, sudo, Docker, PostgreSQL, network, `/usr/local`, or
`/etc` access. It covers zero-argument enforcement; SQL/path/container argument
rejection; sanitized environment behavior; fixed Docker command shape; Git blob
framing; wrong/modified verifier rejection; symlink/owner/group/mode rejection;
one-session read-only input and PASS rollback; assertion exit 3 preservation;
runtime, output-grammar, oversized-output, and audit failures; stderr
suppression; exact sudoers scope; installer root and identity preflight;
destination-symlink refusal; and dedicated rollback-path scope.
