# AP0-TC6 — Persistent Hermes Coordinator Service Design

Status: implementation-ready design; no service installation, startup, provider mutation, user/group creation, or runtime mutation
Date: 2026-09-29
Canonical predecessor: `AP0_TC5_BUDGET_ENFORCEMENT_READY`
Canonical base: `origin/dev @ 8d1919b70b766fc6e2f49e209b430df4529a8b9e`

## 1. Purpose

This document defines the persistent, local `megabrain-hermes-coordinator.service` runtime for AP0-TC7. It makes Hermes a bounded orchestration client of the Control Plane, not a permanent model conversation, Task, Worker, Task Resource Lease, database owner, or direct registry writer.

The core runtime is:

```text
persistent Coordinator process
  -> task discovery/admission
  -> Control Plane budget and provider checks
  -> bounded Hermes coordinator turn
  -> result interpretation
  -> usage evidence and checkpoint
  -> idle/retry only when eligible
```

The coordinator remains running through provider quota pauses. A model turn does not.

## 2. Verified Hermes runtime capabilities

The locally verified runtime is `Hermes Agent v0.21.5+4173.g1b91b8e (2026.9.24)`.

| Capability | Verified interface | TC6 use |
|---|---|---|
| Bounded turn | `hermes --oneshot PROMPT` or `hermes -z PROMPT` | Canonical LLM-backed coordinator decision boundary. |
| Per-turn usage report | `--usage-file PATH` | Writes JSON usage evidence, including on one-shot failure. |
| Provider preflight | `hermes usage --provider PROVIDER --json` | Read-only observation before model admission. |
| Headless backend | `hermes serve` | Optional future local operator/diagnostic surface, not the coordinator loop. |
| Messaging ingress | `hermes gateway` | Optional future task-request adapter, not a Task owner. |
| Isolated Hermes home | `$HERMES_HOME` | A dedicated coordinator profile/state location is required; shared interactive Hermes state is not coordinator state. |

The installed help confirms that one-shot mode emits only final text to stdout and that the usage report is written even when the turn fails. It also confirms `hermes usage` exits non-zero if a credential is absent or the usage fetch fails. TC7 must parse both exit status and bounded JSON/error evidence; neither command's human-readable output is a control-plane record.

## 3. Persistent process vs bounded model turns

The coordinator process and Hermes turns have independent state machines.

```text
Coordinator process:
STOPPED -> STARTING -> READY <-> DEGRADED -> STOPPING -> STOPPED
                                  \-> FAILED

Hermes coordinator turn:
ADMITTED -> STARTED -> COMPLETED
                    \-> FAILED
                    \-> INTERRUPTED
```

The process is long-lived system infrastructure. Its authority is only to evaluate and orchestrate eligible work through the Control Plane. Each LLM-backed decision is a fresh one-shot process with a compact Task Packet. It must not use `hermes --continue`, `hermes --resume latest`, conversation history, terminal history, or `~/.hermes/state.db` as autonomous execution state.

Example quota outcome:

```text
Coordinator state: READY
Provider state: QUOTA_EXHAUSTED
Task state: PAUSED_PROVIDER_QUOTA
Hermes turn: not started
```

A quota pause therefore does not trigger coordinator failure or systemd restart.

## 4. Coordinator responsibilities

The coordinator performs only these infrastructure/orchestration functions:

1. discover candidate Tasks through the Control Plane/Paperclip-facing task-request surface;
2. fetch Task, budget, checkpoint, active-resource, validation, and gate summaries;
3. perform read-only provider observation and record a sanitized provider state;
4. request Control Plane provider preflight and model-call admission;
5. build a compact Task Packet and execute one bounded Hermes decision turn only after `ADMIT`;
6. validate bounded result and usage evidence, then request permitted checkpoint, pause, state-transition, review, or Worker Manager actions;
7. emit infrastructure health and structured logs; and
8. reconcile read-only after restart/reboot before resuming eligible Tasks.

It does not implement product features, open registry SQLite files, manage Docker, issue arbitrary shell commands, create a Worker directly, mutate production, adopt legacy resources, or turn an unbounded Hermes session into a scheduler.

## 5. Service lifecycle

| State | Meaning | Admission behavior |
|---|---|---|
| `STOPPED` | No process is running. | None. |
| `STARTING` | Local configuration, filesystem, Control Plane, and identity checks are in progress. | No Task/Worker/model admission. |
| `READY` | Control Plane connection, runtime identity, and initial provider observation are valid. | Eligible Task work may be evaluated. |
| `DEGRADED` | The process is alive but a required dependency/evidence path is unavailable or stale. | No new model calls, Worker requests, or runtime mutations. Reconnect/read-only diagnostics only. |
| `STOPPING` | SIGTERM was received. | Stop new admission immediately; drain one bounded active turn only. |
| `FAILED` | Process cannot establish a safe operational baseline or exits unexpectedly. | None; systemd may restart only for process failure. |

