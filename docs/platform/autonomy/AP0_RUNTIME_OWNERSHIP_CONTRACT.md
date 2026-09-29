# AP0-TC1 — Runtime Ownership & Resource Lifecycle Contract

Status: proposed canonical contract for AP0; specification only
Evidence basis: `docs/platform/autonomy/AP0_RUNTIME_BASELINE.md` (captured 2026-09-29T11:50:46Z)
Predecessor verdict: `AP0_TC0_BLOCKED`
Scope boundary: this document creates no runtime registry entry, process, preview, worktree, cleanup action, system configuration, or authorization.

## 1. Principles

1. Every autonomous runtime resource has exactly one canonical owner: one immutable `task_id` through one Resource Lease. The required relationship is `TASK -> RESOURCE LEASE -> runtime resource`.
2. A Task is the durable control-plane record for one finite, bounded unit of autonomous work. It is not a PID, terminal session, worktree path, branch, preview, or log file.
3. A Resource Lease is the durable ownership record for one runtime resource. It binds the resource to exactly one Task for the lease lifetime. A resource may not be simultaneously leased to multiple Tasks.
4. Human and agent identities are distinct typed identities. An agent may create or operate a resource only under the Task; it does not replace the requesting human or other accountable requester.
5. Task lifecycle and resource lifecycle are separate state machines. A terminal Task can retain resources for evidence or review; resource cleanup does not change business-task state.
6. Liveness is explicit evidence, not inference from process name, user, current working directory, port, or age. Heartbeat expiry creates review evidence only.
7. `STALE_CANDIDATE` is not `SAFE_TO_DELETE`. Expiry, age, orphaned parentage, and missing heartbeat never independently authorize destructive action.
8. Creation must be register-before-use where practical: create the Task, allocate the Resource Lease, then create or attach the runtime resource and record its identity. If this ordering cannot be achieved, the resource is unowned and must be treated as an admission failure, not silently adopted.
9. A worker is finite. It must not intentionally remain alive after its Task becomes terminal.
10. Cleanup authority is least-privilege, explicit, auditable, and separate from evidence of staleness. AP0 grants no autonomous C3 or C4 cleanup.
11. Canonical ownership records and audit events must be control-plane data, not reconstructed from terminal logs or tool caches. Runtime labels are corroborating evidence, not the sole registry.
12. Unknown legacy ownership remains `UNKNOWN`; this contract does not invent Task records or assign inferred owners retroactively.

Definitions:

- Canonical owner: the immutable `task_id` named by a Resource Lease.
- Operational actor: the human or agent identity that performed an action under a Task.
- Cleanup authority: the explicitly authorized class and principal permitted to request or execute cleanup.
- Terminal: no further normal Task work or resource activity is expected, subject to retained evidence and an independent cleanup lifecycle.
- Stale candidate: a resource whose evidence requires review because expected liveness, lease, or retention conditions are no longer satisfied.

## 2. Task schema

A Task record is append-only except for explicitly mutable lifecycle fields. `task_id` is immutable and globally unique. The registry must reject mutation of `task_id` and reject reuse of a terminal Task ID.

```text
Task {
  task_id: TaskId (immutable)
  created_at: Timestamp
  created_by: IdentityRef
  requested_by: IdentityRef
  state: TaskState
  risk_class: GREEN | YELLOW | RED | UNKNOWN
  branch: GitRef | N/A
  base_sha: GitCommitSha | N/A
  expected_head: GitCommitSha | UNKNOWN | N/A
  worktree: WorktreeRef | N/A
  allowed_operations: [OperationGrant]
  resource_budget: ResourceBudget
  created_resources: [ResourceId]
  last_heartbeat: Timestamp | N/A
  expires_at: Timestamp | N/A
  terminal_result: TerminalResult | N/A
  cleanup_state: TaskCleanupState
}

IdentityRef {
  identity_type: HUMAN | AGENT | SERVICE | UNKNOWN
  identity_id: StableOpaqueIdentifier
  display_name: OptionalNonAuthoritativeLabel
}

ResourceBudget {
  max_workers: NonNegativeInteger
  max_processes: NonNegativeInteger
  max_previews: NonNegativeInteger
  max_worktrees: NonNegativeInteger
  max_temp_bytes: NonNegativeInteger | UNKNOWN
  max_artifact_bytes: NonNegativeInteger | UNKNOWN
  max_runtime_seconds: NonNegativeInteger | UNKNOWN
}

TerminalResult {
  outcome: SUCCEEDED | FAILED | CANCELLED | EXPIRED | BLOCKED | UNKNOWN
  recorded_at: Timestamp
  summary_ref: EvidenceRef | N/A
  recorded_by: IdentityRef
}

TaskCleanupState {
  state: NOT_APPLICABLE | NOT_REQUESTED | PENDING_REVIEW | AUTHORIZED | IN_PROGRESS | COMPLETE | FAILED
  updated_at: Timestamp
  reason_ref: AuditEventId | N/A
}
```

