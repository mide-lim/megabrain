# AP0-TC2 — Control Plane Registry & Admission Contract

Status: proposed canonical contract for AP0; specification only
Date: 2026-09-29
Canonical predecessors:

- `docs/platform/autonomy/AP0_RUNTIME_BASELINE.md` — verdict `AP0_TC0_BLOCKED`
- `docs/platform/autonomy/AP0_RUNTIME_OWNERSHIP_CONTRACT.md` — verdict `AP0_TC1_CONTRACT_READY`

Scope boundary: this contract creates no datastore, registry entry, runtime resource, process, preview, worktree, cleanup action, Docker/systemd configuration, firewall/SSH configuration, production mutation, Git mutation, push, pull request, or merge.

## 1. Goals and invariants

AP0 establishes a durable control-plane protocol that makes ownership, authority, and lifecycle evidence available before autonomous runtime resources are used. It operationalizes the TC1 relationship:

```text
TASK -> RESOURCE LEASE -> runtime resource
```

The canonical creation direction is:

```text
REQUEST
  -> TASK REGISTERED
  -> POLICY / ADMISSION CHECK
  -> RESOURCE LEASE ALLOCATED
  -> RUNTIME RESOURCE CREATED
  -> IDENTITY READBACK
  -> ACTIVE
```

The control plane is authoritative for Task identity/state, Resource Leases, permitted operations, risk class, budgets, gates, heartbeats, checkpoints, and audit history. It is not authoritative for Git content, application business data, production configuration, provider secrets, Docker internals, or terminal history.

Invariants:

1. No autonomous runtime resource may be created or used before a Task and a Resource Lease establish canonical ownership.
2. Every `TASK`, `RESOURCE_LEASE`, `AUDIT_EVENT`, `HEARTBEAT`, `GATE`, and `CHECKPOINT` record carries a supported `schema_version`.
3. Task and resource identifiers are immutable, opaque, globally unique, non-semantic, and never reused.
4. A Resource Lease binds exactly one resource to exactly one Task for that lease lifetime. A resource cannot be concurrently leased to more than one Task.
5. Runtime evidence corroborates ownership; it never replaces the canonical registry.
6. `ALLOCATED` is not `ACTIVE`. `ACTIVE` requires exact post-create identity readback and durable identity binding.
7. A missing heartbeat is evidence of missing liveness reporting, not proof of process death and not cleanup authorization.
8. Reconciliation is read-only. It can mark drift or unknown ownership but cannot stop, delete, or adopt a resource.
9. Unknown legacy resources retain `UNKNOWN`, `UNOWNED_UNKNOWN`, or `STALE_CANDIDATE` status unless evidence and an authorized human decision establish a different result.
10. Canonical ownership must remain durable across Hermes restart and terminal disconnect. Hermes is a control-plane client/event producer, never the sole state store.
11. Mutation fails closed when canonical ownership, authorization, supported schema, audit persistence, or identity readback cannot be established.
12. AP0 grants no cleanup authority beyond metadata/evidence handling. Any future C1/C2 cleanup requires its own authorization and Janitor contract; C3/C4 remain outside AP0 autonomous authority.

## 2. Component boundaries

```text
                    HUMAN / ROADMAP
                          |
                          v
                    Task Request
                          |
                          v
                +--------------------+
                |   CONTROL PLANE    |
                |                    |
                | Tasks              |
                | Resource Leases    |
                | Audit Events       |
                | Heartbeats         |
                | Gates              |
                | Checkpoints        |
                | Budgets            |
                +---------+----------+
                          |
                          v
                       HERMES
                      Tech Lead
                          |
                          v
                  Worker Manager
                          |
                          v
                       Workers
```

Control-plane boundary:

- The control plane persists canonical records and executes transactional admission decisions.
- Hermes consumes Task/lease/gate state, requests admission, emits structured events, and coordinates bounded workers.
- Worker Manager creates resources only after a successful admission result and reports exact identity evidence back to the control plane.
- Workers receive only capability-scoped Task/lease references and cannot query or alter arbitrary registry records.
- Read-only adapters collect bounded host, Git, preview, Docker, and security evidence. They do not expose arbitrary shell, Docker socket, arbitrary file read, or mutation capabilities.

The control plane does not own:

- repository contents, commits, branch policy, or pull-request state;
- MegaBrain product records or production PostgreSQL;
- Docker lifecycle, images, volumes, or socket access;
- terminal transcripts, shell history, provider-secret values, or production configuration.

Repository Task Contracts remain governance/specification artifacts. They may be referenced by immutable evidence identifiers, but a repository document does not overwrite runtime Task state, and runtime state does not rewrite Git history.

## 3. Record families

AP0 has exactly these minimum persisted canonical families. Product-domain records are out of scope.

### TASK

A Task is one finite, bounded unit of autonomous work.

```text
TASK {
  schema_version: SemVer
  task_id: TaskId
  requester: IdentityRef
  created_by: IdentityRef
  created_at: UtcTimestamp
  state: CREATED | READY | RUNNING | PAUSED | BLOCKED | VALIDATING | REVIEW | TERMINAL
  risk_class: GREEN | YELLOW | RED | UNKNOWN
  task_contract_ref: EvidenceRef | N/A
  allowed_operations: [OperationGrant]
  resource_budget: ResourceBudget
  prerequisite_status: PrerequisiteStatus
  pause_reason: PauseReason | N/A
  terminal_result: TerminalResult | N/A
  current_checkpoint_id: CheckpointId | N/A
  revision: NonNegativeInteger
}
```

`allowed_operations` is an explicit allowlist containing operation class, bounded target scope, authority requirement, and any matching gate requirement. It does not report ambient host capability.

`ResourceBudget` at minimum limits workers, processes, previews, worktrees, temporary bytes, artifact bytes, and total runtime duration. `UNKNOWN` is not a valid budget at admission; it blocks allocation of the relevant resource type.

Task lifecycle:

```text
TASK_REQUESTED -> CREATED -> READY -> RUNNING -> VALIDATING -> REVIEW -> TERMINAL
                                  |       |          |
                                  v       v          v
                                PAUSED <-----------+
                                  |
                                  v
                                BLOCKED

BLOCKED -> READY only after an auditable prerequisite or authority resolution.
PAUSED -> READY or RUNNING only after the recorded resume policy succeeds.
TERMINAL permits no new worker, process, preview, or task-worktree allocation.
```