`READY` is service health, not a guarantee that any provider is available. `DEGRADED` is not a Task state. Provider blocking is recorded on the affected Task/channel while the coordinator normally remains `READY` and idle.

## 6. Task Packet

Each one-shot receives a versioned, compact, secret-free packet. It contains only the evidence needed for the next permitted decision:

```text
TaskPacket v1
- task_id, task state, task revision, objective, risk class
- allowed-operation summary and explicitly permitted next action
- budget remaining, model-admission correlation id, context thresholds
- provider channel/state/observation timestamp and fallback authorization
- current checkpoint reference and compact checkpoint facts
- active resource summaries and pending gates
- validation/review summaries and bounded evidence references
- bounded repository/status evidence when explicitly authorized
- required output schema and refusal/stop rules
```

The packet excludes complete conversations, raw terminal output, unrestricted repository history, provider credentials, capability proofs, environment dumps, private keys, full logs, and unbounded artifact contents. Evidence references resolve only through separately authorized, bounded readers.

TC7 should require a deterministic packet-size cap and validate it before spawn. A packet that cannot be represented within the cap must checkpoint/block for packet compaction; it must not silently include prior history.

## 7. Control Plane interaction

The Control Plane remains canonical for Task state, model admissions, provider observations, budgets, checkpoints, gates, and audit history. The coordinator is a UDS client only.

For each eligible candidate, the coordinator performs this ordered protocol:

```text
GetTask + GetExecutionBudget + GetTaskResources + GetPendingGates
  -> validate Task eligible and no stop condition
  -> obtain/refresh provider observation when stale
  -> RecordProviderObservation
  -> EvaluateProviderPreflight
  -> AdmitModelCall(execution_role=COORDINATOR)
  -> only ADMIT permits hermes --oneshot
  -> validate result/usage evidence
  -> checkpoint and permitted state/action request
```

No `AdmitModelCall` result other than `ADMIT` permits a Hermes invocation. `STOP_AND_CHECKPOINT` requires a checkpoint and no new turn. `BLOCK_BUDGET`, provider blocks, Control Plane errors, invalid capabilities, and unsupported schemas fail closed.

TC5 currently permits coordinator budget reads, preflight, and coordinator model admission, but its role map does not permit `HERMES_COORDINATOR` to call `RecordProviderObservation`. TC7 must add that one narrowly scoped operation to the coordinator role/capability contract, restricted to configured provider channels and sanitized `hermes-usage-v1` observations. This is a required Control Plane extension, not a direct SQLite write.

## 8. Budget admission

The Control Plane must make the admission decision before a one-shot subprocess exists:

```text
Task eligible?
  -> GetExecutionBudget
  -> observation fresh enough?
  -> EvaluateProviderPreflight
  -> AdmitModelCall(COORDINATOR)
  -> ADMIT?
```

Logical model admission is the Control Plane's Task-budget unit. It is consumed transactionally by `AdmitModelCall` and remains consumed if process spawn or Hermes execution later fails; the admission represented a permitted execution opportunity. The coordinator must checkpoint/report the later failure rather than attempt an unadmitted replacement call.

Coordinator defaults retain TC5 policy: component soft limit 8, hard limit 12; Task global model-call hard limit remains authoritative; context soft/hard limits are 80k/120k tokens. A task-global hard-limit refusal blocks coordinator, Worker, continuation, retry, and reviewer calls.

## 9. Provider observation/preflight

The initial observer is exactly:

```text
hermes usage --provider <configured-channel-provider> --json
```

It is executed as a read-only, bounded subprocess before a model call when the previous observation is absent or older than the configured freshness interval. TC7 should initially use a conservative five-minute freshness limit and require a fresh observation immediately after a prior provider failure or recovery attempt.

The observer maps only sanitized facts to Control Plane states:

| Evidence | Recorded state | Required result |
|---|---|---|
| Valid configured account and usable window | `AVAILABLE` | Continue to Control Plane preflight. |
| Missing/expired/invalid authentication evidence | `AUTH_EXPIRED` | `BLOCK_PROVIDER_AUTH`; no blind retry. |
| `usage_limit_reached` or confirmed exhausted window | `QUOTA_EXHAUSTED` | checkpoint, Task `PAUSED_PROVIDER_QUOTA`, no Hermes turn, no short retry. |
| Bounded network/provider failure that cannot establish quota/auth state | `TRANSIENT_FAILURE` | Block normal admission; retry only through existing bounded retry policy. |
| Unparseable, unsupported, absent, or ambiguous result | `UNKNOWN` | Fail closed; no model call. |

