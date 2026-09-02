# Public Repository Security Audit — B2.1 Preflight / B2.2 Remediation

## B2.1 scope and threat model

This audit evaluates whether the complete MegaBrain Git history can be published without exposing credentials or unnecessary operational information. A public push makes every reachable commit and blob effectively durable and immediately available to automated scanners. This delivery is documentation only; it does not push, change GitHub, alter credentials, rewrite history, or access production.

## B2.1 audit methods

- Read all 64 tracked files, including documentation, infrastructure, services, migrations, skills, examples, and the four n8n exports.
- Enumerated all reachable refs and scanned 39 reachable commits, 333 reachable objects, and 142 unique blobs.
- Searched current content and historical blob content for private-key blocks; GitHub, AWS, Slack, Telegram, and bearer-token formats; and sensitive-assignment patterns. A second current-tree `git grep` and historical `git log -G` scan found no match for the concrete token/key formats.
- Reviewed every historical path matching `.env`, key, credential, secret, backup, dump, SQL, JSON, auth, or token names. The seven matches are the tracked example environment file, migrations, and versioned workflow exports. `git log --diff-filter=D` reported no deleted paths, so there is no high-risk deleted file to inspect.
- Checked operational metadata, workflow credential references, webhook and chat identifiers, URLs, binary objects, large blobs, and `.gitignore`.
- `git fsck --full --no-reflogs` found 14 dangling commits. A supplemental scan covered 156 unreachable blobs. They are not sent by an ordinary ref push; no concrete private-key or token signature matched. Generic assignment candidates remain outside publication scope and do not change the reachable-history verdict.

No automated secret scanner is installed in this environment; the complementary Git-native and custom pattern scans above were used instead.

## Findings

### PUB-001 — BLOCKER — REMEDIATED IN HEAD; OPEN IN REACHABLE HISTORY

**Unsanitized n8n operational identifiers in versioned exports.**

At B2.1, all four workflow exports contained 16 non-placeholder credential-reference objects. The first three contained six Telegram chat identifier fields and seven webhook identifier fields; two exports contained non-placeholder service URLs. These values are identifiers rather than credential material, and no hard-coded token, password, or private key was detected. The audit records only structural counts and classes, not identifier values. They nonetheless exposed unnecessary operational mapping and may expose webhook paths. `workflows/README.md` incorrectly stated that production IDs and credentials were replaced with placeholders.

**Required remediation:** replace credential IDs/names, chat IDs, webhook IDs, and service URLs with explicit placeholders; preserve only the workflow structure required for documentation; correct the README; then repeat the workflow audit.

| Workflow metadata class | Secret assessment | Publication classification | Required disposition |
| --- | --- | --- | --- |
| Credential reference ID/name | Identifier only; no credential payload was detected | SHOULD_SANITIZE | Replace with an explicit placeholder. |
| Telegram chat identifier | Operational/personal identifier; not a bot token | SHOULD_SANITIZE | Replace with an explicit placeholder. |
| Webhook identifier | Operational endpoint metadata; not a credential value | SHOULD_SANITIZE | Replace with an explicit placeholder because it may aid endpoint enumeration. |
| Service URL | Operational endpoint metadata; not a credential value | SHOULD_SANITIZE | Replace host/path with a placeholder unless a documented `PUBLIC_OK` rationale is approved. |

### PUB-002 — HIGH — ACCEPTED

**Production hostname in the Caddy configuration.**

`infra/Caddyfile` contains a fixed production n8n hostname rather than a variable or example. The hostname is not a secret, but it is unnecessary to explain the public architecture and associates the repository with an operational service.

**B2.2 disposition:** `ACCEPTED`. This is active runtime-sensitive configuration; changing it merely to obscure a publicly addressed service would alter the production contract and is excluded from this task. The hostname does not authenticate access, so publication security must not rely on concealing it. No Caddy change was made.

### PUB-003 — MEDIUM — ACCEPTED

**Unnecessary operational filesystem topology is versioned.**

`AGENTS.md` and B1 documentation record concrete production/local paths and Docker-socket paths. The paths do not contain credentials and architecture visibility is PUBLIC_OK, but the concrete topology is PUBLIC_BUT_UNNECESSARY or SHOULD_SANITIZE for a public repository.

