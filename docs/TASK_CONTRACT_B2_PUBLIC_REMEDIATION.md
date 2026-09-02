# Task Contract — B2.2: Public Repository Remediation

## Status

- Status: READY
- Risk Level: YELLOW

## Objective

Sanitize the current public repository content and safety controls identified by B2.1, then repeat the complete current-tree and reachable-history audit without changing production runtime behavior, credentials, GitHub, remotes, or history.

## Scope

### In

- Versioned n8n workflow-export metadata, `workflows/README.md`, and workflow JSON validation.
- Narrow `.gitignore` rules for local secret material, backup/export artifacts, and browser/test artifacts.
- Re-audit documentation, current content, all reachable Git objects, operational metadata, risky filenames, binary/large objects, and ignore coverage.
- Update the canonical audit, active-task state, and this Task Contract.
- Independent security review of the complete remediation and evidence.

### Out

- Push, GitHub changes, remote changes, history rewrite, credential or SSH changes, deployment, Docker, production access, production secrets, and runtime configuration changes.

## Risk

YELLOW: the delivery changes versioned workflow exports, repository safety controls, and operational documentation. Sanitization and ignore rules are low-risk; any runtime-sensitive configuration change is excluded and must be a separate approved Yellow or Red task.

## Acceptance Criteria

- Current workflow exports use explicit, consistent placeholders for credential IDs/names, chat IDs, webhook IDs, service URLs, and node identifiers that lack public documentation value. The placeholder grammar is a full-string `__[A-Z0-9_]+__` marker and is documented in `workflows/README.md`.
- Workflow topology, node types, expressions, queries, and documented logic remain intact.
- `workflows/README.md` accurately states the public/export boundary and operator restoration requirement.
- `.gitignore` adds narrow risk-class rules without ignoring workflow JSON or SQL migrations.
- The audit preserves B2.1 findings, records a current state for each, distinguishes HEAD from reachable-history results, and has exactly one publication verdict.
- JSON parsing, placeholder consistency, current-tree secret-pattern scanning, reachable-history scanning, scope inspection, runtime-sensitive-diff inspection, and independent review pass.

## Changes

- Sanitized names of credential references, internal service URLs, and a UUID-like node identifier in all four versioned workflow exports.
- Added narrow ignore rules for local credential, backup/export, and test-browser artifact classes.
- Updated the workflow-export documentation and B2 task/audit records.
- No runtime-sensitive file is changed.

## Validation

- Parse every `workflows/*.json` file with Python `json`.
- Verify every credential ID/name, webhook ID, literal Telegram chat ID, service URL, and node ID in the current workflow exports matches the documented full-string placeholder grammar where applicable.
- Scan the current tree and all reachable Git history for concrete private-key and common provider-token formats, with sensitive-assignment matches reviewed by context.
- Review historical workflow blobs separately from the current tree.
- Check tracked paths against the new ignore patterns, run `git diff --check`, and inspect the exact changed-file and runtime-sensitive scope.

## Evidence

- The pre-change audit established 41 reachable commits and seven unique workflow blobs across all local refs.
- The remediation re-audit covers 41 reachable commits, 344 objects, and 147 blobs. It records current-tree and historical results in `PUBLIC_REPOSITORY_SECURITY_AUDIT.md` without reproducing sensitive values.
- JSON parsing passed for all four exports. The documented placeholder grammar passed for 16 credential IDs, 16 credential names, seven webhook IDs, 33 node IDs, two service URLs, and the authorized-chat value; no literal chat ID remains.
- `git diff --check`, explicit new-file whitespace validation, current-tree/reachable-history concrete-secret signature scans, ignore-policy probes, changed-scope inspection, and runtime-sensitive-diff inspection passed.
- Independent security/QA review: PASS. It confirmed the task is `READY`, publication remains `BLOCKED`, no runtime-sensitive file changed, and a separate approved reachable-history remediation is required.

## Human Gates

- Explicit human approval is required before any public push.
- Any reachable-history rewrite is a separate approved task; it is not authorized here.
- A constrained, least-privilege Hermes GitHub identity remains required before autonomous agent pushes become official; that authorization boundary is separate from publication security.
- Any runtime-sensitive configuration change requires a separate approved task.

## Rollback

Revert the local remediation changes to restore the prior versioned exports and documentation. No runtime system, credential, or remote state is touched by this delivery. A future history-remediation task must define its own backup, rotation, approval, and rollback plan.

## Final Result

`READY` for the B2.2 task. The current-tree remediation and validation evidence are complete, but publication remains `BLOCKED` because reachable historical workflow blobs retain operational metadata. A separately approved history-remediation task and explicit human publication gate are required; neither is authorized by this delivery.