If a provider returns `reset_at`, record it only as sanitized observation/evidence. It is not a permanent schedule, wake-up timer, or authorization to retry. A future retry/recovery always requires a fresh observation and new admission. Explicit fallback remains permitted only where the Task explicitly allows it and the alternate channel separately passes this same flow.

## 10. Usage accounting

After `AdmitModelCall=ADMIT`, create an owner-only usage path below the coordinator runtime directory:

```text
/run/megabrain-hermes-coordinator/usage/<correlation_id>.json
usage directory: 0700
usage file:      0600
```

Invoke the bounded turn in a new process group:

```text
hermes --oneshot <TaskPacket> --usage-file <usage-path>
```

On exit, including non-zero exit or interruption, TC7 must:

1. stat the expected file without following symlinks and require a regular file owned by `megabrain-hermes` with mode `0600`;
2. parse bounded JSON using a strict schema and reject duplicate/unknown critical fields and non-finite numbers;
3. record a sanitized usage-evidence summary linked to `task_id` and `correlation_id`;
4. checkpoint/result-transition when permitted; and
5. unlink the transient file only after durable evidence is confirmed. A malformed/missing file is retained only when safe for incident collection in the owner-only runtime directory and is removed on reboot by `RuntimeDirectory` cleanup.

The Control Plane budget database is canonical. The usage file is never an alternate budget ledger.

Two different values must be retained without conflation:

```text
logical_model_admission = one successful Control Plane ADMIT decision
hermes_reported_api_calls = integer reported by Hermes for that one-shot
```

`api_calls` may exceed one logical admission because Hermes may make multiple provider calls. Independent TC7A1 compatibility inspection verified the installed ledger schema: main-loop fields use `estimated_cost_usd`, `cache_read_tokens`, `cache_write_tokens`, `reasoning_tokens`, `total_tokens`, and `api_calls`, with optional `auxiliary` and `total_including_auxiliary` blocks. When `total_including_auxiliary.api_calls` is present, it is the post-run API-call total used for overrun evidence; main-loop `api_calls` must not hide auxiliary provider consumption. Token counts and estimated cost are usage telemetry. Cache counters and estimated cost must not be represented as subscription-billing truth. TC7 records numeric values only after schema validation, labels their source as `hermes_usage_report`, and never back-calculates provider quota or budget from them.

## 11. `hermes serve` classification

`hermes serve` is not the autonomous coordinator loop and is not required for recovery. It is an optional, separate future local surface for operator UI, desktop integration, diagnostics, or remote-control backend.

If a later task enables it, it must bind `127.0.0.1` by default, use a separately scoped service/profile, have independent health and credentials, and never gain direct registry-file access. It cannot substitute for Control Plane admission or make a long-lived model session canonical.

## 12. `hermes gateway` classification

`hermes gateway` is an optional ingress adapter, not a Task owner, worker manager, or bypass around Control Plane policy.

Future direction:

```text
Telegram / Discord / other channel
  -> Hermes Gateway
  -> validated Task Request
  -> Control Plane / Paperclip
  -> Coordinator
```

A message is only a request. It must still receive identity/risk classification, Task admission, gate evaluation, budget checks, provider preflight, and permitted operation scope. TC6 neither installs nor starts the gateway.

## 13. UDS and filesystem ownership

TC7 should use these canonical production locations and identities, created only by an approved root/systemd installation step:

| Object | Owner:group | Mode | Purpose |
|---|---|---:|---|
| `/var/lib/megabrain-control-plane/` | `megabrain-control-plane:megabrain-control-plane` | `0700` | Control Plane state only. |
| `registry.db`, `registry.db-wal`, `registry.db-shm` | `megabrain-control-plane:megabrain-control-plane` | `0600` | Canonical registry; coordinator has no filesystem access. |
| `/run/megabrain/` | `megabrain-control-plane:megabrain-control-plane-clients` | `0750` | Local UDS parent, recreated each boot. |
| `/run/megabrain/control-plane.sock` | `megabrain-control-plane:megabrain-control-plane-clients` | `0660` | AF_UNIX only; no TCP listener. |
| `/run/megabrain-hermes-coordinator/` | `megabrain-hermes:megabrain-hermes` | `0700` | Coordinator runtime and transient usage files. |
| `/var/lib/megabrain-hermes-coordinator/` | `megabrain-hermes:megabrain-hermes` | `0700` | Coordinator-owned non-registry state, including isolated `$HERMES_HOME`. |
| `/var/log/megabrain-hermes-coordinator/` | `megabrain-hermes:megabrain-hermes` | `0700` | Bounded diagnostic artifacts only; primary logs go to journald. |