**B2.2 disposition:** `ACCEPTED`. The remaining paths are either standard Docker-socket terminology needed to state the prohibited trust boundary or repository-relative paths. The one production-workspace path remains in `AGENTS.md`; an automated protection gate rejected its edit and no separate approval was received. It contains no credential and is retained as a narrow, explicit access boundary rather than treated as a publication secret.

### PUB-004 — MEDIUM — REMEDIATED

**At B2.1, `.gitignore` did not cover several public-repository risk classes.**

It correctly ignores environment files, runtime data, logs, Python caches, virtual environments, and `node_modules`. It does not cover common private-key/service-account formats, backup/dump directories and compressed dump formats, local credential files, or planned test/browser artifacts such as Playwright reports, traces, screenshots, and videos. SQL migrations must remain trackable, so a future rule must target backup/dump naming rather than all `.sql` files.

**Required remediation:** in a separate change, add narrow rules for non-versioned backup/export artifacts such as `infra/backups/`, `infra/dumps/`, `infra/exports/`, `*.dump`, `*.backup`, `*.bak`, `*.sql.gz`, and `*.sql.bz2`; then verify they do not hide intended source or migrations. Do not ignore `workflows/*.json`: sanitized workflow exports are intentionally versioned documentation and must remain trackable.

### PUB-005 — HIGH — ACCEPTED FOR PUBLICATION; OPEN FOR AUTONOMOUS AUTHORIZATION

**Hermes currently authenticates to GitHub as an owner-equivalent identity.**

The supplied external context establishes that this credential can create `agent/*` and has broader authority than the desired long-term Hermes boundary. This audit does not inspect or change SSH keys or GitHub permissions.

**Required remediation for B2:** validate a provider-supported constrained identity model before autonomous pushing becomes official. Candidate mechanisms include a dedicated identity, GitHub App, fine-grained credential, or controlled gateway; selection requires provider-specific validation. The resulting principal must not administer settings, secrets, protected branches, tags, reviews, merges, or deployments.

### PUB-006 — INFO — ACCEPTED

**No current-tree or reachable-history secret material detected.**

No private-key block or concrete GitHub, AWS, Slack, Telegram, or bearer-token format was found in the current tree or reachable history. This is limited to the named concrete patterns, sensitive-assignment context review, and all objects reachable from local refs at audit time; it is not a guarantee against novel or obfuscated secret formats. Sensitive-assignment matches were inspected as empty example settings, environment references/lookups, code identifiers, documentation examples, or test fixtures. No actual secret value is recorded in this report.

### PUB-007 — INFO — ACCEPTED

**No binary or large-object publication concern detected.**

There are no binary blobs and no reachable blob at or above 100 KB. No archive, video, database dump, generated runtime artifact, or other large object was found in reachable history.

## Operational metadata classification

| Classification | Evidence and reasoning |
| --- | --- |
| PUBLIC_OK | Service architecture, PostgreSQL/R2/n8n/Caddy roles, migrations, source, tests, and environment-variable names. These enable useful technical review without disclosing a credential. |
| PUBLIC_BUT_UNNECESSARY | Generic container names, internal service labels, and security-boundary descriptions. They are not secrets, but only the descriptions needed for reproducibility should remain. |
| SHOULD_SANITIZE | Fixed production hostname, concrete production/local paths, n8n credential names/IDs, Telegram chat IDs, webhook IDs, and workflow service URLs. These do not authenticate by themselves but add operational exposure without public-documentation value. |
| BLOCKING | The non-placeholder workflow operational identifiers collectively block a public push until sanitized. No actual credential value was found. |

## n8n workflow assessment

The current exports contain credential references only, not credential values. Their credential IDs/names, chat identifiers, webhook identifiers, service URLs, and node identifiers are explicit placeholders matching the documented full-string `__[A-Z0-9_]+__` grammar where applicable. `workflows/README.md` now accurately states that the exports preserve structure only and require operator-side configuration outside the public repository. Earlier reachable workflow blobs still contain non-placeholder credential names and service URLs; the current-tree remediation cannot clear that historical exposure.

## Documentation assessment

Documentation contains no detected credential material. The remaining production-workspace and standard Docker-socket references are classified explicitly in PUB-003. The public architecture remains useful and is not removed for obscurity.

## Recommended public/private boundary

**Public source:** application code, migrations, architecture, tests, skills, design system, sanitized workflows, and sanitized examples.

**Private operations:** runtime `.env`, credentials, service-account keys, backups, runtime data, real webhook/chat/credential identifiers, and incident/debug artifacts containing sensitive values.