Schema rules:

- `created_by` identifies the actor that registered the Task; `requested_by` identifies the requester accountable for the work. Both are typed `IdentityRef` values and must never be collapsed into an untyped username.
- `branch`, `base_sha`, `expected_head`, and `worktree` describe the authorized development context when Git work is in scope. They are `N/A` for a Task with no Git scope, and `UNKNOWN` only where the Task was imported from incomplete evidence.
- `expected_head` is the intended terminal Git commit when known; it is not a mutable pointer to arbitrary branch movement. Any material change requires a recorded Task amendment or a successor Task.
- `allowed_operations` is an allowlist, not a statement of ambient capability. It must name operation class, target boundary, and any human gate reference.
- `created_resources` is derived from successful lease allocation and is retained as an audit index. It must not be manually edited to hide an allocation.
- `last_heartbeat` is required only when the Task has active heartbeat-required resources or an explicit Task heartbeat policy. It must not claim passive artifact liveness.
- `expires_at` is a review deadline. Expiry can advance a Task to `BLOCKED` or establish an expired condition for review, but does not itself delete resources or change a resource to `CLEANED`.
- `terminal_result` is set once when the Task reaches a terminal business outcome. Corrections are appended as audit events, not destructive rewrites.
- `cleanup_state` records cross-resource cleanup governance without encoding cleanup as a Task business state.

## 3. Task state machine

Task states are finite and concern authorized work, not infrastructure cleanup.

```text
CREATED -> READY -> RUNNING -> VALIDATING -> REVIEW -> TERMINAL
                    |             |             |
                    v             v             v
                  PAUSED <------> PAUSED <----> PAUSED
                    |             |             |
                    v             v             v
                  BLOCKED <---------------------+

CREATED | READY | RUNNING | VALIDATING | REVIEW | PAUSED | BLOCKED -> CANCELLED
CANCELLED -> TERMINAL
BLOCKED -> READY | RUNNING | VALIDATING | REVIEW only after recorded unblock authority
TERMINAL is final for normal work.
```

State meanings:

- `CREATED`: immutable identity and requested scope exist; admission is not complete.
- `READY`: required policy, scope, and prerequisite checks permit a worker or resource allocation.
- `RUNNING`: at least one authorized active work operation is expected.
- `VALIDATING`: implementation work is complete enough for declared validation; validation resources remain independently leased.
- `REVIEW`: evidence is awaiting automated or human review, including a required human gate.
- `PAUSED`: work is intentionally suspended with reason, actor, and re-entry conditions recorded. A paused Task is not proof that its processes may continue indefinitely; active worker leases require their own explicit pause policy or termination.
- `BLOCKED`: work cannot safely progress because of a missing prerequisite, denied gate, expired lease evidence, scope drift, or unresolved safety condition.
- `CANCELLED`: a requester or authorized authority has cancelled normal work. Cancellation must cause active worker admission to stop and require resource disposition review.
- `TERMINAL`: a final Task outcome is recorded. No new worker, process, preview, or task worktree lease may be allocated to a terminal Task. Retained artifacts and cleanup records may continue to exist.

Allowed normal transitions must be recorded in the audit stream. Illegal examples include allocating a new worker to `TERMINAL`, treating `PAUSED` as permission for an unbounded worker, and using `CLEANED` as a Task state.

## 4. Resource Lease schema

Every autonomous runtime resource must have one Resource Lease before or atomically with creation. The lease is the canonical ownership record.

```text
ResourceLease {
  resource_id: ResourceId (immutable)
  resource_type: ResourceType
  task_id: TaskId (immutable foreign key)
  owner: OwnerRef
  created_at: Timestamp
  state: ResourceState
  heartbeat_required: Boolean
  last_heartbeat: Timestamp | N/A
  ttl: Duration | N/A
  cleanup_policy: CleanupPolicyRef
  cleanup_authority: CleanupAuthority
  metadata: TypeSpecificMetadata
}

OwnerRef {
  task_id: TaskId
  accountable_requester: IdentityRef
  operating_actor: IdentityRef | UNKNOWN
}

ResourceType =
  WORKER | PROCESS | PREVIEW | WORKTREE | TEMP_DIR | TEST_ENV | ARTIFACT | DELEGATED_RUN
  | FutureRegisteredType

CleanupAuthority {
  authority_class: C0 | C1 | C2 | C3 | C4
  authorized_principal: IdentityRef | HUMAN_GATE_REQUIRED | NONE
  authorization_ref: AuditEventId | N/A
}
```

Lease rules:

- `resource_id` is immutable, unique, and never reused. `task_id` is immutable after allocation.
- `owner.task_id` must equal the lease `task_id`; its redundant representation makes ownership visible in resource-centric views without weakening the foreign-key invariant.
- `owner.accountable_requester` is copied from the Task at allocation for audit clarity. `owner.operating_actor` may change only through an auditable handoff; it never changes canonical Task ownership.
- `metadata` is resource-type-specific but must include enough stable identity to read back the exact resource. It may add fields without changing Task identity semantics.
- `ttl` is the maximum expected lease interval or review deadline. `N/A` is permitted only for resource types explicitly governed by retention rather than runtime liveness, such as retained artifacts.
- Any unsuccessful creation after lease allocation must be represented by a terminal lease record with failure metadata; deleting the record would erase ownership evidence.
- Any discovered resource without a lease is `UNOWNED_UNKNOWN`. It may be observed and mapped, but cannot be silently attached to a newly invented Task.

## 5. Resource state machine

Resource state is independent of Task state.

```text
ALLOCATED -> ACTIVE -> IDLE -> ACTIVE
     |          |        |
     |          v        v
     |   HEARTBEAT_MISSED
     |          |
     v          v
 TERMINAL <- STALE_CANDIDATE
     |              |
     v              v
CLEANUP_PENDING <- cleanup request and explicit authorization
     |
     +-> CLEANED
     |
     +-> CLEANUP_FAILED
```

State meanings and transition rules:

- `ALLOCATED`: a lease exists; creation or attachment is pending, in progress, or not yet confirmed.
- `ACTIVE`: the resource is expected to be operating now. Heartbeat or health requirements apply when specified by the resource type.
- `IDLE`: the resource remains intentionally retained and is not doing active work. It is not equivalent to abandoned.
- `HEARTBEAT_MISSED`: required liveness evidence was not received by the recorded deadline. This is a non-destructive signal.
- `STALE_CANDIDATE`: available evidence indicates review is required, for example missed heartbeat beyond policy, expired TTL, Task terminality with an active finite worker, or an ownership/identity mismatch. It is never an authorization to stop or delete.
- `TERMINAL`: the resource ended normally, failed, or was determined absent by an identity-safe readback. It may still require retained evidence or cleanup.
- `CLEANUP_PENDING`: an authorized cleanup request exists and preconditions are awaiting execution or review.
- `CLEANED`: an authorized cleanup action completed and exact-target readback confirmed absence or the intended postcondition.
- `CLEANUP_FAILED`: authorized cleanup was attempted but did not reach the verified postcondition. The lease, audit events, and evidence remain retained.

Transition constraints:

- `HEARTBEAT_MISSED` and `STALE_CANDIDATE` must retain the last known liveness evidence, policy deadline, and reason.
- TTL expiry transitions an active or idle resource to `STALE_CANDIDATE`; it must not transition directly to `CLEANUP_PENDING`, `CLEANED`, or deletion.
- `CLEANUP_PENDING` requires an explicit `CLEANUP_REQUESTED` event, a matching authority class, a target identity check, and all resource-type safety preconditions.
- A resource may reach `TERMINAL` without cleanup; for example, a process may have exited while its logs or worktree are retained.
- `CLEANED` is a verified resource outcome, not a synonym for expired, inaccessible, or no longer listed by a heuristic query.

## 6. Worker contract

A Worker is a finite execution resource that may own subordinate process resources but never replaces the Task as canonical owner.

Required lifecycle:

```text
spawn
  -> allocate WORKER lease
  -> start worker
  -> register process identity and process group
  -> RUNNING / heartbeat
  -> result
  -> TERMINAL
  -> separately authorized cleanup, if required
```

The Worker record must bind at least:

```text
WorkerMetadata {
  task_id: TaskId
  worker_id: ResourceId
  pid: Pid
  process_group: ProcessGroupId
  process_identity: ProcessIdentity
  cwd: AbsolutePath
  worktree: WorktreeRef | N/A
  branch: GitRef | N/A
  head_sha: GitCommitSha | UNKNOWN | N/A
  started_at: Timestamp
  last_heartbeat: Timestamp
  timeout: Duration
  exit_code: Integer | SIGNAL | UNKNOWN | N/A
  result: WorkerResult | N/A
}
```

Worker rules:

- The Worker lease is allocated before spawn where practical. Immediately after spawn, the supervisor records PID, process group, process identity, start time, and runtime context; failure to register is an admission failure requiring termination or explicit human review, not silent continuation.
- A worker must run in its declared `cwd` and `worktree`. A mismatch between recorded and observed worktree, branch, or head SHA blocks continued autonomous work until reconciled.
- A worker must emit heartbeat evidence while `RUNNING`; the heartbeat includes Task ID, Worker ID, monotonic sequence or timestamp, and a bounded status summary. A heartbeat does not authorize new operations.
- `timeout` is explicit and finite. Timeout expiry produces `HEARTBEAT_MISSED` or `STALE_CANDIDATE` evidence and stops new work admission; it is not a destructive cleanup authorization.
- `result` captures success, failure, cancellation, blocked condition, and evidence references. Worker result is recorded before terminalization where possible.
- The worker must intentionally exit when its Task reaches `TERMINAL` or `CANCELLED`, unless a separately recorded evidence-preservation exception applies. Such an exception does not permit the worker to continue autonomous actions.
- Child processes must be individually leased as `PROCESS` resources or deterministically represented in Worker metadata when they cannot outlive the worker. A child capable of surviving worker exit, binding a port, retaining credentials, or consuming material resources requires its own PROCESS lease.