### RESOURCE_LEASE

A Resource Lease is the durable ownership and allocation record for one resource.

```text
RESOURCE_LEASE {
  schema_version: SemVer
  resource_id: ResourceId
  task_id: TaskId
  resource_type: WORKER | PROCESS | PREVIEW | WORKTREE | TEMP_DIR | TEST_ENV | ARTIFACT | DELEGATED_RUN
  created_at: UtcTimestamp
  created_by: IdentityRef
  state: ALLOCATED | ACTIVE | IDLE | TERMINAL | HEARTBEAT_MISSED | STALE_CANDIDATE
  requested_operation: OperationGrantRef
  budget_reservation: BudgetReservation
  expected_identity: TypedIdentityExpectation
  bound_identity: TypedIdentity | N/A
  heartbeat_policy: HeartbeatPolicy | N/A
  ttl_policy: TtlPolicy | N/A
  retention_class: EPHEMERAL | REVIEW | EVIDENCE | HANDOFF | PERSISTENT_APPROVED
  terminal_reason: TerminalReason | N/A
  revision: NonNegativeInteger
}
```

`ALLOCATED` records the attempted resource allocation before runtime creation. `bound_identity` is immutable once `ACTIVE`, except that a later state record can preserve a new readback observation without replacing the original binding. Failed creation terminalizes the lease with `RESOURCE_CREATION_FAILED`; it does not erase the lease.

### AUDIT_EVENT

Audit events are append-only facts about an attempted, completed, refused, or observed control-plane transition.

```text
AUDIT_EVENT {
  schema_version: SemVer
  event_id: EventId
  sequence: PositiveInteger
  occurred_at: UtcTimestamp
  recorded_at: UtcTimestamp
  event_type: EventType
  task_id: TaskId | N/A
  resource_id: ResourceId | N/A
  gate_id: GateId | N/A
  checkpoint_id: CheckpointId | N/A
  actor: IdentityRef
  correlation_id: CorrelationId
  payload_type: String
  payload: TypedSanitizedPayload
  previous_event_hash: Sha256Hex | N/A
  event_hash: Sha256Hex
}
```

Minimum event types include `TASK_REQUESTED`, `TASK_CREATED`, `TASK_READY`, `TASK_BLOCKED`, `TASK_PAUSED`, `TASK_RESUMED`, `RESOURCE_ALLOCATED`, `RESOURCE_CREATION_FAILED`, `IDENTITY_BOUND`, `RESOURCE_ACTIVE`, `HEARTBEAT_RECORDED`, `HEARTBEAT_MISSED`, `CHECKPOINT_CREATED`, `GATE_REQUESTED`, `GATE_DECIDED`, `RECONCILIATION_RECORDED`, `RESOURCE_TERMINAL`, and `AUDIT_APPEND_FAILED` when an external durable incident channel is available.

### HEARTBEAT

A Heartbeat is a normalized liveness observation and may also be represented by its corresponding append-only `HEARTBEAT_RECORDED` event. The family exists as a queryable current/history projection, not as a substitute for audit history.

```text
HEARTBEAT {
  schema_version: SemVer
  heartbeat_id: EventId
  task_id: TaskId
  resource_id: ResourceId | N/A
  producer: IdentityRef
  sequence: NonNegativeInteger
  producer_monotonic_ns: NonNegativeInteger | N/A
  observed_at: UtcTimestamp
  received_at: UtcTimestamp
  status: EXPECTED | PAUSED | COMPLETING | FAILED | UNKNOWN
  evidence_ref: EvidenceRef | N/A
}
```

### GATE

A Gate represents a human authority decision for one exact operation scope.

```text
GATE {
  schema_version: SemVer
  gate_id: GateId
  task_id: TaskId
  requested_operation: OperationGrant
  risk_class: GREEN | YELLOW | RED | UNKNOWN
  requested_at: UtcTimestamp
  requested_by: IdentityRef
  required_authority: AuthorityRequirement
  status: PENDING | APPROVED | DENIED | EXPIRED | CONSUMED
  approved_by: IdentityRef | N/A
  approved_at: UtcTimestamp | N/A
  expires_at: UtcTimestamp | N/A
  authorization_reference: String | N/A
  consumed_by_event_id: EventId | N/A
}
```

Approval is bound to exact operation type, task, target/scope, budget exception if any, and expiry. A general approval, a matching title, or an unrelated task cannot satisfy a Gate.

### CHECKPOINT

A Checkpoint is a resumable, secret-free Task snapshot. It is immutable; a new checkpoint supersedes a prior one by reference rather than overwrite.

```text
CHECKPOINT {
  schema_version: SemVer
  checkpoint_id: CheckpointId
  task_id: TaskId
  created_at: UtcTimestamp
  created_by: IdentityRef
  task_state: TaskState
  last_successful_operation: OperationRef | N/A
  git_context: GitCheckpointContext | N/A
  active_resources: [ResourceCheckpointRef]
  pending_validation: [ValidationRef]
  next_permitted_action: OperationGrant | N/A
  blocking_reason: BlockingReason | N/A
  provider_state: ProviderPauseState | N/A
  evidence_refs: [EvidenceRef]
}
```

## 4. Storage comparison

The selected datastore must be durable through Hermes restart and terminal disconnect, transactional, locally recoverable, append-safe for audit, schema-versioned, independent of production PostgreSQL/Docker/terminal history, and portable to Paperclip.