`megabrain-control-plane-clients` is a dedicated group whose only intended non-Control-Plane member is `megabrain-hermes`. Group socket access is necessary to connect; it does not grant state-directory traversal, SQLite read/write, credential access, or authority beyond a valid short-lived capability. The UDS service must also inspect `SO_PEERCRED` and require the expected coordinator UID as corroborating evidence.

The current AP0 implementation's owner-only `0600` socket is intentionally replaced only in TC7, after tests prove group socket access plus per-request capability validation. This is a narrow API-boundary change, not a Python-convention boundary.

## 14. Capability bootstrap

TC7 must replace the current hermetic HMAC issuer with a production runtime capability authority. The proposed contract is:

1. The coordinator system identity is `role=HERMES_COORDINATOR`, `identity_id=megabrain-hermes-coordinator`; its Unix UID is `megabrain-hermes`.
2. Root provisions a unique opaque bootstrap secret and identifier only through systemd encrypted credentials. The coordinator receives it as `LoadCredentialEncrypted=control-plane-coordinator-bootstrap`; the Control Plane receives only its verifier/rotation material plus the issuer signing material through its own encrypted credentials.
3. systemd materializes credentials in the unit-private `/run/credentials/<unit>/` mount. The bootstrap value is never placed in environment variables, repository files, plain `/etc` files, logs, SQLite, Task Packets, usage files, or checkpoints.
4. Over the authenticated UDS, the coordinator calls a new `ExchangeCoordinatorBootstrap` operation. The Control Plane checks peer UID, bootstrap identifier/verifier, configured coordinator identity, expiry/rotation generation, and requested bounded operation set.
5. The Control Plane returns an in-memory, short-lived capability proof scoped to the coordinator identity, permitted task/channel scope, operation set, nonce, and five-minute expiry. The coordinator caches it only in process memory and obtains a replacement before expiry; it does not write it to disk.
6. The Control Plane validates proof signature/MAC, expiry, nonce, role, operation, task/resource/channel scope, and revocation generation on every request. It persists only non-secret capability identifier/digest, expiry, and audit correlation as needed.
7. Rotation is a root/human-controlled replacement of encrypted credentials and generation followed by controlled service restart. Revocation adds the bootstrap/capability generation to the Control Plane deny set immediately; requests with a revoked generation fail closed. Existing proofs have a maximum five-minute residual validity and are additionally rejected by immediate revocation lookup.

The production cryptographic implementation is deliberately not selected by TC6: TC7 must choose one reviewed, standard primitive and define serialization/key rotation tests. The security contract is fixed: no hardcoded secret, no permanent environment credential, no repository secret, no raw proof persistence, and no direct registry access.

Deployment is human-gated because root must provision service accounts, group membership, encrypted credentials, and a root-owned Hermes installation/profile boundary. This is not required for hermetic TC7 implementation/testing.

## 15. systemd design

TC7 may add source unit files under `deploy/systemd/`; it must not install or enable them. The proposed coordinator unit is:

```ini
[Unit]
Description=MegaBrain Hermes Coordinator
Wants=network-online.target megabrain-control-plane.service
After=network-online.target megabrain-control-plane.service

[Service]
Type=exec
User=megabrain-hermes
Group=megabrain-hermes
SupplementaryGroups=megabrain-control-plane-clients
WorkingDirectory=/var/lib/megabrain-hermes-coordinator
Environment=HOME=/var/lib/megabrain-hermes-coordinator
Environment=HERMES_HOME=/var/lib/megabrain-hermes-coordinator/hermes-home
Environment=PYTHONUNBUFFERED=1
ExecStart=/opt/megabrain/bin/megabrain-hermes-coordinator --config /etc/megabrain/hermes-coordinator.yaml --control-plane-socket /run/megabrain/control-plane.sock
Restart=on-failure
RestartSec=10s
TimeoutStopSec=45s
KillSignal=SIGTERM
KillMode=control-group
RuntimeDirectory=megabrain-hermes-coordinator
RuntimeDirectoryMode=0700
StateDirectory=megabrain-hermes-coordinator
StateDirectoryMode=0700
LogsDirectory=megabrain-hermes-coordinator
LogsDirectoryMode=0700
UMask=0077
StandardInput=null
StandardOutput=journal
StandardError=journal
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=tmpfs
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
LockPersonality=yes
RestrictNamespaces=yes
SystemCallArchitectures=native

[Install]
WantedBy=multi-user.target
```