## 7. Process identity

Every autonomous-development process must be traceable to `task_id` plus `worker_id` or a `resource_id`.

A process record must use an identity stronger than PID alone where practical:

```text
ProcessIdentity {
  pid: Pid
  process_start_time: KernelOrSupervisorStartTime
  boot_id: HostBootId | ContainerInstanceId
  process_group: ProcessGroupId
  parent_worker_id: ResourceId | N/A
  executable_fingerprint: ExecutableRef | UNKNOWN
  cgroup_or_container_id: OptionalRuntimeBoundary
}
```

The minimal safe match is `(pid, process_start_time, boot_id)`; use a container identity instead when the process is containerized. `process_group`, executable fingerprint, and cgroup/container boundary are corroborating evidence. PID reuse must be assumed possible after process exit or host restart.

The registry must not determine ownership from any of the following alone:

- process name;
- current working directory only;
- username only;
- age only;
- port only;
- PID only.

A process discovered without a matching strong identity is `UNOWNED_UNKNOWN`, even when its command, cwd, or user appears plausible. Reconciliation must produce an audit event and cannot fabricate a Task owner.

## 8. Preview lease

A Preview is a bounded runtime resource for a specific Task work context. Public exposure is not the default assumption: preview bind address defaults to loopback or an explicitly approved private boundary. Exposure beyond that boundary requires a separate authorized operation and recorded justification.

```text
PreviewMetadata {
  preview_id: ResourceId
  task_id: TaskId
  branch: GitRef
  head_sha: GitCommitSha
  worktree: WorktreeRef
  runtime_identity: ProcessIdentity | ContainerIdentity
  bind_address: NetworkAddress
  port: Port
  created_at: Timestamp
  health_endpoint: EndpointRef
  last_health: HealthObservation | N/A
  ttl: Duration
  cleanup_policy: CleanupPolicyRef
}
```

Preview rules:

- One preview lease binds one Task, branch, head SHA, worktree, runtime identity, bind address, and port. A branch name without a commit SHA is insufficient.
- Port selection is a resource allocation, not evidence of ownership. A listener must be read back and matched to the recorded process or container identity before the preview is considered active.
- A preview has bounded `ttl`. AP0 may recommend a default TTL in a later policy, but TC1 does not silently enforce one.
- Preview liveness is `health endpoint + owner heartbeat`: health confirms the service response; heartbeat confirms the owning Task/Worker still expects it. Health alone does not establish ownership, and Task heartbeat alone does not establish listener identity.
- A Task terminal result, preview TTL expiry, failed health, or owner-heartbeat miss yields review evidence and may make the preview a `STALE_CANDIDATE`; no automatic shutdown follows from TC1.
- Preview cleanup requires the resource's cleanup policy, explicit authority, strong process/container identity match, and post-action readback.

## 9. Worktree lease

Canonical worktrees and task worktrees are different categories.

- A Canonical Worktree is the protected development baseline workspace. It is not automatically owned by an autonomous Task and must not be deleted by a task-level cleanup policy.
- A Task Worktree is an isolated workspace allocated to exactly one Task through a `WORKTREE` lease. It may reference a branch, detached commit, review context, or evidence context as explicitly recorded.

```text
WorktreeMetadata {
  task_id: TaskId
  path: AbsolutePath
  worktree_kind: CANONICAL | TASK
  branch: GitRef | DETACHED | UNKNOWN
  base_sha: GitCommitSha | UNKNOWN
  head_sha: GitCommitSha | UNKNOWN
  dirty_state: CLEAN | DIRTY | UNKNOWN
  lock_state: LOCKED | UNLOCKED | UNKNOWN
  pr_relation: PullRequestRef | N/A | UNKNOWN
  evidence_relation: [EvidenceRef]
  created_at: Timestamp
  retention_class: EPHEMERAL | REVIEW | EVIDENCE | HANDOFF | UNKNOWN
  cleanup_state: NOT_REQUESTED | PENDING_REVIEW | AUTHORIZED | IN_PROGRESS | COMPLETE | FAILED
}
```

Worktree rules:

- A Task Worktree lease must record its path, branch or detached state, base SHA, head SHA, dirty state, PR/evidence relation, retention class, and cleanup state.
- The Task's `worktree` field references the lease; the path is metadata, never a substitute for Task ownership.
- A dirty worktree can never be automatically deleted.
- A worktree associated with unresolved review, evidence retention, a PR, an active Task, or unknown dirty/lock state can never be automatically deleted.
- Canonical worktrees, shared worktrees, and worktrees with `UNKNOWN` ownership are outside autonomous Task cleanup until a separate human-authorized reconciliation contract establishes ownership and retention.
- Worktree staleness may be raised for review based on Task terminality, branch divergence, detached state, or retention expiry, but none of those facts authorize deletion.

## 10. Temporary resource contract

Temporary storage is leaseable whenever autonomous work creates or claims it. A path prefix or `/tmp` age is not an ownership mechanism.

Initial leaseable temporary resource types and examples:

| Resource type | Examples | Required metadata |
|---|---|---|
| `TEMP_DIR` | `/tmp/megabrain-*`, validation workspace, browser profile | absolute path, creation nonce, filesystem device/inode where practical, intended contents class, byte budget |
| `TEST_ENV` | test virtualenv, isolated package cache, browser test environment | path or runtime identity, toolchain lock/reference, worktree, environment boundary, timeout |
| `ARTIFACT` | build output, test report, trace, evidence bundle | immutable content reference or path, producer resource, retention class, integrity reference where practical |
| `DELEGATED_RUN` | child agent/sandbox execution | delegate identity, parent worker, workspace, timeout, result/evidence reference |

Temporary-resource rules:

- The creator allocates a lease before creation where practical and writes an opaque resource marker/metadata record within the allocated boundary when safe. External lease registry remains canonical because files can be copied, renamed, or deleted.
- Metadata must distinguish a created directory from an adopted shared directory. Autonomous workers may not claim all matching `/tmp/megabrain-*` paths as theirs.
- A temporary resource must carry a bounded resource budget and retention class. If capacity, ownership, or identity cannot be established, it becomes `UNOWNED_UNKNOWN` or `STALE_CANDIDATE`, not cleanup eligible.
- Virtualenvs, browser profiles, build outputs, validation workspaces, and artifacts may be passive and therefore do not require a runtime heartbeat. Their retention is governed by lease, evidence relationship, and explicit cleanup authority.
- Shared tool caches, host `/tmp`, Hermes cache, and backup directories cannot be treated as single Task resources merely because individual entries exist beneath them. Only separately leased child entries may be attributed to a Task.

## 11. Heartbeat semantics

Heartbeat is evidence answering three distinct questions:

1. Is the owning Task alive and still authorized to expect work?
2. Is the Worker or process still expected to run?
3. When was liveness last proven, and by which observation?

Heartbeat record:

```text
Heartbeat {
  event_id: AuditEventId
  observed_at: Timestamp
  task_id: TaskId
  resource_id: ResourceId | N/A
  source_identity: IdentityRef | SupervisorIdentity
  sequence: MonotonicSequence | N/A
  liveness_kind: TASK | WORKER | PROCESS | PREVIEW_HEALTH
  status: EXPECTED | PAUSED | COMPLETING | FAILED | UNKNOWN
  evidence_ref: EvidenceRef | N/A
}
```

Minimum policy by resource type:

| Resource | Heartbeat requirement | Liveness evidence |
|---|---|---|
| `WORKER` | Required while `ACTIVE` | worker/supervisor heartbeat plus strong process identity readback when needed |
| `PROCESS` | Required when the process may outlive the Worker or is independently active | supervisor heartbeat plus strong process identity readback |
| `PREVIEW` | Required | owner Task/Worker heartbeat plus recorded health endpoint observation |
| `WORKTREE` | Not required | Git/evidence checks only when a lifecycle operation requires them |
| `TEMP_DIR` | Not required | lease/retention and identity evidence |
| `TEST_ENV` | Not required unless actively executing independently | lease/retention, or worker/process heartbeat when active |
| `ARTIFACT` | Not required | immutable retention/evidence relation |
| `DELEGATED_RUN` | Required while active | delegate heartbeat plus parent Worker relationship |

A missed heartbeat records `HEARTBEAT_MISSED` with the deadline, last valid observation, and reason. It stops admission of additional dependent work until reviewed. It does not prove a process is dead and does not authorize stopping or deleting it.

## 12. Expiry semantics

Expiry is evidence, not destructive authorization.

```text
expired resource
  -> STALE_CANDIDATE
  -> review, identity verification, and explicit cleanup authorization if appropriate
  -> CLEANUP_PENDING
  -> CLEANED or CLEANUP_FAILED
```

It must never be interpreted as:

```text
expired resource -> delete
```

Expiry rules:

- Task `expires_at`, resource `ttl`, worker timeout, missing heartbeat, and retention deadline are separate fields with separate meanings. They may corroborate each other but are not interchangeable.
- Expiry must preserve the lease, last known identity, last heartbeat, Task state, linked evidence, and audit history.
- An expired active worker or preview becomes reviewable and blocks further autonomous admission for that resource. A later authorized Janitor contract may define safe termination and cleanup procedures; TC1 does not.
- A passive artifact or worktree can exceed retention without implying it is safe to delete. Review/evidence, dirty/lock state, and shared/canonical status remain preconditions.
- Clocks may drift and processes may be paused. An expiry decision must record the time source and policy version used.

## 13. Cleanup authority

Cleanup authority is classified by blast radius. The authority class sets a maximum capability; each request still needs an explicit authorized principal, target identity verification, safety preconditions, audit events, and readback verification.

| Class | Scope | Autonomous status in AP0 |
|---|---|---|
| `C0` | Metadata-only actions: mark candidate, record evidence, request review; no runtime mutation | Permitted when otherwise authorized |
| `C1` | A worker's own isolated temporary resources, created and strongly identified by that worker | Future bounded use only; not automatically granted by TC1 |
| `C2` | Bounded development-runtime resources: task worker/process, isolated preview, task worktree, test environment, and artifacts | Future bounded use only with a Janitor contract and explicit Run Authorization |
| `C3` | Shared infrastructure: shared caches, shared runners, Docker resources, network/system services, shared worktrees | Not autonomously granted in AP0 |
| `C4` | Production infrastructure or data | Not autonomously granted in AP0; human explicit authorization required |

Rules:

- AP0-TC1 authorizes C0 documentation/evidence semantics only. It authorizes no actual cleanup.
- C1 and C2 are future capabilities, not implied permissions. Their later contract must specify resource-type allowlists, identity-safe target matching, dry-run/readback behavior, retry limits, failure handling, and human gates.
- C3 and C4 autonomous cleanup are prohibited in AP0. Docker mutation, systemd mutation, host cache deletion, shared-worktree removal, production mutation, and similar actions remain outside this contract.
- A cleanup request must include the resource ID, Task ID, strong resource identity, observed state, reason, requested authority class, authorization reference, and preconditions. It must create `CLEANUP_REQUESTED` before action and retain `CLEANUP_FAILED` on failure.
- Cleanup completion requires post-action readback of the exact recorded target or an equally strong verified postcondition; a successful command exit alone is insufficient.

## 14. Audit events

Audit events are immutable, append-only records. They must support observability without parsing terminal logs.

Common envelope:

```text
AuditEvent {
  event_id: AuditEventId
  event_type: EventType
  occurred_at: Timestamp
  task_id: TaskId | N/A
  resource_id: ResourceId | N/A
  actor: IdentityRef | SupervisorIdentity
  correlation_id: CorrelationId
  schema_version: Version
  payload: TypedEventPayload
  prior_event_hash: Hash | N/A
}
```

Minimum event types and required intent:

| Event | Minimum payload |
|---|---|
| `TASK_CREATED` | Task ID, creator, requester, scope summary, risk class, expiry |
| `TASK_STARTED` | Task ID, authorized actor, prior state, new state |
| `RESOURCE_ALLOCATED` | resource ID/type, Task ID, owner, lease policy, expected identity |
| `WORKER_STARTED` | worker ID, Task ID, strong process identity, cwd, worktree, branch, head SHA, timeout |
| `HEARTBEAT` | Task/resource IDs, observation time, liveness kind, status, source, evidence reference |
| `VALIDATION_STARTED` | Task ID, validation scope, actor/resource, evidence plan |
| `VALIDATION_FINISHED` | Task ID, result, evidence references, limitations |
| `TASK_TERMINAL` | Task ID, terminal outcome, actor, result/evidence reference |
| `RESOURCE_STALE` | resource ID, Task ID, reason, last known identity/liveness, policy deadline |
| `CLEANUP_REQUESTED` | resource ID, exact target identity, reason, authority class, authorization reference, preconditions |
| `CLEANUP_STARTED` | resource ID, executor, identity recheck result, bounded action reference |
| `CLEANUP_FINISHED` | resource ID, verified postcondition, readback evidence, executor |
| `CLEANUP_FAILED` | resource ID, failure category, preserved identity/evidence, next required gate |
| `HUMAN_GATE_REQUIRED` | Task/resource ID, blocked action, reason, required approver/authority class |

Recommended additional events are `TASK_PAUSED`, `TASK_BLOCKED`, `RESOURCE_TERMINAL`, `PREVIEW_HEALTH_OBSERVED`, `WORKTREE_INSPECTED`, `OWNERSHIP_UNKNOWN_DISCOVERED`, and `RESOURCE_HANDOFF_REQUESTED`.

Events must record facts and references, not terminal-log parsing assumptions. Sensitive values, credentials, and unrestricted command output must not be embedded in event payloads.