| Candidate | Durability and transactions | Operations and concurrency | Backup / corruption recovery | Access control | Migration / Paperclip portability | AP0 assessment |
|---|---|---|---|---|---|---|
| Dedicated control-plane SQLite database | Durable single-file database with WAL mode, atomic transactions, foreign keys, and crash recovery when correctly configured. Single-writer serialization fits AP0 admission. | Low operational complexity; local process/service can serialize mutation. Concurrent readers are practical; sustained multi-host writers are not. | Consistent online backup API or quiesced copy; `integrity_check`; restore into isolated path; retain WAL-aware backup procedure. | Owner-only file permissions plus a narrow local control-plane service/API. Do not expose raw database path to workers. | Portable relational schema and explicit export/import envelopes; no provider dependency. | Recommended AP0 MVP. |
| Dedicated PostgreSQL database/schema | Strong durability, transactions, row locking, and multi-writer concurrency. | Higher operational cost: server lifecycle, credentials, backups, monitoring, roles, and local availability. A separate instance/schema still adds operational authority. | Mature backup/PITR and recovery, but requires operating a database service. | Strong database roles possible, but credential issuance/rotation becomes a new security surface. | Portable, but unnecessary complexity before multi-host control-plane needs are proven. | Not recommended for AP0 MVP; reconsider for Paperclip/multi-host phase. |
| Filesystem JSON plus event log | Atomic rename can protect individual files; cross-record transactions, constraints, and safe concurrent mutation require custom implementation. | Low initial complexity becomes high when locks, ordering, deduplication, compaction, corruption handling, and concurrent writers are added. | Simple copies possible, but partial writes/log truncation/lock recovery require bespoke protocol. | Filesystem permissions only unless wrapped in a service. | Export is easy; reliable import/history semantics must be invented. | Rejected: too much correctness-critical database behavior would be custom. |
| Hermes existing `~/.hermes/state.db` | It is a SQLite store, but its durability/transaction behavior serves Hermes internal session state, not an AP0 registry contract. | Hermes owns its schema and migrations. Control-plane changes could contend with or be invalidated by Hermes implementation changes. | Hermes-specific backup/recovery semantics are not an AP0 contract. | Current file is owner-only, but direct access couples workers/control plane to Hermes internals. | Internal tables are not a stable external contract. | Rejected as canonical storage. It may remain a non-canonical event source only. |

The observed `~/.hermes/state.db` contains Hermes session/transcript/routing/delegation/gateway tables such as `sessions`, `messages`, `async_delegations`, and `gateway_heartbeats`; it has no documented AP0 Task/Lease/Gate registry boundary. Its SQLite integrity is not evidence that its internal schema is a stable control-plane API. The AP0 source of truth must not depend on it.

## 5. Recommended AP0 storage

Use exactly one AP0 MVP storage boundary: a dedicated local control-plane SQLite database, owned by a narrow local control-plane service, separate from `~/.hermes/state.db` and separate from production PostgreSQL.

Requirements for the later implementation:

1. Store the database beneath a dedicated control-plane state directory with owner-only permissions. Resolve the directory through a future AP0 configuration contract; do not reuse Hermes internal state paths.
2. Enable SQLite foreign keys and WAL mode; use short transactional writes with an explicit busy timeout appropriate to the local service.
3. Permit all mutations only through a versioned local control-plane API/service. Hermes, Worker Manager, and workers do not write SQLite files directly.
4. Serialize admission and budget reservations inside one database transaction. This prevents two concurrent requesters from exceeding a budget or allocating the same exclusive resource identity.
5. Maintain normalized current-state tables for the six record families and an append-only audit-event table. Mutable current state must identify the audit event that produced it.
6. Use an outbox/pending-event mechanism within the same transaction for any later asynchronous delivery. An external transport failure must not make a local admission appear durable when it is not.
7. Never store provider secrets, raw environment dumps, terminal history, raw Docker inspect output, SSH private-key data, or password material.
8. Do not create the datastore in TC2.

This is a local, single-host AP0 control-plane boundary. It does not claim multi-host high availability. Loss of the host/disk remains a recovery event requiring backup restore and reconciliation.

## 6. Identity model

All identifiers are immutable, opaque strings generated from a cryptographically secure random UUIDv7-compatible 128-bit value, encoded in lowercase canonical UUID text. UUIDv7 provides sortable creation locality but no authorization or semantic meaning. A collision check occurs within the allocation transaction; collision retry is bounded and audited.

Formats:

```text
task_id       = task_<uuidv7>
resource_id   = rsrc_<uuidv7>
event_id      = evt_<uuidv7>
gate_id       = gate_<uuidv7>
checkpoint_id = chk_<uuidv7>
correlation_id = corr_<uuidv7>
```

Examples are format illustrations only: `task_018f3d4a-7b8c-7c9d-8e1f-0123456789ab`.

Rules:

- Prefixes identify record family only; the UUID portion remains non-semantic.
- IDs are never derived from PID, process start time, port, branch, path, title, requester name, or timestamp alone.
- IDs remain unchanged when a Task is paused, resumed, migrated, imported into Paperclip, or reconciled.
- Human-readable labels are non-authoritative metadata and cannot be used as a registry key.
- `correlation_id` groups one request across Task, lease, gate, and event activity. It is not a substitute for a Task ID and may span multiple events.
- Runtime identities such as `(pid, start_time, boot_id)` are typed evidence attached to a Resource Lease; they are not canonical resource IDs.

## 7. Schema versioning

Each canonical record includes `schema_version` as a semantic version (`MAJOR.MINOR.PATCH`). The persisted database also has a registry-level schema migration version. A record is valid only when both the database migration and its declared record version are compatible with the executing control-plane service.

Compatibility policy:

| Condition | Read-only diagnostics | Mutation / admission behavior |
|---|---|---|
| Supported version: same major; known fields; supported minor/patch | Parse and display normally. | Permitted if all other checks pass. |
| Upgrade required: known older major/minor that an installed explicit migration can upgrade transactionally | Expose `UPGRADE_REQUIRED` and migration plan. | Block until migration completes and is integrity-checked. No partial admission. |
| Unknown future version: major is newer or required fields/semantics are unknown | Expose record identity and `UNSUPPORTED_FUTURE_VERSION` without interpreting unknown semantics. | Fail closed. No mutation, allocation, gate consumption, resume, or cleanup request. |
| Invalid version: missing, malformed, inconsistent with payload, or unsupported historical version | Expose `INVALID_SCHEMA_VERSION` diagnostic. | Fail closed. Preserve evidence and require repair/recovery procedure. |

Rules:

1. Writers emit only one currently supported canonical version per record family.
2. Every schema migration is transactional where SQLite permits it, versioned, idempotence-checked, and recorded in audit metadata before new writes are admitted.
3. A reader may preserve unknown fields during export/import but must not infer their meaning.
4. Unknown versions never become valid through default values or best-effort field dropping.
5. Event payload types are versioned independently from their envelope. Unsupported event payloads remain retained and visible as opaque diagnostic references.

## 8. Task admission