Rationale and validation conditions:

| Directive | Proposed setting | Rationale / TC7 proof required |
|---|---|---|
| `User=` / `Group=` | fixed coordinator identity (`megabrain-hermes`) | Separates coordinator runtime from the Control Plane identity; its service home is isolated from interactive Hermes state. Root only provisions the Control Plane identity/client group and deployment boundary. |
| `WorkingDirectory=` | coordinator state directory | Never run service from an interactive terminal or mutable task worktree. |
| `ExecStart=` | root-owned installed wrapper, no shell | Pins a deployment artifact and eliminates shell/TTY dependency. |
| `Restart=on-failure` | yes | Recovers crashes; quota/provider pauses remain in-process `READY`/idle and do not cause exit. |
| `TimeoutStopSec=45s` | yes | Provides a bounded 35-second application grace plus final systemd containment. |
| `KillSignal=` / `KillMode=` | `SIGTERM` / `control-group` | Stops admission and ensures one-shot child processes are not intentionally orphaned. |
| `Environment=` | non-secret locations/flags only | Uses isolated coordinator Hermes home; no credential values. |
| `RuntimeDirectory=` / `StateDirectory=` / `LogsDirectory=` | owner-only | systemd creates bounded writable locations without registry access. |
| `NoNewPrivileges` | yes | The coordinator cannot acquire privilege through exec. |
| `PrivateTmp` | yes | Prevents use of shared `/tmp` as Task state or usage evidence. |
| `ProtectSystem` | `strict` | Source/runtime binaries are read-only; systemd-managed writable directories are the only writes. |
| `ProtectHome` | `tmpfs` | Blocks inherited interactive home/session state. Requires TC7 deployment test proving Hermes uses isolated `$HERMES_HOME` and a root-owned installed runtime outside `/home`. Do not enable until that test passes. |
| kernel/control-group protections | yes | No coordinator need to tune kernel, load modules, or manage cgroups. |
| `RestrictSUIDSGID`, `LockPersonality`, `RestrictNamespaces`, `SystemCallArchitectures` | yes / native | Reduces unnecessary privilege/escalation surface. TC7 must run one-shot, provider observation, UDS, and shutdown tests under these restrictions; any exception must be justified and documented rather than silently removed. |

The proposed unit intentionally omits `Requires=megabrain-control-plane.service`: temporary Control Plane loss must produce coordinator `DEGRADED`, not force a restart loop. The coordinator still starts after it and requires it to become `READY`.

The `HERMES_HOME` behavior is documented by Hermes, but the exact installed build and its provider configuration must be exercised under `ProtectHome=tmpfs` before production activation. Until then, a human deployment gate remains open; TC7 must not weaken this to shared interactive `~/.hermes` access as a workaround.

## 16. startup

The exact startup sequence is:

```text
systemd starts coordinator
  -> create owner-only runtime/state/log directories
  -> load bounded non-secret config and private systemd credentials
  -> validate ownership/mode of runtime paths and credential handles
  -> connect Control Plane UDS; validate protocol and registry readiness
  -> exchange/validate coordinator capability
  -> run read-only provider observation for configured channel(s)
  -> RecordProviderObservation
  -> register service instance STARTING then READY
  -> enter idle event loop and 30-second health heartbeat cadence
```

No autonomous model call is made merely because the process starts. If registry readiness, capability exchange, or provider observation cannot be established, record local structured evidence where safe, set infrastructure health to `DEGRADED` when the Control Plane is reachable, and do not admit work.

## 17. graceful shutdown

On `SIGTERM` the application performs this bounded sequence:

```text
atomically set local stopping flag
  -> stop Task discovery and all new model/Worker admissions
  -> publish STOPPING infrastructure health when UDS remains available
  -> if no active Hermes turn: close UDS and exit 0
  -> if active turn: wait up to 35 seconds for result + usage file
       -> preserve valid usage/result evidence
       -> create checkpoint if Control Plane and evidence are available
       -> otherwise emit bounded local failure evidence and exit nonzero
  -> terminate remaining child process group before service exit
  -> close UDS and exit
```

If the active one-shot exceeds the 35-second application grace, it receives `SIGTERM`; the coordinator waits only within `TimeoutStopSec=45s`. systemd then contains remaining children through `KillMode=control-group`. The coordinator never intentionally orphans a one-shot. A forced interruption leaves the Task's last committed state authoritative; recovery treats the admitted turn as indeterminate until result/usage/checkpoint reconciliation.