## 15. Paperclip compatibility

TC1 intentionally does not implement Paperclip. It defines boundaries so Paperclip can later become the canonical control plane for:

- Task state and immutable Task identity;
- Resource Lease registry and resource budgets;
- history and immutable audit events;
- permissions, cleanup authority, and human gates;
- limits, timeouts, checkpoints, and resumption policy.

Compatibility requirements:

1. Task IDs and Resource IDs must be opaque, immutable, globally unique, and portable across Hermes, Paperclip, and worker runtimes.
2. Task and Resource Lease schemas must be versioned and serializable without depending on Hermes internal database layout, terminal history, PID-only identity, or tool-specific cache paths.
3. Hermes may act as a coordinator, worker launcher, and event producer, but it must not be the sole state database or sole source of ownership truth.
4. A future Paperclip control plane may import existing Task/lease/event records while preserving identity, provenance, timestamp, and unknown fields. It must not rewrite historical ownership to make a legacy resource appear owned.
5. Workers must be able to receive a capability-scoped Task/lease reference and emit events through a transport-neutral interface. They must not require direct access to the entire runtime registry.
6. Paperclip adoption must preserve the distinction between task business state, resource state, evidence retention, and cleanup authority.

## 16. Mapping of AP0-TC0 resources

The following mapping translates the AP0-TC0 snapshot into this model. It is an observation and reconciliation backlog, not a registry import or ownership assignment. No Task owner is invented. All unknown ownership is explicitly `UNKNOWN`.

| Baseline resource | Proposed resource type | Observed identity / evidence | Proposed ownership mapping | Current lifecycle classification | Missing fields before managed admission |
|---|---|---|---|---|---|
| Hermes PID 1610802 | `PROCESS` (and possible coordinator `WORKER` only if later proven) | PID 1610802; started 2026-08-24 01:07:50 UTC; process group 1610802; stopped; archive CWD | `task_id = UNKNOWN`; owner = `UNKNOWN`; no lease may be fabricated | `ACTIVE_UNKNOWN` / review candidate, not automatically stale or deletable | launcher, canonical role, Task/Worker relation, process start/boot identity record, heartbeat, timeout, retention, cleanup authority |
| 14 Codex sandbox chains | `WORKER` + subordinate `PROCESS` per chain | 14 detached `codex-linux-sandbox` parents, PPID 1, with listed command families | `task_id = UNKNOWN`; owner = `UNKNOWN` | `STALE_CANDIDATE` per TC0; not safe to terminate | Task/worker IDs, strong process identities, task scope, start/timeout, heartbeat, results, explicit cleanup policy |
| 14 pytest descendants | `PROCESS` subordinate to a `WORKER` | 14 sleeping pytest-related descendants under the detached chains | `task_id = UNKNOWN`; owner = `UNKNOWN` | `STALE_CANDIDATE` per TC0; not safe to terminate | parent worker lease, strong process identity, expected runtime, heartbeat/status, result/evidence link, cleanup authority |
| Next preview `:3100` | `PREVIEW` + backing `PROCESS` | Next PID 2761290; parent PID 2761289; all-interface bind; canonical `apps/web`; started 2026-09-09 23:34:37 UTC | `task_id = UNKNOWN`; owner = `UNKNOWN` | `ACTIVE_UNKNOWN` | branch at launch, head SHA, worktree lease, bind authorization, health endpoint, Task/Worker heartbeat, TTL, cleanup policy/authority |
| Next preview `:37891` | `PREVIEW` + backing `PROCESS` | Next PID 3106835; parent PID 3106834; all-interface bind; canonical `apps/web`; started 2026-09-10 20:08:40 UTC | `task_id = UNKNOWN`; owner = `UNKNOWN` | `ACTIVE_UNKNOWN` | branch at launch, head SHA, worktree lease, bind authorization, health endpoint, Task/Worker heartbeat, TTL, cleanup policy/authority |
| Registered canonical worktree | `WORKTREE` with kind `CANONICAL` | `/home/megabrain-hermes/workspace/megabrain`; branch/HEAD recorded in baseline | Not a Task Worktree; task owner = `N/A`; stewardship owner = `UNKNOWN` in this contract | retained canonical workspace; outside Task cleanup | canonical stewardship/retention policy, shared-access policy, formal evidence relation |
| Nine registered `agent/*` worktrees | `WORKTREE` with kind `TASK` only after evidence-backed registration | canonical Git registry listed nine named agent worktrees | `task_id = UNKNOWN` for each; owner = `UNKNOWN` | ownership/retention review required; behind status is not deletion evidence | task IDs, branch/base/head, dirty/lock state, PR/evidence relation, retention class, cleanup state |
| Six detached review/install worktrees | `WORKTREE` with kind `TASK` or evidence/review retention class only after proof | TC0 listed detached install sources and four review worktrees | `task_id = UNKNOWN`; owner = `UNKNOWN` | `STALE_CANDIDATE` for review; not safe to delete | requester, review/evidence relation, dirty/lock status, retention class, authority |
| `/tmp` | shared host location; individual `TEMP_DIR` child entries may become leaseable | 1,228,675,929 bytes and 60,960 files at capture; no ownership metadata | shared parent owner = `UNKNOWN`; no blanket Task owner | `UNKNOWN` | per-entry lease marker/registry, exact path identity, creator Task, TTL, retention, cleanup policy |
| Hermes cache | shared runtime location; child `TEMP_DIR`, `ARTIFACT`, `DELEGATED_RUN`, or `TEST_ENV` entries may become leaseable | `~/.hermes/cache`, active scratch/terminal/browser/delegation/web cache trees | shared parent owner = `UNKNOWN`; no blanket Task owner | `UNKNOWN` / runtime data | child resource IDs, Task links, retention classes, evidence references, cleanup authority |
| Review worktrees / `workspace/reviews` tree | `WORKTREE` and associated `ARTIFACT` resources where evidence proves separation | review tree includes detached registered worktrees and other contents | `task_id = UNKNOWN`; owner = `UNKNOWN` | retention and ownership review required | per-worktree Task lease, evidence/PR relation, dirty state, retention, cleanup state |