Task admission is the only path from a request to `READY`. No worker starts before successful Task admission.

```text
TASK_REQUESTED
  -> validate requester identity
  -> validate Task Contract reference and immutable scope summary
  -> validate risk class and required authority
  -> validate allowed operations and explicit target boundaries
  -> validate resource budget and prerequisites
  -> assign task_id
  -> transaction: persist TASK_CREATED + TASK_REQUESTED audit events
  -> evaluate admission
       -> READY
       -> BLOCKED
       -> HUMAN_GATE_REQUIRED
```

Protocol:

1. The requester submits an authenticated typed `IdentityRef`, bounded Task Contract reference, requested operations, risk class, and resource budget.
2. The control plane validates that the requester is recognized by the AP0 identity provider/bound local policy. Unknown identity fails closed.
3. The control plane validates the Task Contract reference as an immutable evidence reference; it does not trust a branch name or mutable file path alone.
4. The control plane checks risk classification, required gates, operation allowlist, budgets, host-policy prerequisites, and dependency state.
5. In one transaction, generate `task_id`, persist the Task in `CREATED`, append `TASK_REQUESTED` and `TASK_CREATED`, and reserve no runtime resource yet.
6. If all requirements are satisfied, transition to `READY` and append `TASK_READY`.
7. If a human decision is required, create a `GATE` in `PENDING`, append `GATE_REQUESTED`/`HUMAN_GATE_REQUIRED`, and set the Task to `BLOCKED` or `REVIEW` according to policy. A pending gate is not an implicit approval.
8. If a prerequisite fails, set `BLOCKED` with a typed blocking reason and audit event. Do not allocate resources.

Admission validation is deterministic for the same request, policy version, and observed prerequisite evidence. Material scope changes require an auditable Task amendment or a successor Task; a mutable title or branch movement cannot silently expand authority.

## 9. Resource admission

Every resource uses an explicit two-phase admission. Allocation and runtime creation are separate to preserve failure evidence.

```text
REQUEST RESOURCE
  -> verify Task exists and is not TERMINAL
  -> verify Task state permits this resource type
  -> verify requested operation is allowed
  -> verify matching approved Gate, if required
  -> verify and reserve budget
  -> allocate resource_id
  -> transaction: persist RESOURCE_ALLOCATED / ALLOCATED lease
  -> create runtime resource through bounded manager
  -> read back exact identity through adapter
  -> transaction: persist IDENTITY_BOUND + RESOURCE_ACTIVE / ACTIVE lease
```

If creation fails:

```text
ALLOCATED lease
  -> persist RESOURCE_CREATION_FAILED
  -> release only the unused budget reservation in the same terminalization transaction
  -> terminalize lease with failure reason and retained request/expected identity evidence
```

The lease history remains immutable. A failed resource ID is never reused.

Admission requirements:

- Task must exist in `READY`, `RUNNING`, `VALIDATING`, or another explicitly permitted state for that resource class. `PAUSED`, `BLOCKED`, and `TERMINAL` deny new worker/process/preview/worktree admission by default.
- The Task’s allowed operation must match type, target boundary, scope, and gate reference.
- Budgets are reserved atomically against active and allocated leases. Budget overruns fail closed.
- Resource allocation is idempotent only for the same idempotency key, Task, resource type, and normalized request digest. A changed request receives a new admission decision; it cannot reuse a lease accidentally.
- Exact identity readback is required before `ACTIVE`. A manager can retry readback only within the same bounded creation operation and cannot start work before successful binding.
- Creation may produce an unbound runtime artifact only during the bounded create/readback interval. If binding fails, it must be treated as an admission failure and be surfaced for authorized recovery; it must not receive autonomous work.

## 10. Register-before-use

The control plane uses the generic sequence `ALLOCATED -> CREATE -> IDENTITY_BIND -> ACTIVE`. The lease is persisted before creation. Each resource class has the following minimum contract.

| Resource | Pre-registration and expected identity | `ACTIVE` readback requirement | Fail-closed behavior |
|---|---|---|---|
| `WORKER` | Allocate worker lease with task, bounded command profile, declared cwd/worktree, timeout, expected supervisor identity. | PID + process start time + boot ID + process group + cwd + executable evidence. | Do not grant work. Record bind failure; manager stops issuing commands. |
| `PROCESS` | Allocate a separate lease when it can outlive its worker, bind a port, retain credentials, or materially consume resources. | `(pid, start time, boot ID)` plus parent/process-group/cwd/executable evidence. | Do not treat a PID-only match as ownership; block dependent work. |
| `PREVIEW` | Allocate preview lease with bind policy, requested port strategy, worktree/branch/HEAD, health endpoint, TTL. | Listener bind address/port, backing process/container identity, health result, Task lease, branch, HEAD. | Port collision or mismatch terminalizes allocation; no alternative listener is adopted. |
| `WORKTREE` | Allocate lease with intended location category, branch/base/HEAD, retention class, expected lock/dirty policy. | Repository identity, absolute path, registered-worktree state, branch, HEAD, base, dirty, lock state. | Dirty, locked, wrong repo, wrong base/HEAD, or existing unknown path blocks use. |
| `TEMP_DIR` | Allocate lease with generated child path/nonce, filesystem boundary, intended class, byte budget, retention. | Exact path plus filesystem device/inode where available and lease marker/metadata when safe. | Do not use a discovered matching directory; mark unknown if identity cannot bind. |
| `TEST_ENV` | Allocate with worktree, toolchain/lock reference, isolation boundary, timeout, and budget. | Exact path or process/container identity, toolchain evidence, worktree evidence, active executor if applicable. | Do not run tests in an unbound/shared environment. |
| `ARTIFACT` | Allocate before producing retained artifact with producer resource, retention class, expected output type, byte budget. | Immutable content digest and storage/path evidence, producer link, size. | Do not mark produced output as task artifact without producer/identity evidence. |
| `DELEGATED_RUN` | Allocate with parent worker, delegate identity, approved task scope, workspace, timeout, provider policy. | Delegate-run identity, parent relation, workspace/worktree, bounded result/evidence reference. | Do not accept unauthenticated or mismatched delegate result as Task progress. |