## 18. crash recovery

A restarted coordinator reconstructs only from:

```text
Control Plane Registry + immutable checkpoints + read-only reconciliation
```

It does not derive ownership, success, or continuation from a PID, terminal, last log line, stale Hermes session, usage-file age, or filesystem timestamp. It first lists non-terminal/affected Tasks and their checkpoints/resource summaries, then asks bounded adapters to reconcile known runtime resources. Unknown or legacy Workers stay `UNOWNED_UNKNOWN`/`STALE_CANDIDATE`; the coordinator never adopts one because it happens to exist.

An admitted turn without a durable terminal result is treated as interrupted/indeterminate. The coordinator preserves the original admission cost, obtains a fresh provider observation, and requires a valid checkpoint plus new admission before any new continuation decision.

## 19. host reboot recovery

After a host reboot, the intended order is:

```text
Control Plane service starts
  -> validates/restores registry and marks admission readiness
  -> coordinator starts
  -> coordinator registers new boot_id and instance identity
  -> read-only reconciliation of non-terminal Task state/checkpoints
  -> fresh provider observation/preflight
  -> eligible Task continuation only after new model admission
```

Pre-reboot PIDs and process identities are invalid because `boot_id` changes. No Worker continuation, new Worker request, or model turn occurs before registry readiness, checkpoint validation, reconciliation, provider preflight, and budget admission.

## 20. infrastructure health/heartbeat

Recommendation: implement a new Control Plane infrastructure-service projection in TC7, rather than reusing Task Resource Leases or relying solely on systemd/journald. The Control Plane is already the durable runtime authority; a separate projection makes coordinator health queryable and auditable without asserting that infrastructure is Task-owned.

```text
RuntimeServiceHealth {
  service_id: svc_hermes_coordinator
  service_type: HERMES_COORDINATOR
  instance_identity: opaque per-start UUID
  boot_id: opaque host boot identifier
  pid: integer
  process_start_time: opaque kernel start value
  state: STARTING | READY | DEGRADED | STOPPING | FAILED
  started_at: UTC timestamp
  last_heartbeat: UTC timestamp
  version: deployed coordinator + Hermes version summary
  health_reason: bounded secret-free code
}
```

TC7 adds narrowly scoped operations such as `RegisterRuntimeServiceInstance` and `RecordRuntimeServiceHeartbeat`; capability scope permits the coordinator to report only `svc_hermes_coordinator`. The projection has its own audit events and never allocates a Task Resource Lease.

The coordinator sends an authenticated heartbeat every 30 seconds while `READY`, `DEGRADED`, or `STOPPING`. The Control Plane marks/states stale health evidence after 90 seconds without an accepted heartbeat. Missing infrastructure heartbeat is availability evidence only: it does not terminate Task resources, delete anything, or change Task ownership.

## 21. logging

Coordinator logs are JSON lines to journald, with bounded field lengths and redaction before serialization. The normal schema is:

```text
 timestamp
 service=megabrain-hermes-coordinator
 instance_id
 correlation_id
 task_id
 operation
 decision
 provider_channel
 budget_decision
 result
 duration_ms
 health_state
 reason_code
```

Fields are emitted only where relevant. Logs must never contain capability proofs, bootstrap credentials, OAuth/provider tokens, provider credentials, raw environment values, private keys, raw Task Packets, full prompts, unrestricted tool output, or raw usage-file contents. Logs reference durable IDs/evidence only. The coordinator rate-limits repetitive `DEGRADED` logs and emits state changes, not unbounded retry noise.

## 22. Worker boundary

The coordinator is never the implementation Worker:

```text
Hermes Coordinator
  -> orchestration decision
  -> Worker Manager request through Control Plane
  -> finite Worker
```

It may admit, plan, schedule, pause, request review, and interpret bounded evidence. It may not run arbitrary feature implementation inside the persistent service context, call a coding worker directly outside Worker Manager admission, or use its own service account to bypass a Worker lease. Worker Manager unavailability blocks the requested work and preserves/checkpoints the Task; it does not cause coordinator implementation fallback.

## 23. tool authority

Future one-shot coordinator turns receive a dedicated, deny-by-default tool profile. It exposes only:

- a scoped Control Plane client;
- bounded Task/checkpoint/gate metadata;
- a future Paperclip task interface;
- read-only repository/status evidence within the Task's declared worktree scope; and
- a Worker Manager request interface.