Additional baseline locations such as tool caches, `.next`, `node_modules`, backups, and `workspace/evidence` are not assigned Task owners by this contract. They require separately scoped discovery and individual lease identity before they can enter automated cleanup.

## 17. Open questions

1. What control-plane service, datastore, and durability properties will host the canonical Task, Resource Lease, and immutable event registry before Paperclip is introduced?
2. Which stable identity format should be used for human, agent, service, Task, Resource, event, evidence, and correlation identifiers?
3. What is the authoritative host/process identity source for `(pid, start time, boot ID)` and how will it be collected without granting workers broad host inspection?
4. What admission mechanism can guarantee register-before-use for worker spawn, port allocation, worktree creation, and temporary directories while preserving failure evidence?
5. What default resource budgets and preview/worker TTLs are appropriate for development, and who approves exceptions?
6. What precise health endpoint contract is required for previews, including authentication, bind address, health timeout, and access boundary?
7. What is the formal relationship between repository Task Contract states and this runtime Task state machine? A mapping is needed, but neither should silently overwrite the other.
8. How will delegated runtimes such as Codex sandboxes, browser sessions, virtual environments, and future containers emit authenticated heartbeats and results?
9. Which evidence/PR/review conditions determine worktree and artifact retention, and who may release them after review resolution?
10. What sanitized, read-only observability mechanism can provide container identity, labels, network, mounts, restart policy, health, and published ports without Docker control?
11. What future Janitor contract will define C1/C2 cleanup target verification, mandatory preconditions, dry-run behavior, retries, failure handling, and human gates?
12. Which legacy resources can be reconciled through evidence, and which must remain `UNKNOWN` until a human decides their disposition?

## 18. Recommended AP0-TC2

AP0-TC2 should be a separately authorized, non-destructive control-plane design and evidence task: define the registry boundary, record format, admission protocol, and read-only reconciliation procedure needed to make TC1 operational without creating or mutating runtime resources.

Recommended scope:

1. Specify the authoritative Task/Resource Lease/Event storage boundary, schema versioning, identity generation, retention, integrity, and access-control model; keep Hermes as an event producer/coordinator rather than the sole database.
2. Define a register-before-use admission protocol for Worker, Process, Preview, Worktree, Temp Dir, Test Env, Artifact, and Delegated Run resources, including compensation records when creation fails.
3. Define read-only collection adapters for strong process identity, Git worktree state, preview listener/health evidence, and sanitized container observability; do not grant Docker control or perform runtime mutation.
4. Define Task-to-repository Task Contract correlation and the exact mapping between human approval, runtime state, risk class, allowed operations, resource budget, and human-gate events.
5. Define heartbeat transport, timing policy, clock source, missed-heartbeat escalation, pause/resume rules, and terminal-worker behavior.
6. Define C1/C2 Janitor preconditions as a future specification only: identity-safe targeting, dirty/review/evidence protections, cleanup request/review/verification records, and explicit refusal paths. Do not execute cleanup.
7. Prepare a read-only reconciliation report format that maps legacy resources to `UNKNOWN`, `UNOWNED_UNKNOWN`, or evidence-backed leases without inventing Task owners.
8. Validate the specification with schema/state-machine review, examples for each initial resource type, negative cases for PID reuse and stale candidates, documentation review, and `git diff --check`. No process termination, cleanup, Docker/systemd mutation, preview shutdown, worktree removal, branch deletion, cache deletion, push, PR, merge, or production action is in scope.

## Final verdict

AP0_TC1_CONTRACT_READY