A resource cannot be fully pre-registered only where the operating system assigns identity after creation, such as PID or ephemeral port. In those cases, pre-register the intent and bounded expected conditions, create only through the manager, bind the read-back identity immediately, and do not permit operational use before binding. Any resource observed outside this sequence is `UNOWNED_UNKNOWN`.

## 11. Host observability adapters

Adapters are read-only, capability-scoped evidence providers. They return structured sanitized evidence, not shell access, raw `/proc` paths, arbitrary commands, environment variables, or unrestricted files.

### Process Identity Adapter

Input: a lease-bound process identity request limited to an explicit PID or manager-created process handle.

Output:

```text
ProcessObservation {
  observed_at: UtcTimestamp
  pid: Integer
  process_start_time: KernelStartTime
  boot_id: OpaqueBootId
  process_group: Integer
  parent_pid: Integer | UNKNOWN
  cwd: SanitizedAbsolutePath | UNKNOWN
  executable: SanitizedExecutableRef | UNKNOWN
  cgroup: SanitizedCgroupRef | N/A | UNKNOWN
  user: StableLocalUserRef | UNKNOWN
  observation_status: MATCH | NOT_FOUND | ACCESS_DENIED | INCOMPLETE
}
```

The minimal strong process match is `(pid, process_start_time, boot_id)`. Process group, parent PID, cwd, executable, cgroup, and user are corroborating evidence. The adapter never provides arbitrary host command execution to workers.

### Git / Worktree Adapter

Input: an explicit registered worktree lease/path boundary and repository identity expectation.

Output:

```text
GitWorktreeObservation {
  repository_identity: RepositoryRef
  worktree_path: SanitizedAbsolutePath
  registered_worktree_state: REGISTERED | UNREGISTERED | UNKNOWN
  branch: GitRef | DETACHED | UNKNOWN
  head: CommitSha | UNKNOWN
  base: CommitSha | UNKNOWN
  dirty_state: CLEAN | DIRTY | UNKNOWN
  lock_state: LOCKED | UNLOCKED | UNKNOWN
  observed_at: UtcTimestamp
}
```

This adapter is read-only. It must not create/remove worktrees, checkout branches, change refs, manipulate locks, reset, clean, or mutate Git configuration.

### Preview Observability Adapter

Input: a PREVIEW lease plus its recorded expected identity/bind/health constraints.

Output:

```text
PreviewObservation {
  bind_address: NetworkAddress | UNKNOWN
  port: Integer | UNKNOWN
  backing_identity: ProcessIdentity | ContainerIdentity | UNKNOWN
  health_endpoint: SanitizedEndpointRef | N/A
  health_result: HEALTHY | UNHEALTHY | TIMEOUT | UNREACHABLE | UNKNOWN
  task_lease: TaskId | UNKNOWN
  resource_lease: ResourceId | UNKNOWN
  branch: GitRef | UNKNOWN
  head: CommitSha | UNKNOWN
  ttl_status: WITHIN_TTL | EXPIRED | UNKNOWN
  observed_at: UtcTimestamp
}
```

The adapter may probe only the explicitly recorded health endpoint under bounded timeout, method, response-size, and redirect policy. It does not create, alter, expose, or terminate previews.

## 12. Docker observability

A future Docker capability must extend the existing bounded Operations Gateway model rather than expose the Docker socket or the Docker CLI to Hermes/workers.

The capability is read-only and accepts only fixed allowlisted queries for an explicitly authorized service/container scope. It may return:

- container name and opaque container identity;
- service identity and Compose project;
- image digest;
- lifecycle state and health;
- restart policy;
- network names/attachment identifiers;
- mount destinations only, never host source paths when sensitive and never mount contents;
- published ports;
- selected allowlisted labels.

It must not return or permit:

- environment variables, environment secrets, secret values, labels outside an explicit allowlist, or credential-bearing command lines;
- arbitrary `docker inspect`, arbitrary Docker API method, raw Docker socket, container filesystem access, `docker exec`, image pull/build, start/stop/restart/remove, network/volume mutation, Compose mutation, or log streams that can expose secrets.

The gateway must authenticate the caller, authorize query scope through the Task/operation grant, produce sanitized structured results, apply response-size limits, and append a read-only observation audit event. In TC2 this is design only; Docker access remains unavailable to AP0 workers.

## 13. Security observability

A future bounded Security Observability capability provides only named effective-policy facts, collected by a privileged or policy-authorized probe and returned through a sanitized read-only interface.

Allowlisted outputs:

```text
SecurityObservation {
  ssh_root_login_policy: ENABLED | DISABLED | PROHIBITED | UNKNOWN
  ssh_password_auth_policy: ENABLED | DISABLED | UNKNOWN
  ssh_public_key_policy: ENABLED | DISABLED | UNKNOWN
  ufw_active_state: ACTIVE | INACTIVE | UNKNOWN
  ufw_default_incoming_policy: ALLOW | DENY | REJECT | UNKNOWN
  ufw_explicit_allowed_ports: [PortProtocol]
  fail2ban_status: ACTIVE | INACTIVE | NOT_INSTALLED | UNKNOWN
  observed_at: UtcTimestamp
  source_version: String
}
```

The interface must not expose private keys, password hashes/material, arbitrary SSH configuration files, unrelated host configuration, unrestricted firewall rules, shell output, or arbitrary file reads. It performs no SSH, UFW, Fail2ban, or system-configuration mutation. `UNKNOWN` remains a valid observation result and cannot be silently treated as secure.

## 14. Heartbeat

Heartbeat is an authenticated liveness protocol, not a process monitor or cleanup command.

Producer and transport:

- Task/Worker Manager emits the authoritative Task/Worker heartbeat after verifying its lease binding.
- A delegated runtime may emit a signed/credential-bound heartbeat only through the local control-plane API. It cannot write the database or claim another Task/resource ID.
- The local control-plane service timestamps receipt using its UTC clock. Producers include a monotonic sequence and, when available, a monotonic elapsed-time value to distinguish replay/order from wall-clock changes.
- The transport is a versioned local authenticated API/IPC channel. Credentials are capability-scoped to one Task/lease and rotate/expire with the lease; raw bearer values are never persisted in heartbeat records.

Initial AP0 default policy, subject to later operational validation:

| Resource type | Frequency while active | Deadline after last accepted heartbeat |
|---|---:|---:|
| `WORKER` | 30 seconds | 90 seconds |
| independently active `PROCESS` | 30 seconds | 90 seconds |
| `PREVIEW` owner heartbeat | 30 seconds plus health observation | 90 seconds |
| `DELEGATED_RUN` | 30 seconds | 90 seconds |
| passive worktree/temp/artifact | not required | N/A |

The stored sequence must increase strictly per `(producer identity, task_id, resource_id)` stream. Duplicate equal sequences may be accepted only when payload digest and receipt semantics prove idempotent retry; lower/out-of-order sequences are recorded as protocol anomalies and do not refresh liveness.

Missed-heartbeat behavior:

```text
last deadline exceeded
  -> persist HEARTBEAT_MISSED audit event and state projection
  -> block new dependent resource admission and new autonomous operations for that lease
  -> request read-only reconciliation when policy requires
  -> retain resource and Task evidence for review
```

Required distinctions:

```text
heartbeat missing != process dead
process dead != cleanup authorized
cleanup authorized != cleanup completed
```

Pause/resume:

- A pause is explicit: the Task records reason, expected resume condition, active-resource disposition, and a checkpoint before entering `PAUSED` where possible.
- A paused active Worker/Process must either continue its heartbeat with `PAUSED` status under a bounded pause policy or be terminalized as a runtime resource. Silence is not a valid pause signal.
- On resume, the control plane validates supported schema, Gate validity, budget, Task scope, checkpoint consistency, and strong resource identity. A restarted worker obtains a new `resource_id`; it does not inherit a dead process identity.

## 15. Checkpoint

A Task checkpoint permits safe resumption after Hermes restart, terminal disconnect, Codex/provider quota exhaustion, temporary provider failure, or host reboot when the retained evidence remains recoverable.

Minimum checkpoint content:

- `task_id` and `checkpoint_id`;
- Task state and state revision;
- last successful operation and its evidence reference;
- branch, worktree identity, and HEAD when Git applies;
- all active/allocated resource lease IDs with their last known strong identity and state;
- pending validation and outstanding Gates;
- next permitted action, not merely next desired action;
- blocking reason and prerequisite needed to unblock;
- provider/quota state when applicable;
- policy/schema versions used to make the checkpoint;
- no secret material, raw capability tokens, provider credentials, environment dumps, or terminal transcript.

Protocol:

1. Before a planned pause, provider-failure pause, risky handoff, or bounded operation boundary, the manager requests a checkpoint.
2. The control plane validates Task/lease consistency and persists a new immutable checkpoint plus `CHECKPOINT_CREATED` audit event in one transaction.
3. If checkpoint persistence fails, the Task must not claim a resumable pause. It enters `BLOCKED` or remains in its current non-progressing state with `CHECKPOINT_FAILURE` evidence; no new work is admitted.
4. On recovery, the manager loads the latest supported checkpoint, reconciles all non-terminal resources read-only, and re-runs policy/gate/budget checks before `READY` or `RUNNING`.
5. A host reboot invalidates PID/boot-bound identity. Surviving resource claims require new observation and reconciliation; no pre-reboot PID binding is trusted.

## 16. Quota pause/resume

`PROVIDER_QUOTA` is a non-terminal pause reason. It preserves Task state and prevents uncontrolled retry/spawn loops.

```text
RUNNING
  -> provider quota unavailable
  -> persist provider-failure observation
  -> checkpoint
  -> PAUSED(reason = PROVIDER_QUOTA)
  -> no new Worker admission
  -> provider availability restored
  -> policy / gate / budget / checkpoint consistency check
  -> READY or RUNNING
```

Rules:

- Quota exhaustion does not change Task ownership, erase event history, or terminalize a Task automatically.
- The current worker may finish only an explicitly bounded in-flight operation if the operation can remain within authorized scope; otherwise it stops accepting new work and reports its state.
- Resume requires a new availability observation plus successful policy checks. It does not reuse an expired Gate, invalid checkpoint, old worker identity, or exhausted budget reservation.
- Provider failures other than quota use the same pause/checkpoint discipline with a distinct typed reason, such as `PROVIDER_TEMPORARY_FAILURE`.

## 17. Human gates

A Gate is required whenever risk policy, operation policy, budget exception policy, or cleanup policy requires explicit human authority. Gates do not grant ambient access.

Gate lifecycle:

```text
PENDING -> APPROVED -> CONSUMED
    |          |
    v          v
 DENIED      EXPIRED
```

Rules:

1. Create the Gate before the gated operation. A worker does not start the operation while status is `PENDING`.
2. Approval must bind exact `task_id`, requested operation, resource/target scope, risk class, required authority, authorization reference, and `expires_at`.
3. A Gate may be consumed exactly once by the event that starts the approved operation. Idempotent retry requires a separately specified replay-safe operation policy; it never consumes a different scope.
4. A denied or expired Gate blocks the operation and creates an audit event. It cannot be revived by changing a display label or matching a similar request.
5. Gate service/storage unavailability fails closed for gated operations.
6. The approver identity is typed and immutable in the record. A generic human name or a chat statement without an authorization reference is insufficient.

## 18. Audit model

AP0 audit is append-only and designed for detectable history and reproducibility, not blockchain or tamper-proof claims.

Ordering and integrity model:

1. Each accepted event receives a database-assigned monotonically increasing `sequence` in the same transaction that applies its current-state projection.
2. Each event receives a globally unique `event_id`, UTC `occurred_at` supplied/validated by the producer, and authoritative UTC `recorded_at` assigned by the control plane.
3. The event payload is canonicalized according to its typed schema. `event_hash` is SHA-256 over a canonical envelope including event ID, sequence, record timestamps, type, record references, actor, correlation ID, schema version, payload digest, and `previous_event_hash`.
4. `previous_event_hash` points to the immediately prior accepted global event hash, or is `N/A` for genesis. This makes alteration, deletion, and reordering detectable during verification, but does not prevent a privileged store operator from rewriting both data and hashes.
5. Database constraints prevent update/delete through the normal control-plane service. Administrative recovery procedures must preserve original event files/backup evidence and append recovery events rather than rewrite history.
6. Sensitive data stays out of payloads. Use redacted structured categories and evidence references rather than secret values or raw command output.

A transactional mutation is valid only when its required audit event(s) and resulting state projection commit together. Audit append failure means the associated admission/state mutation is not committed. If an external side effect already occurred in the bounded creation interval, the service records the local failure in a durable incident/recovery channel on return and blocks further use pending reconciliation.