It excludes shell escape, unrestricted filesystem/network access, direct SQLite, direct production mutation, Docker, systemd control, credential access, arbitrary Git mutation, and arbitrary task creation. Independent TC7A1 compatibility inspection found that the installed `hermes --oneshot` implementation internally sets `HERMES_YOLO_MODE=1` and `HERMES_ACCEPT_HOOKS=1`; therefore interactive approval prompts are not a security boundary for coordinator turns. The enforceable boundary is an explicit deny-by-default tool allowlist. TC7A1 pins `platform_toolsets.cli: []`, which the installed Hermes resolves to zero toolsets, until later TC7 slices provide narrowly scoped coordinator-specific tools. The one-shot subprocess also receives a minimal explicit environment rather than an unrestricted copy of the coordinator process environment; `HOME` and `HERMES_HOME` are forced to the private coordinator runtime. The systemd coordinator process mediates Hermes CLI invocation; the one-shot model is never granted service-management authority.

## 24. Paperclip compatibility

The compatibility boundary remains:

```text
Paperclip     = task planning/state integration surface
Control Plane = runtime authority, budget, provider, resource, and checkpoint truth
Hermes        = bounded coordinator/orchestrator
```

Task Packets carry canonical IDs and evidence references rather than session history. Paperclip may later supply requests, planning, or views, but it does not make a coordinator session canonical. A future Control Plane/Paperclip cutover preserves Task IDs, checkpoint IDs, provider observations, logical admissions, API-call telemetry, service-health evidence, and append-only provenance with one writer per canonical record.

## 25. failure matrix

Every case below fails closed: no authority expansion, no direct registry write, no inferred ownership, and no unadmitted model call.

| Failure | Required behavior |
|---|---|
| 1. Coordinator process crash | systemd restarts on failure; recovery uses committed registry/checkpoint/reconciliation only; in-flight turn is indeterminate. |
| 2. Host reboot | require registry READY, new boot identity, read-only reconciliation, fresh provider preflight, then new admission. |
| 3. Control Plane unavailable | coordinator `DEGRADED`; no new model call, Worker request, or runtime mutation; bounded reconnect only. |
| 4. SQLite recovery required | Control Plane closes admission; coordinator remains degraded/idle; no shadow state authority or direct DB repair. |
| 5. Capability invalid/expired | reject request, mark degraded/blocked evidence, re-exchange only via bootstrap; no model call. |
| 6. Provider `AUTH_EXPIRED` | record `AUTH_EXPIRED`; Task `BLOCKED_PROVIDER_AUTH`; no blind retry. |
| 7. Provider `QUOTA_EXHAUSTED` | record state/reset evidence; checkpoint and `PAUSED_PROVIDER_QUOTA`; no one-shot/short retry. |
| 8. Provider `TRANSIENT_FAILURE` | record state; normal admission blocked; retry only with existing bounded retry reservation. |
| 9. Unknown provider state | record `UNKNOWN`; fail closed; no inferred availability. |
| 10. `hermes usage` fails | record sanitized `UNKNOWN` or `TRANSIENT_FAILURE` by deterministic error mapping; no model call. |
| 11. One-shot exits non-zero | parse usage evidence if valid; record bounded failure/checkpoint; no automatic replacement invocation. |
| 12. Usage file missing | record `USAGE_EVIDENCE_MISSING`; preserve admission; checkpoint/block affected Task; no accounting fabrication. |
| 13. Usage file malformed | record `USAGE_EVIDENCE_INVALID`; never parse best-effort; checkpoint/block affected Task. |
| 14. Model call admitted but spawn fails | admission remains consumed; record spawn failure and checkpoint/block; do not retry without a new permitted admission. |
| 15. SIGTERM before model invocation | cancel local dispatch; no spawn; record STOPPING only; exit cleanly. |
| 16. SIGTERM during model invocation | stop new work, bounded drain, preserve available evidence, checkpoint if possible, terminate process group at grace expiry. |
| 17. Task global budget exhausted | `BLOCK_BUDGET`; no coordinator/Worker/reviewer/continuation/retry call. |
| 18. Context hard limit reached | `STOP_AND_CHECKPOINT`; no broad/new turn until compact checkpoint and new admission. |
| 19. Worker Manager unavailable | checkpoint/block requested work; coordinator does not implement the feature itself. |
| 20. Unknown legacy Worker discovered | record read-only unknown-ownership evidence; never adopt, command, terminate, or assign a Task. |

## 26. TC7 implementation plan

TC7 is bounded code/design delivery, split into hermetic implementation and separately human-gated deployment preparation.

### Repository code and hermetic tests

