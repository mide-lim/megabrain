# Task Contract — B2.1: Public Repository Security Preflight

## Status

- Status: READY
- Risk Level: GREEN

## Objective

Produce an evidence-based public-repository security audit and publication decision without publishing, changing GitHub, modifying credentials, rewriting history, or changing runtime behavior.

## User / Product Context

The target GitHub repository already exists and is public. Publication of MegaBrain history is effectively irreversible and needs a later explicit human gate. B2.1 is an audit/documentation delivery only.

## Scope

### In

- Complete current-tree and reachable-history audit for secret material, risky paths, metadata, n8n exports, documentation, binary/large objects, and `.gitignore`.
- Evidence-based publication verdict, remediation, public/private boundary, residual risk, and Hermes identity assessment.
- Independent review of methodology, findings, verdict, diff, and validation evidence.
- This Task Contract and the B2 active-task update.

### Out

- Push, fetch, merge, bundle, remote/origin change, GitHub setting/visibility/permission change, SSH change, credential rotation, history rewrite, deployment, Docker, production access, or runtime/application modification.

## Acceptance Criteria

- All tracked current files and all reachable Git history are inspected with complementary secret/path scans.
- Workflow identifiers are distinguished from secret material and sanitized where their exposure is unnecessary.
- The audit report contains every required section, finding IDs, severity/status, remediation, and exactly one publication verdict.
- The Task Contract reaches `READY` only after independent review completes.
- Documentation is concise, accurate, contains no secret value, and passes `git diff --check` plus a scan of the new documentation.

## Architecture / Technical Plan

Read-only audit of tracked content and every reachable blob. Record evidence without copying secret values. Classify operational metadata by public value and exposure. Treat publication as a separate irreversible human gate, not as a consequence of task readiness.

## UX Specification Reference

N/A.

## Contracts Changed

No runtime, API, database, workflow, GitHub, or production contract changes. Documentation adds a proposed public/private publication boundary only.

## Data / Migration Impact

N/A. No database or runtime data is accessed or changed.

## Security Impact

The delivery identifies current publication blockers and the future need for a constrained Hermes Git identity. It does not modify any live security control.

## Expected Files / Components

- `docs/PUBLIC_REPOSITORY_SECURITY_AUDIT.md`
- `docs/TASK_CONTRACT_B2_PUBLIC_PREFLIGHT.md`
- `docs/ACTIVE_TASK.md`

## Required Tests

- Current-tree and reachable-history secret-pattern scans.
- Historical risky-path and deletion review.
- n8n export metadata review.
- Binary/large-object and `.gitignore` review.
- `git diff --check`, final scope inspection, and a secret-pattern scan of the new documentation.
- Independent review.

## Required Evidence

- Branch/status inspection before and after documentation changes.
- Audit counts, scan results, findings, and final verdict in the report.
- Independent reviewer result.
- Final diff/status and local commit hash, if a local commit is created after review.

## Staging Requirements

N/A.

## Production Impact

None. Documentation-only GREEN work. Publishing to the existing public GitHub repository remains a separate RED human-gated action and is explicitly out of scope.

## Rollback / Recovery

Revert the local documentation commit if the audit record itself must be corrected. Any secret remediation, credential rotation, or history rewrite requires a separately approved task and must begin with rotation where applicable.

## Human Gates

- Explicit human approval is required before any public push.
- A separately approved remediation task is required for changes to tracked content, ignores, workflows, credentials, or history.
- A future B2 decision must approve and validate the constrained Hermes identity model before autonomous pushing.

## Dependencies

- Existing tracked repository and reachable history.
- Supplied external context about the existing public repository and owner-equivalent Hermes SSH identity.

## Open Questions

- Which identified operational metadata will be preserved with an explicit `PUBLIC_OK` rationale after sanitization review?
- Which provider-supported constrained identity model will satisfy the future B2 boundary?

## Final Evidence Summary

- All 64 tracked files and 39 reachable commits were scanned read-only. The audit covered 333 reachable objects and 142 unique blobs; no concrete private-key, GitHub, AWS, Slack, Telegram, or bearer-token signature was found in current content or reachable history.
- Historical risky-path review found seven tracked example/migration/workflow paths and no deleted path. There are no reachable binary blobs or blobs at or above 100 KB.
- Workflow review found 16 credential-reference objects, six Telegram chat identifier fields, seven webhook identifier fields, and two service URLs that require sanitization; the audit now classifies each as an identifier/metadata class rather than a secret value and records its required disposition.
- `git diff --check` and the concrete-secret signature scan of all three documentation files passed. The final scope is the three declared `docs/` files only.
- Independent security review: `BLOCKED` for publication. It required explicit workflow-class dispositions, a backup/export ignore recommendation that preserves versioned sanitized workflows, and scope-limited history wording; those corrections are now recorded. Follow-up independent QA PASS found no corrections.
- This Task Contract is `READY`; the repository remains `BLOCKED` for public publication. The audit report controls publication readiness.