## 19. Reconciliation

Reconciliation is a read-only comparison of control-plane expected state with bounded host observations. It runs after restart, checkpoint restore, missed heartbeat, adapter recovery, and explicit review requests.

Inputs:

- expected Task/Lease state and bound identity from canonical storage;
- process, Git/worktree, preview, Docker, and security observations from bounded adapters;
- no inferred ownership from names, paths, ports, age, terminal logs, or PID alone.

Results:

| Result | Meaning | Required control-plane action |
|---|---|---|
| `MATCHED` | Expected resource exists and strong identity/evidence matches lease. | Append observation; leave lifecycle unchanged unless another policy condition exists. |
| `MISSING_RUNTIME` | Expected strong identity is absent. | Record evidence; terminalize resource only under explicit identity-safe policy; do not create replacement automatically. |
| `UNKNOWN_RUNTIME` | A runtime resource is observed but cannot be mapped to a lease confidently. | Record as unknown; no adoption, mutation, or cleanup. |
| `IDENTITY_MISMATCH` | Observed resource conflicts with expected identity, such as PID reuse/start-time mismatch or wrong worktree/HEAD. | Block dependent work; retain both expected and observed evidence; require review. |
| `HEARTBEAT_MISSED` | Required heartbeat deadline elapsed. | Record liveness failure; do not infer dead/cleanup authorization. |
| `STATE_DRIFT` | Lease/Task expectation conflicts with valid observation, such as branch/HEAD/health/budget state. | Block affected operation and require remediation/re-admission. |
| `UNOWNED_UNKNOWN` | No valid lease/Task ownership exists for discovered resource. | Preserve unknown status; no invented Task ID or automatic claim. |

No reconciliation result may terminate a process, delete a file, alter Docker, shut down a preview, remove a worktree, or otherwise mutate runtime state. Reconciliation always produces an audit event containing observations, adapter version, policy version, and correlation ID.

## 20. Legacy resources

TC0-discovered resources are not imported into AP0 ownership by inference. In particular, do not fabricate Task IDs for:

- Hermes PID `1610802`;
- fourteen Codex chains and their fourteen pytest descendants;
- previews on `:3100` and `:37891`;
- historical or detached worktrees;
- `/tmp` entries, Hermes cache entries, tool caches, review trees, or backups.

They remain `UNKNOWN`, `UNOWNED_UNKNOWN`, or `STALE_CANDIDATE` according to evidence already documented by TC0/TC1. An evidence-backed human reconciliation decision may later establish a registry import/attachment record, but it must:

1. retain the original unknown/discovered event;
2. identify the evidence and approving authority;
3. distinguish imported historical evidence from resource creation under AP0;
4. never claim register-before-use occurred retrospectively;
5. avoid changing historical IDs or rewriting prior audit history.

Absent that decision, legacy resources are outside AP0 worker control and cleanup authority.

## 21. Failure semantics

All failure paths preserve evidence and fail closed for further autonomous work. “Fail closed” means no new affected operation/resource admission proceeds; it does not mean the control plane assumes authority to terminate an already existing resource.

| Failure | Required behavior |
|---|---|
| Registry unavailable | Do not admit Task/resource, consume Gate, record heartbeat as accepted, or start worker. Manager may only surface a local bounded failure and request recovery. |
| Transaction failure | Roll back uncommitted admission/state mutation. If runtime creation has not started, no side effect occurs. If it began, mark operation indeterminate through durable recovery evidence and block use pending reconciliation. |
| Schema mismatch | Unknown/invalid/upgrade-required schema blocks mutation. Read-only diagnostics may identify affected record IDs/version. |
| Identity readback failure | Keep lease `ALLOCATED`, append/retain `RESOURCE_CREATION_FAILED` or bind-failure evidence, stop autonomous use, require reconciliation/authorized recovery. |
| Duplicate resource identity | Reject the new binding in the same transaction, retain collision evidence, and block both affected allocations from becoming active until reviewed. |
| Budget exceeded | Reject allocation before creation; append denied-admission event; do not reserve or spawn. |
| Gate unavailable | Treat gated operation as not approved. Do not use cached/general approval beyond its explicitly valid record. |
| Heartbeat store unavailable | Producer must not claim liveness. Block new dependent work; manager applies bounded pause/stop policy rather than silently running indefinitely. |
| Audit append failure | Do not commit corresponding logical state mutation. If an unavoidable external creation already occurred, preserve recovery evidence and block use; no successful admission claim is emitted. |
| Checkpoint failure | Do not enter resumable `PAUSED` state. Block new work and retain failure evidence; current worker follows its finite stop policy. |
| Adapter failure or access denied | Return typed `ADAPTER_UNAVAILABLE`/`ACCESS_DENIED`; do not substitute heuristic evidence. Block actions that require the missing evidence. |
| Control-plane restart during operation | On restart, recover only committed records, treat in-flight creation as indeterminate, reconcile before reuse, and never assume a missing in-memory operation completed. |

## 22. Backup/recovery requirements

TC2 defines requirements only; it does not implement backup or restore.

The future SQLite control plane must support:

1. consistent backups that include the SQLite database and any WAL state through a SQLite-aware backup procedure or a quiesced checkpointed snapshot;
2. retention of registry-level schema version, record schema versions, event sequence/high-water mark, and integrity metadata with each backup;
3. an integrity check before backup acceptance and before restored service admission;
4. restore only first into an isolated environment/path, never directly over a live canonical registry;
5. verification of database integrity, foreign keys, record-version compatibility, event sequence continuity, and event-hash-chain consistency after restore;
6. a read-only reconciliation of all non-terminal/allocated resources after restore before any new worker/resource admission;
7. retention of restoration audit evidence and a clear distinction between restored historical records and newly observed runtime state;
8. a documented recovery policy for unavailable/corrupt primary storage that blocks normal admission until the registry is restored or an explicit human decision establishes a new canonical registry.

A backup is not proof that the live host state rolled back with it. Host/process/resource evidence must be reconciled after restore.

## 23. Paperclip migration

The AP0 registry is not Paperclip. AP0 defines a portable control-plane contract that Paperclip can import or replace without changing canonical identifiers or rewriting history.

