# AP0-TC8A — Worker Runtime Contract & Architecture
Status: design only; no runtime, migration, service, or production mutation
Date: 2026-09-30
Predecessors: AP0 Control Plane contract/implementation design and current `services/control_plane`
## 1. Decision and boundary
```text
Control Plane -> Worker Manager -> finite Worker -> bounded result
```
The Control Plane remains the only authority for Task state, admission, leases, budgets, gates, heartbeats, checkpoints, audit events, and terminalization. The Worker Manager is a scoped client and launcher; it does not create a second policy engine, scheduler, database, or resource lifecycle.
TC8A creates only this document. It does not connect task discovery, create a service/unit, create a worktree, spawn a process, call a provider, mutate production, restart `megabrain-control-plane.service` or `megabrain-hermes-coordinator.service`, or change Coordinator's `IdleWorkSource` role.
## 2. Inherited invariants
- resource lifecycle: `ALLOCATED -> ACTIVE -> IDLE | HEARTBEAT_MISSED | STALE_CANDIDATE -> TERMINAL`;
- creation: `AllocateResource -> bounded external creation -> BindResourceIdentity -> ACTIVE`; creation failure terminalizes and never deletes the lease;
- one Worker per Task and one Worker globally;
- Worker timeout policy: default 2700 seconds, maximum 7200 seconds;
- heartbeat policy: 30-second interval, missed at 90 seconds, 60-second grace;
- strong process identity is `pid + start_time + boot_id`; PID alone is invalid;
- old `boot_id` after a reboot never identifies a current process;
- missing heartbeat, stale status, terminalization, and cleanup are distinct;
- UDS/capability-scoped Control Plane access; Workers never write SQLite.
## 3. Required identity-contract correction
Current `AllocateResource(WORKER)` rejects an expectation without `pid`, `start_time`, and `boot_id`; current binding requires canonical equality between that expectation and the submitted identity. This is incompatible with required pre-spawn allocation because PID and start time do not exist yet.
TC8B must replace that overloaded interpretation with two typed values:
```text
LaunchExpectation (pre-spawn) != ObservedProcessIdentity (post-spawn)
```
`expected_identity` remains the stored JSON column name for compatibility, but for `WORKER` it stores a versioned `LaunchExpectation`, not a guessed process identity. `bound_identity` stores the immutable `ObservedProcessIdentity`.
### 3.1 Minimal safe LaunchExpectation
```text
LaunchExpectation {
  kind: "WORKER_PROCESS_V1"
  expected_boot_id
  expected_uid
  executable_class
  worktree_ref
  nonce_sha256
}
```
Before `AllocateResource`, the Worker Manager generates a high-entropy single-use launch nonce with the OS CSPRNG and submits only `nonce_sha256` in the expectation. The Control Plane then generates the canonical `resource_id` and persists the expectation containing only the digest. The allocation response never contains the raw nonce, so idempotency replay persists and returns only non-secret allocation data. The Manager keeps the raw nonce only in memory across the allocation round-trip and, after allocation succeeds, delivers it to the child over a dedicated inherited local descriptor. It is never put in the Task Packet, result, audit event, checkpoint, stdout/stderr, persisted request, or idempotency response. Binding presents the raw nonce only long enough for the Control Plane to compare its digest and discard it.
If the Manager loses the in-memory nonce after allocation, the lease remains `ALLOCATED`; it must not spawn or bind a replacement from guessed or recovered material. Recovery is reconciliation followed by a policy-authorized terminalization path.
`executable_class` is an allowlisted configured launcher profile, not a Task-supplied path or command. `worktree_ref` is a validated, lease-bound worktree reference/path identity; TC8B may use a validated placeholder reference until TC8E implements worktrees. No PID, start time, process group, executable path, or caller-selected command appears in this pre-spawn expectation.
### 3.2 ObservedProcessIdentity and matching
```text
ObservedProcessIdentity {
  pid
  start_time
  boot_id
  uid
  parent_pid | launcher_identity
  process_group
  cwd
  executable
  cgroup | null
}
```
The first three fields are mandatory. The remainder is corroborative when applicable. A narrow launcher/process-observation adapter obtains it from its exact child handle and bounded host readback, not Worker text.
```text
matches_launch_expectation(expectation, observation, launch_nonce) =
  observation.pid is valid
  and observation.start_time is valid
  and observation.boot_id == expectation.expected_boot_id
  and observation.uid == expectation.expected_uid
  and observation.executable matches expectation.executable_class
  and observation.cwd matches expectation.worktree_ref
  and observation has the manager's expected parent/launcher relation
  and sha256(launch_nonce) == expectation.nonce_sha256
```
The Control Plane accepts a binding only when this function is true, the observation has strong identity, the caller capability is scoped to the same Task and canonical `resource_id` lease, and evidence came through the allowlisted launcher/process-adapter path. The lease row itself supplies the resource binding; `resource_id` is not duplicated inside the pre-spawn expectation. It persists only the observation and safe evidence reference, never the raw nonce. `resource_id`, boot ID, UID, worktree, executable class, parent/launcher relation, nonce digest, and strong identity jointly establish association.
PID, process name, CWD, launch nonce, resource ID, or manager assertion alone are never sufficient.
## 4. Worker lifecycle
```text
1. Task READY or RUNNING
2. policy/admission
3. AllocateResource(WORKER) commits ALLOCATED
4. receive resource_id; retain the pre-generated raw launch nonce in memory
5. prepare isolated allowed runtime
6. spawn finite process
7. observe strong process identity
8. BindResourceIdentity commits ACTIVE
9. manager heartbeat
10. bounded execution
11. bounded result/evidence
12. MarkResourceTerminal
```
There is no `spawn -> AllocateResource` path. No Task Packet, autonomous work, or provider call reaches a spawned process before successful identity binding.
If the Manager crashes after allocation but before spawn, the lease remains `ALLOCATED`; reconciliation is required and Worker existence is never assumed. If it crashes after spawn but before binding, the lease remains `ALLOCATED` and runtime is indeterminate: do not issue work, adopt it, kill it, respawn it, or infer cleanup. Record read-only reconciliation evidence for later policy.
A Worker is finite:
```text
start -> immutable Task Packet -> bounded turns -> result/evidence -> exit
```
It is neither a daemon nor an infinite conversation. It has `task_id`, `resource_id`, `correlation_id`, timeout, execution role, worktree reference, Task Packet, and model-call budget context.
## 5. Worker Manager authority and launcher
The Manager consumes admitted work only. It may get the scoped Task, allocate a Worker lease, prepare an allowlisted environment, launch one finite Worker, observe/bind it, heartbeat it, collect its bounded outcome, terminalize its lease, and create a required checkpoint through explicitly scoped capability.
It may not create arbitrary Tasks; change immutable Task scope/budgets; approve human gates; execute arbitrary shell; write SQLite; delete worktrees; kill or adopt unknown processes; access Docker; merge PRs; deploy; or mutate production.
The initial production capability must be task-scoped and issued per lease. Its minimal operation set is:
```text
GetTask, GetTaskResources,
AllocateResource(WORKER only), BindResourceIdentity,
RecordHeartbeat, MarkResourceTerminal,
EvaluateProviderPreflight, AdmitModelCall,
CreateCheckpoint and constrained TransitionTask only when required by the
specific Task lifecycle.
```
`AppendEvent`, delegation operations, broad gate consumption, arbitrary resource allocation, and cross-Task reads/mutations are not needed by the initial production Manager capability. Existing broad hermetic `WORKER_MANAGER` role membership is not a production grant. Current production capability profiles issue only Coordinator/Observer capabilities; TC8H adds no Manager capability until this smaller profile and task/resource scope are enforced.
The launcher interface is narrow:
```text
WorkerLauncher.launch(LaunchSpec) -> RunningWorker
RunningWorker.observe_identity()
RunningWorker.poll()
RunningWorker.wait(timeout)
RunningWorker.terminate_owned()
RunningWorker.bounded_output()
```
`LaunchSpec` contains only configured executable class, argv list, validated cwd, allowlisted environment, deadline, local binding descriptor, and packet handle. It has no `shell`, arbitrary command, `sudo`, Docker, or unrestricted host API. Launch uses an argv list with `shell=False`; executable resolution is configured and validated, never supplied by a Task.
Ownership for management or termination is exactly:
```text
lease + resource_id + pid + start_time + boot_id
```
Before `terminate_owned`, the Manager re-observes that exact identity. A process without the full chain is `UNKNOWN_RUNTIME`: not adopted and not killed.
## 6. Packet, result, environment, and worktree
`WorkerTaskPacket` is serializable, immutable for one invocation, secret-free, and bounded to 64 KiB:
```text
{ schema_version, task_id, resource_id, correlation_id, objective,
  allowed_scope, acceptance_criteria, validation_commands, stop_conditions,
  context_refs }
```
It excludes full conversation history by default, raw capabilities, provider credentials, launch nonce, Control Plane signing material, and ambient secrets.
`WorkerResult` is machine-readable and at most 64 KiB:
```text
{ status, summary, changed_files, validation, checkpoint_required,
  evidence_refs, usage }
```
Captured stdout and stderr are evidence only, capped at 32 KiB per stream with truncation metadata/digest; they are never the canonical result. Result and packet schemas reject secret-bearing fields. `usage` exposes provider usage for Control Plane accounting; Worker self-reporting never substitutes for admission.
The execution environment is explicit and allowlisted. It excludes root credentials, Docker socket, production secrets, Control Plane signing key, Coordinator bootstrap secret, arbitrary SSH agent, and broad HOME inheritance.
An implementation Worker runs in an isolated Git worktree. The later worktree creator accepts only a validated repository, bounded branch name, and bounded worktree path; the Worker CWD is that worktree. TC8A creates neither worktree nor cleanup authority.
## 7. Provider, heartbeat, timeout, and reboot
Before every Worker model call the Manager performs:
```text
EvaluateProviderPreflight -> AdmitModelCall(execution_role=IMPLEMENTATION_WORKER)
```
Only `ADMIT` permits a provider call. `BLOCK_BUDGET`, `STOP_AND_CHECKPOINT`, `PAUSE_PROVIDER_QUOTA`, `BLOCK_PROVIDER_AUTH`, and `BLOCK_PROVIDER_UNKNOWN` stop the call and follow the returned disposition. TC8 begins with a fake executable and fake provider; no Codex/Hermes real Worker call is permitted.
The Worker reports local bounded liveness/result to its Manager. The Manager, not the model process, sends strictly increasing `RecordHeartbeat` sequences. At 90 seconds the Control Plane records `HEARTBEAT_MISSED`; at 150 seconds it records `STALE_CANDIDATE`. Neither proves death or authorizes cleanup.
The Manager records a monotonic start timestamp and deadline. At deadline it stops new model admission, captures timeout evidence, and may request bounded termination only of its re-observed exact Worker identity. It then terminalizes with a typed result such as `COMPLETED`, `FAILED`, `TIMEOUT`, `INTERRUPTED`, `RESOURCE_CREATION_FAILED`/`START_FAILED`, or `IDENTITY_BIND_FAILED`, preserving exit code, signal/termination type, last heartbeat, bounded output evidence, and completion artifact reference. Worker-process termination is lifecycle control for the exact bound child; Janitor cleanup of worktrees, temp paths, or artifacts is separate and deferred.
After reboot, a recorded boot ID cannot match the current host boot ID. Recovery is registry lease -> read-only observation -> mismatch/missing/inconclusive evidence -> reconciliation. It never auto-adopts, auto-respawns, or auto-cleans.
## 8. TC8 implementation sequence
Each slice should remain near or below 500 implementation LOC, 500 test LOC, and 1000--1300 total LOC; smaller is preferred.
- TC8B — Control Plane Worker Identity Contract Correction: typed expectation/observation validation, Manager-generated nonce with digest-only allocation, server-generated resource ID, matching function, service/protocol/adapter contract updates, and negative tests. Use JSON schema evolution and service validation; no DB migration is expected because both identity columns already hold generic JSON, but add one only if an invariant cannot be preserved without it.
- TC8C — Worker Manager Client + Lease Lifecycle: scoped client and fake-only allocation/bind/terminal lifecycle; no launcher or provider.
- TC8D — Finite Local Worker Runner: allowlisted fake executable, argv-only launcher, strong child observation, bounded output, and no shell.
- TC8E — Worktree Isolation + Task Packet: validated repository/worktree creation boundary, immutable packet/result codecs, secret-free size limits.
- TC8F — Heartbeat + Timeout + Crash Recovery: Manager heartbeat, deadline, exact-child termination request, crash/reboot reconciliation tests; no Janitor.
- TC8G — Provider/Model Admission Integration: fake provider first, mandatory preflight/admit dispositions, usage accounting, checkpoint dispositions.
- TC8H — Production Capability + Service Packaging: least-privilege Manager production capability and packaging only after fake lifecycle proof; no broad role grant and no production activation.
- TC8I — Human-Gated Worker Runtime Activation: explicit approval plus bounded activation evidence; still no automatic merge, deployment, or production mutation.
## 9. Consistency review
### Inherited invariants
`AP0_CONTROL_PLANE_IMPLEMENTATION_DESIGN.md` establishes two-phase allocation, immutable retained leases, scoped UDS capabilities, read-only reconciliation, strong `(pid,start_time,boot_id)`, non-destructive heartbeat escalation, and frozen worker/timeout/heartbeat policy. Current `policy.py` implements the stated limits. Current `service.py` enforces Worker allocation/global limits, records `ALLOCATED`, binds before `ACTIVE`, and evaluates heartbeat escalation. Current `auth.py` has the hermetic Manager role matrix and task/resource capability checks.
### Required contract corrections
Current `service.py` requires process fields in Worker `expected_identity` and requires exact expected/bound equality. Its `ProcessAdapter` also treats an expectation as a process identity. TC8B must correct those semantics as section 3 specifies. The older TC1 Worker diagram that shows `spawn -> allocate` is superseded for Workers by section 4; its later register-before-use rule remains inherited. Current production `auth.py` has no Worker Manager capability profile; TC8H must add only the least-privilege scoped profile described above.
### Deferred behavior
Paperclip discovery, Preview/Reviewer runtimes, Janitor, Docker, production deployment, automatic merge/approval, multi-worker/distributed workers, remote hosts, Kubernetes, queues, real provider calls, worktree cleanup, and runtime activation are outside TC8A.
## 10. Security invariants
1. No Worker spawn precedes committed allocation.
2. Initially there is one Worker globally.
3. Initially there is one Worker per Task.
4. Strong process identity is required before `ACTIVE`.
5. PID alone is insufficient.
6. An unknown process is never adopted.
7. Reboot never causes automatic Worker respawn.
8. No arbitrary shell is available.
9. The Worker environment has no root authority.
10. The Worker environment has no Docker authority.
11. The Worker Manager performs no production mutation.
12. No Worker flow can auto-merge.
13. Every model call requires Control Plane admission.
14. Timeout is mandatory.
15. Heartbeat is mandatory.
16. Every Worker is finite.
17. Terminalization never infers cleanup.
18. Task Packets and results contain no secrets.
19. Manager capability is Task/resource scoped.
20. Failure preserves audit evidence.
## Final verdict
AP0_TC8A_READY