**Optional/review:** hostnames, usernames, paths, bucket names, workflow IDs, and internal service URLs. Keep them only when they provide concrete public value and have a documented classification.

## Residual risks

- Pattern scanning cannot prove the absence of a novel or obfuscated credential format.
- This environment has no installed dedicated secret-scanning tool; the audit used read-only custom and Git-native scans.
- The supplemental dangling-object scan is not evidence about content that an ordinary ref push publishes.
- Even after remediation, publication remains a separate irreversible human gate. This audit does not authorize pushing.

## B2.2 remediation and re-audit

### Scope and methods

- Parsed all four current workflow exports and inspected every credential-reference ID/name, webhook ID, literal Telegram chat ID, service URL, and UUID-like node ID without copying identifier values into this report.
- Repeated current-tree and reachable-history scans for private-key blocks; GitHub, AWS, Slack, Telegram, and bearer-token formats; and sensitive-assignment patterns, followed by context review.
- Enumerated every local ref, commit, object, and historical workflow blob. The historical workflow review is separate from the current-tree result because an ordinary public push publishes reachable prior commits.
- Reviewed `.gitignore` coverage, risky paths, documentation, binaries, and large objects. The proposed ignore patterns do not match the tracked workflow exports or SQL migrations.

### Current-tree result

`REMEDIATED` for workflow metadata and ignore-policy gaps. All 16 credential-reference ID/name pairs in the current exports match the documented placeholder grammar; the two internal service URLs, all node IDs, existing webhook IDs, and the authorized-chat value also match it; no literal chat ID remains. Workflow topology, node types, expressions, and SQL queries are unchanged.

No concrete private-key or named provider-token signature was detected in the current tree by the stated scans. This is scope-limited evidence, not proof against novel or obfuscated formats. No current-tree binary or large-object publication concern was found.

### Reachable-history result

`BLOCKED`. Across all local refs, the re-audit found 41 reachable commits, 344 reachable objects, 147 reachable blobs, and seven unique workflow blobs. Historical workflow blobs retain non-placeholder credential names and internal service URLs. These are operational identifiers rather than credential payloads, but they are the same metadata classes remediated in HEAD and would be disclosed by publication of the complete reachable history.

No concrete private-key or named provider-token signature was detected in reachable history by the stated scans. This does not remove the workflow-metadata blocker. No reachable binary or blob at or above 100 KB was found.

### Required next step

Do not rewrite history automatically. A separately approved history-remediation task must define the protected refs, affected commits/blobs, operator access model, any required credential rotation, validation, rollback, and explicit human publication gate. Until then, the repository must not be publicly pushed.

## B2.1 independent review

The independent security reviewer returned `BLOCKED` for publication, confirming that PUB-001 and the ignore-policy gap prevent release clearance. It required an explicit per-class workflow disposition, a repository-specific non-versioned backup/export ignore recommendation that preserves sanitized workflow exports, and a scope-limited statement of historical scan coverage. Those documentation corrections are recorded above. Follow-up independent QA passed with no corrections: it confirmed the workflow classification, ignore recommendation, coverage wording, and distinction between B2.1 task readiness and the repository publication verdict. Neither review changes the repository verdict from `BLOCKED`.

## B2.1 historical conclusion

The B2.1 audit work became READY after independent review and recorded a blocked publication state. B2.2 supersedes that current-state conclusion below.

## B2.2 independent review

Independent security/QA review: `PASS`. It confirmed all four workflow exports parse; the documented full-string placeholder grammar covers 16 credential IDs, 16 credential names, seven webhook IDs, 33 node IDs, two service URLs, and the authorized-chat value; workflow structure and logic are unchanged; and the ignore rules are narrow. It also confirmed that no runtime-sensitive file changed, concrete secret signatures were absent from the current tree and reachable history under the stated scan patterns, and the review scope supports `READY` task status while keeping publication `BLOCKED` for reachable historical workflow metadata. No history rewrite, push, or production access occurred.

## B2.2 final verdict

**BLOCKED**

The current tree is remediated for workflow operational identifiers and `.gitignore` coverage. Publication is still blocked because reachable historical workflow blobs retain the pre-remediation credential-name and internal-service-URL metadata. PUB-002 and PUB-003 are accepted, documented decisions with no runtime change. PUB-005 is not a publication blocker, but its least-privilege identity requirement remains open before autonomous agent pushes become official. This verdict does not authorize a history rewrite or public push.