Migration boundary:

- Workers depend on a versioned control-plane API/contract, not SQLite tables, filesystem paths, Hermes internal state, or terminal transcripts.
- The AP0 export envelope includes Tasks, Resource Leases, Audit Events, Gates, Heartbeats, Checkpoints, schema versions, record IDs, event sequence, timestamps, event hashes, opaque unknown fields, and provenance.
- Paperclip import preserves `task_id`, `resource_id`, `event_id`, `gate_id`, `checkpoint_id`, `correlation_id`, original timestamps, event ordering, and original AP0 provenance.
- Import does not transform a historical `UNKNOWN`/`UNOWNED_UNKNOWN` resource into an owned resource without a separately auditable reconciliation decision.
- Paperclip may become canonical through an explicit cutover record that identifies final AP0 event sequence, export digest, importer identity/version, validation result, and effective canonical endpoint.
- During migration, there is one writer/canonical authority per Task. A dual-read period is permissible; uncoordinated dual-write is prohibited.
- After cutover, AP0 storage may remain read-only archival evidence. Workers continue through the abstract API and do not need to know whether AP0 SQLite or Paperclip is canonical.

## 24. Negative cases

| Case | Required result |
|---|---|
| PID reuse | `(pid, start_time, boot_id)` mismatch produces `IDENTITY_MISMATCH`; a PID match alone never binds a lease. |
| Host reboot | Boot ID changes; old process identities are invalid. Restore then read-only reconciliation is required before resume. |
| Hermes crash | Committed registry records survive independently. In-flight work is indeterminate until checkpoint/reconciliation; no implicit success. |
| Worker crash | Heartbeat may be missed; adapter determines only observed process state. Task blocks/pause policy applies; no cleanup authorization follows. |
| Registry unavailable | No Task/resource admission, heartbeat acceptance, gate consumption, or new worker start. |
| Registry partially written | Transactional write rolls back; database integrity/recovery procedure blocks mutation until repaired. |
| Worker spawned but identity bind fails | Lease remains with failure evidence; worker receives no autonomous work and cannot be treated as active. |
| Lease allocated but creation fails | Lease terminalizes as `RESOURCE_CREATION_FAILED`; history remains and unused budget is released transactionally. |
| Preview port collision | No listener is adopted. Allocation fails or remains unbound; alternate port requires a new/explicit allocation decision. |
| Dirty worktree | Worktree is not eligible for automated cleanup and cannot satisfy a clean-worktree prerequisite. Drift is recorded. |
| Branch drift | Observed branch/base/HEAD mismatch blocks continued autonomous work pending reconciliation/re-admission. |
| Quota exhaustion | Persist checkpoint then `PAUSED(PROVIDER_QUOTA)`; no new Worker admission; resume only after availability/policy checks. |
| Heartbeat missed | Record `HEARTBEAT_MISSED`; do not infer process death or authorize cleanup. |
| Unknown Docker resource | Record `UNKNOWN_RUNTIME`/`UNOWNED_UNKNOWN`; do not inspect arbitrarily, adopt, mutate, or delete. |
| Unsupported schema version | Read-only diagnostic only; mutation fails closed until a supported migration/reader exists. |
| Human gate expired | Operation remains blocked; expired approval cannot be consumed or extended implicitly. |
| Audit write failure | Associated admission/state mutation is not claimed as durable; no new dependent autonomous work proceeds. |
| Checkpoint failure | Task cannot be marked resumably paused; block new work and preserve failure reason. |

No negative case silently continues autonomous work without canonical ownership evidence, supported schema, durable audit evidence, and required identity binding.

## 25. Open questions

1. Which local service identity and IPC authentication mechanism will own the AP0 SQLite database and issue per-Task/per-lease capabilities?
2. What exact immutable evidence-reference scheme should identify repository Task Contracts, policy versions, validation artifacts, and human authorization references?
3. What AP0 default budgets and TTLs are operationally safe after measurement, including worker count, process count, preview lifetime, temp/artifact size, and provider retry limits?
4. Which resources must be exclusive at admission, especially port ranges, worktree paths, test environments, and provider-concurrency slots?
5. What is the formal resume policy for an in-flight operation whose provider-side completion is unknown after a crash/restart?
6. What trusted privileged implementation can provide the bounded Docker and Security Observability capabilities without expanding worker privilege?
7. What preview health endpoint requirements, bind-address policy, authentication behavior, and acceptable response semantics will apply in AP0-TC3?
8. How will owner/requester/agent/service identities be provisioned, revoked, and audited without coupling them to Unix usernames or provider secrets?
9. What retention periods and evidence-release rules govern checkpoints, events, artifacts, and terminal Resource Leases?
10. What explicit human reconciliation process may attach evidence-backed legacy resources while preserving their prior unknown status?
11. What migration acceptance test will prove a Paperclip import preserves identifiers, event ordering/hashes, unknown fields, and gate semantics?

## 26. Recommended AP0-TC3

AP0-TC3 should be a separately authorized, still non-production implementation-design and validation task that turns this contract into an implementation-ready local control-plane specification without creating runtime resources or mutating production systems.

Recommended scope:

1. Define the dedicated SQLite logical schema, constraints, indexes, transaction boundaries, migration plan, and query/API contracts for the six record families.
2. Specify the local control-plane service/IPC authorization model, per-lease capability binding, idempotency keys, request/response error taxonomy, and audit/outbox behavior.
3. Define precise AP0 policy defaults for budgets, TTLs, heartbeat deadlines, retry bounds, preview bind restrictions, and quota pause behavior, with explicit human-gate conditions.
4. Specify reference data structures and read-only adapter interfaces for process, Git/worktree, preview, Docker, and security observations; include sanitized fixtures and negative-case tests only.
5. Define backup/restore runbook requirements and a hermetic test plan for migrations, integrity checks, event-chain verification, failed transaction recovery, and post-restore reconciliation.
6. Define Paperclip export/import conformance fixtures proving identifier and history preservation.
7. Validate the design through documentation/schema/state-machine review and `git diff --check`; do not create a database, spawn/terminate processes, manipulate Docker/systemd/firewall/SSH, create/shut down previews, create/remove worktrees, remove caches, push, open a pull request, or merge.

## Final verdict

AP0_TC2_CONTROL_PLANE_READY