```text
services/hermes_coordinator/
  app/
    coordinator.py          # lifecycle, loop, shutdown, recovery
    control_plane_client.py # bounded UDS protocol client
    provider_observer.py    # hermes usage subprocess/parser
    hermes_oneshot.py       # process-group spawn, usage-file handling
    packet.py               # compact Task Packet validation
    usage.py                # strict usage schema/sanitization
    health.py               # service-health client/state
    logging.py              # JSON redaction/bounds
  tests/

services/control_plane/
  app/
    production_capabilities.py  # reviewed runtime issuer/validator boundary
    service_health.py           # infrastructure projection
    ... minimal dispatch/auth/schema extensions
  tests/

deploy/systemd/
  megabrain-hermes-coordinator.service
  megabrain-control-plane.service.d/  # only if needed for socket group/mode

docs/platform/autonomy/
  deployment runbook and capability bootstrap contract updates
```

TC7 Control Plane extensions are limited to: coordinator-scoped `RecordProviderObservation`; production capability exchange/validation; service-health projection; peer-credential/socket group enforcement; and any necessary secret-free audit schemas. It must not add direct database access, generic secret retrieval, generic process control, Worker implementation, gateway installation, or `hermes serve`.

Hermetic tests must cover: admission-before-spawn; non-`ADMIT` no-spawn; provider mappings; quota no-retry; usage report success/non-zero/missing/malformed; logical admission versus `api_calls`; checkpoint/recovery; SIGTERM before/during one-shot; 30-second heartbeat semantics with fake clock; UDS mode/peer/capability failures; revocation/expiry/rotation fixtures; all failure-matrix cases; systemd unit lint/static assertions; and hardening smoke tests in a disposable non-root environment where available.

### Root/systemd installation: human gate

A human-approved deployment task, separate from hermetic TC7 validation, is required to create users/groups, provision `/opt` artifact, provision encrypted credentials, install/enable units, set UDS ownership, and start services. It must read back exact files, permissions, unit state, UDS accessibility, and service health before claiming success.

### Explicitly not authorized by TC7

No production installation or start, no gateway installation, no `hermes serve` enablement, no public listener, no provider credential mutation, no Worker Manager implementation beyond client contract, and no Paperclip cutover.

## 27. unresolved blockers

### TC6 execution-validation finding

Independent post-task validation showed that the current interactive Hermes CLI did not self-enforce the TC6 prompt budget: the primary session reached 18 provider API calls and exceeded the 120k context hard limit before returning the READY verdict, followed by an automatic background-review turn. No subagent/delegation or runtime mutation occurred, and the document itself remained docs-only and structurally valid.

Therefore prompt-declared limits are not an enforcement boundary. TC7 must make budget/context containment external to the model conversation: admission is authoritative in the Control Plane, the coordinator must use bounded one-shot subprocesses, and the runtime must be able to stop/refuse further execution independently of model compliance. Hermes-reported `api_calls`/usage evidence is post-execution accounting, not permission to exceed the admitted budget. The installed Hermes codebase exposes `agent.max_turns`/iteration-budget machinery, but TC7 must prove its behavior specifically for the chosen one-shot path before treating it as a hard guard; otherwise the coordinator must add an external process/time/turn containment mechanism.

No architectural blocker prevents hermetic TC7 implementation. The following deployment prerequisites remain explicitly human-gated and must be resolved before any real service activation:

1. provision the dedicated Control Plane Unix user, the narrow client group, root-owned deployment path, and an isolated coordinator service home without reusing interactive Hermes state;
2. establish the reviewed production capability primitive, encrypted systemd credential store, bootstrap verifier/signing-key custody, and revocation persistence;
3. prove the exact deployed Hermes build runs one-shot/provider observation with isolated `$HERMES_HOME` under `ProtectHome=tmpfs` and the proposed hardening profile;
4. validate the target host's systemd support for `LoadCredentialEncrypted`, directory modes, and the chosen hardening directives; and
5. approve the Task/Paperclip discovery interface and configured provider-channel allowlist.

If any prerequisite fails at deployment, do not weaken permissions or reuse shared interactive state to proceed. Keep the service uninstalled/unstarted and return to a separately scoped design or remediation task.

## 28. final design verdict

The design is implementation-ready for a bounded TC7: persistence belongs to the coordinator process and Control Plane, every LLM-backed coordinator decision is a fresh admitted one-shot, provider quota pauses preserve coordinator health, and filesystem/UDS/capability boundaries prevent Hermes from gaining registry or host authority.

Final verdict: `AP0_TC6_HERMES_SERVICE_DESIGN_READY`
