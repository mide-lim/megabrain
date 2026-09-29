# AP0-TC3 — Control Plane Implementation Design

Status: implementation-ready specification; no implementation or runtime mutation
Date: 2026-09-29
Predecessor verdict: `AP0_TC2_CONTROL_PLANE_READY`

Canonical predecessors:

- `docs/platform/autonomy/AP0_RUNTIME_BASELINE.md`
- `docs/platform/autonomy/AP0_RUNTIME_OWNERSHIP_CONTRACT.md`
- `docs/platform/autonomy/AP0_CONTROL_PLANE_CONTRACT.md`

Scope boundary: this document defines the AP0 Control Plane Registry MVP only. It does not create a SQLite database, service, socket, process, worktree, preview, Docker resource, system configuration, production record, or runtime resource. It neither authorizes nor describes an autonomous cleanup action.

## 1. Frozen AP0 decisions

1. AP0 uses one dedicated, locally durable SQLite database. It is separate from production PostgreSQL and `~/.hermes/state.db`.
2. A narrow local Control Plane Service is the only writer and the only supported reader of the database. Hermes, Worker Manager, Workers, adapters, and Paperclip import/export tooling use the versioned service protocol; they never open the database directly.
3. AP0 uses a Unix-domain socket (UDS), not loopback HTTP. The socket is local-only, has no TCP listener, supports peer-credential inspection, and is protected by owner-only filesystem permissions.
4. SQLite is a single-host, single-writer AP0 implementation. Every mutation uses a short explicit `BEGIN IMMEDIATE` transaction. This is intentional: correctness of admission, budgets, audit order, and gate consumption takes priority over throughput.
5. Current state is stored in the canonical Task, Resource Lease, Heartbeat, Gate, and Checkpoint families. Immutable history is retained as append-only Audit Events. A state change and all corresponding events commit atomically.
6. Audit hash chaining is retained as an integrity-detection mechanism. It detects accidental or unsophisticated alteration, deletion, or reordering of retained events when validation is run. It is not tamper-proof: a sufficiently privileged operator who rewrites the event store and recomputes the chain can evade it.
7. Resource creation is always two-phase: `ALLOCATED -> create externally -> bind exact identity -> ACTIVE`. A failed creation terminalizes the allocated lease and preserves the evidence; the lease is never erased or reused.
8. Missing liveness is non-destructive. A missed heartbeat blocks dependent admission and creates evidence; it never proves a process is dead and never grants cleanup authority.
9. No AP0 API exposes arbitrary SQL, arbitrary shell execution, database files, raw Docker inspect output, secret retrieval, environment dumps, or privileged host configuration output.
10. Database deletion, retention pruning, and runtime cleanup are not AP0-TC4 capabilities. Retention rules below are minimum preservation requirements and do not authorize deletion.

## 2. Storage, durability, and SQLite operating contract

The future registry directory is selected by an AP0 configuration contract, not by the Hermes internal-state path. It must be a dedicated owner-only directory, for example a service-private control-plane state directory, with mode `0700`. The database, WAL, SHM, migration lock, and backup staging files must be created with mode `0600`. The service must refuse to start if the directory or database ownership/mode is broader than the configured owner policy.

The future service opens each SQLite connection with the following required configuration and verifies successful application at startup:

```sql
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA busy_timeout = 2500;
PRAGMA synchronous = FULL;
PRAGMA trusted_schema = OFF;
```

`journal_mode` must read back as `wal`; otherwise the service enters `REGISTRY_UNAVAILABLE` and admission remains disabled. A 2.5-second busy timeout is bounded enough to avoid indefinite worker waits while allowing a short competing transaction to complete. Callers may retry only according to the retry policy in section 14.

The service uses UTC RFC 3339 timestamps with millisecond precision and a trailing `Z`, for example `2026-09-29T12:34:56.789Z`. The database stores timestamps as text so export/import is portable and unambiguous. The service validates the full timestamp grammar; SQL checks only reject obvious empty/non-UTC values.

Structured fields are UTF-8 JSON text encoded with RFC 8785 JSON Canonicalization Scheme (JCS) before persistence. The service rejects duplicate object keys, non-finite numbers, unsupported JSON types, and noncanonical JSON. JSON is used only for bounded structured contracts whose relational decomposition would not improve AP0 integrity. No Python pickle, repr, ORM blob, terminal transcript, raw inspect document, or Hermes-internal serialization is permitted.

## 3. Physical SQLite schema

### 3.1 Schema conventions

The SQL below is the AP0-TC4 target initial schema, not a request to execute it during TC3.

- `schema_version` is a record-contract semantic version such as `1.0.0`. Writers emit only the currently supported version.
- `revision` is an optimistic-concurrency version. Every permitted mutation increments it by exactly one.
- JSON columns are canonical JSON text validated by both SQL `json_valid()` and service validation.
- Identifier shape checks validate prefix, length, and lowercase. Full UUIDv7 validation occurs in the service because SQLite has no portable UUIDv7 validator.
- The listed triggers are defense in depth for the service path. Owner-level filesystem/database access is outside the normal API trust boundary and is not represented as tamper-proof protection.

```sql
-- Infrastructure tables permitted by the AP0 contract.
CREATE TABLE schema_migrations (
    migration_id       TEXT PRIMARY KEY,
    checksum_sha256    TEXT NOT NULL UNIQUE
                       CHECK(length(checksum_sha256) = 64
                             AND checksum_sha256 = lower(checksum_sha256)),
    applied_at         TEXT NOT NULL CHECK(substr(applied_at, -1) = 'Z'),
    service_version    TEXT NOT NULL,
    description        TEXT NOT NULL
) STRICT;

CREATE TABLE registry_metadata (
    metadata_key       TEXT PRIMARY KEY,
    metadata_value     TEXT NOT NULL,
    updated_at         TEXT NOT NULL CHECK(substr(updated_at, -1) = 'Z')
) STRICT;

-- Required initial keys: admission_state, schema_epoch, event_chain_algorithm,
-- event_chain_head_sequence, event_chain_head_hash, migration_failure_code.

CREATE TABLE tasks (
    task_id                 TEXT PRIMARY KEY
                            CHECK(length(task_id) = 41
                                  AND substr(task_id, 1, 5) = 'task_'
                                  AND task_id = lower(task_id)),
    schema_version          TEXT NOT NULL,
    created_at              TEXT NOT NULL CHECK(substr(created_at, -1) = 'Z'),
    created_by              TEXT NOT NULL CHECK(json_valid(created_by)
                                                 AND json_type(created_by) = 'object'),
    requested_by            TEXT NOT NULL CHECK(json_valid(requested_by)
                                                 AND json_type(requested_by) = 'object'),
    state                   TEXT NOT NULL CHECK(state IN (
                              'CREATED','READY','RUNNING','PAUSED','BLOCKED',
                              'VALIDATING','REVIEW','TERMINAL')),
    risk_class              TEXT NOT NULL CHECK(risk_class IN ('GREEN','YELLOW','RED','UNKNOWN')),
    task_contract_ref       TEXT,
    allowed_operations      TEXT NOT NULL CHECK(json_valid(allowed_operations)
                                                 AND json_type(allowed_operations) = 'array'),
    resource_budget         TEXT NOT NULL CHECK(json_valid(resource_budget)
                                                 AND json_type(resource_budget) = 'object'),
    prerequisite_status     TEXT NOT NULL CHECK(json_valid(prerequisite_status)
                                                 AND json_type(prerequisite_status) = 'object'),
    pause_reason            TEXT CHECK(pause_reason IS NULL OR
                                       (json_valid(pause_reason)
                                        AND json_type(pause_reason) = 'object')),
    terminal_result         TEXT CHECK(terminal_result IS NULL OR
                                       (json_valid(terminal_result)
                                        AND json_type(terminal_result) = 'object')),
    current_checkpoint_id   TEXT CHECK(current_checkpoint_id IS NULL OR
                                       (length(current_checkpoint_id) = 40
                                        AND substr(current_checkpoint_id, 1, 4) = 'chk_'
                                        AND current_checkpoint_id = lower(current_checkpoint_id))),
    revision                INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
    last_event_sequence     INTEGER NOT NULL DEFAULT 0 CHECK(last_event_sequence >= 0),
    CHECK((state = 'PAUSED' AND pause_reason IS NOT NULL) OR
          (state <> 'PAUSED')),
    CHECK((state = 'TERMINAL' AND terminal_result IS NOT NULL) OR
          (state <> 'TERMINAL')),
    CHECK(NOT (pause_reason IS NOT NULL AND state <> 'PAUSED')),
    CHECK(NOT (terminal_result IS NOT NULL AND state <> 'TERMINAL'))
) STRICT;

CREATE TABLE resource_leases (
    resource_id             TEXT PRIMARY KEY
                            CHECK(length(resource_id) = 41
                                  AND substr(resource_id, 1, 5) = 'rsrc_'
                                  AND resource_id = lower(resource_id)),
    task_id                 TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
    schema_version          TEXT NOT NULL,
    resource_type           TEXT NOT NULL CHECK(resource_type IN (
                              'WORKER','PROCESS','PREVIEW','WORKTREE','TEMP_DIR',
                              'TEST_ENV','ARTIFACT','DELEGATED_RUN')),
    created_at              TEXT NOT NULL CHECK(substr(created_at, -1) = 'Z'),
    created_by              TEXT NOT NULL CHECK(json_valid(created_by)
                                                 AND json_type(created_by) = 'object'),
    state                   TEXT NOT NULL CHECK(state IN (
                              'ALLOCATED','ACTIVE','IDLE','TERMINAL',
                              'HEARTBEAT_MISSED','STALE_CANDIDATE')),
    requested_operation     TEXT NOT NULL CHECK(json_valid(requested_operation)
                                                 AND json_type(requested_operation) = 'object'),
    budget_reservation      TEXT NOT NULL CHECK(json_valid(budget_reservation)
                                                 AND json_type(budget_reservation) = 'object'),
    expected_identity       TEXT NOT NULL CHECK(json_valid(expected_identity)
                                                 AND json_type(expected_identity) = 'object'),
    bound_identity          TEXT CHECK(bound_identity IS NULL OR
                                       (json_valid(bound_identity)
                                        AND json_type(bound_identity) = 'object')),
    heartbeat_required      INTEGER NOT NULL CHECK(heartbeat_required IN (0, 1)),
    last_heartbeat          TEXT CHECK(last_heartbeat IS NULL OR substr(last_heartbeat, -1) = 'Z'),
    ttl_seconds             INTEGER CHECK(ttl_seconds IS NULL OR ttl_seconds > 0),
    cleanup_policy          TEXT NOT NULL CHECK(json_valid(cleanup_policy)
                                                 AND json_type(cleanup_policy) = 'object'),
    cleanup_authority       TEXT NOT NULL CHECK(json_valid(cleanup_authority)
                                                 AND json_type(cleanup_authority) = 'object'),
    metadata                TEXT NOT NULL CHECK(json_valid(metadata)
                                                 AND json_type(metadata) = 'object'),
    terminal_reason         TEXT,
    revision                INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
    last_event_sequence     INTEGER NOT NULL DEFAULT 0 CHECK(last_event_sequence >= 0),
    CHECK((state = 'ACTIVE' AND bound_identity IS NOT NULL) OR state <> 'ACTIVE'),
    CHECK((heartbeat_required = 1) OR last_heartbeat IS NULL),
    CHECK((state = 'TERMINAL' AND terminal_reason IS NOT NULL) OR state <> 'TERMINAL')
) STRICT;

CREATE TABLE audit_events (
    event_id                TEXT PRIMARY KEY
                            CHECK(length(event_id) = 40
                                  AND substr(event_id, 1, 4) = 'evt_'
                                  AND event_id = lower(event_id)),
    sequence                INTEGER NOT NULL UNIQUE CHECK(sequence > 0),
    schema_version          TEXT NOT NULL,
    event_type              TEXT NOT NULL,
    occurred_at             TEXT NOT NULL CHECK(substr(occurred_at, -1) = 'Z'),
    task_id                 TEXT REFERENCES tasks(task_id) ON DELETE RESTRICT,
    resource_id             TEXT REFERENCES resource_leases(resource_id) ON DELETE RESTRICT,
    actor                   TEXT NOT NULL CHECK(json_valid(actor)
                                                 AND json_type(actor) = 'object'),
    correlation_id          TEXT NOT NULL
                            CHECK(length(correlation_id) = 41
                                  AND substr(correlation_id, 1, 5) = 'corr_'
                                  AND correlation_id = lower(correlation_id)),
    payload                 TEXT NOT NULL CHECK(json_valid(payload)
                                                 AND json_type(payload) = 'object'),
    prior_event_hash        TEXT CHECK(prior_event_hash IS NULL OR
                                       (length(prior_event_hash) = 64
                                        AND prior_event_hash = lower(prior_event_hash))),
    event_hash              TEXT NOT NULL CHECK(length(event_hash) = 64
                                                 AND event_hash = lower(event_hash)),
    CHECK((sequence = 1 AND prior_event_hash IS NULL) OR
          (sequence > 1 AND prior_event_hash IS NOT NULL))
) STRICT;

-- One row is the current liveness projection for one Task or Resource scope.
-- Full heartbeat history is retained as HEARTBEAT_RECORDED audit events.
CREATE TABLE heartbeats (
    heartbeat_scope         TEXT PRIMARY KEY,
    schema_version          TEXT NOT NULL,
    task_id                 TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
    resource_id             TEXT REFERENCES resource_leases(resource_id) ON DELETE RESTRICT,
    producer                TEXT NOT NULL CHECK(json_valid(producer)
                                                 AND json_type(producer) = 'object'),
    sequence                INTEGER NOT NULL CHECK(sequence >= 0),
    producer_monotonic_ns   INTEGER CHECK(producer_monotonic_ns IS NULL OR producer_monotonic_ns >= 0),
    observed_at             TEXT NOT NULL CHECK(substr(observed_at, -1) = 'Z'),
    received_at             TEXT NOT NULL CHECK(substr(received_at, -1) = 'Z'),
    status                  TEXT NOT NULL CHECK(status IN (
                              'EXPECTED','PAUSED','COMPLETING','FAILED','UNKNOWN')),
    evidence_ref            TEXT,
    last_event_id           TEXT NOT NULL UNIQUE REFERENCES audit_events(event_id) ON DELETE RESTRICT,
    CHECK((resource_id IS NULL AND heartbeat_scope = 'task:' || task_id) OR
          (resource_id IS NOT NULL AND heartbeat_scope = 'resource:' || resource_id))
) STRICT;

CREATE TABLE gates (
    gate_id                 TEXT PRIMARY KEY
                            CHECK(length(gate_id) = 41
                                  AND substr(gate_id, 1, 5) = 'gate_'
                                  AND gate_id = lower(gate_id)),
    schema_version          TEXT NOT NULL,
    task_id                 TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
    resource_id             TEXT REFERENCES resource_leases(resource_id) ON DELETE RESTRICT,
    requested_operation     TEXT NOT NULL CHECK(json_valid(requested_operation)
                                                 AND json_type(requested_operation) = 'object'),
    risk_class              TEXT NOT NULL CHECK(risk_class IN ('GREEN','YELLOW','RED','UNKNOWN')),
    requested_at            TEXT NOT NULL CHECK(substr(requested_at, -1) = 'Z'),
    requested_by            TEXT NOT NULL CHECK(json_valid(requested_by)
                                                 AND json_type(requested_by) = 'object'),
    required_authority      TEXT NOT NULL CHECK(json_valid(required_authority)
                                                 AND json_type(required_authority) = 'object'),
    status                  TEXT NOT NULL CHECK(status IN (
                              'PENDING','APPROVED','DENIED','EXPIRED','CONSUMED')),
    approved_by             TEXT CHECK(approved_by IS NULL OR
                                       (json_valid(approved_by)
                                        AND json_type(approved_by) = 'object')),
    approved_at             TEXT CHECK(approved_at IS NULL OR substr(approved_at, -1) = 'Z'),
    expires_at              TEXT CHECK(expires_at IS NULL OR substr(expires_at, -1) = 'Z'),
    authorization_reference TEXT,
    consumed_at             TEXT CHECK(consumed_at IS NULL OR substr(consumed_at, -1) = 'Z'),
    revision                INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
    last_event_sequence     INTEGER NOT NULL DEFAULT 0 CHECK(last_event_sequence >= 0),
    CHECK((status IN ('APPROVED','CONSUMED') AND approved_by IS NOT NULL
           AND approved_at IS NOT NULL AND expires_at IS NOT NULL
           AND authorization_reference IS NOT NULL)
          OR status NOT IN ('APPROVED','CONSUMED')),
    CHECK((status = 'CONSUMED' AND consumed_at IS NOT NULL) OR status <> 'CONSUMED'),
    CHECK((status <> 'CONSUMED' AND consumed_at IS NULL) OR status = 'CONSUMED')
) STRICT;

CREATE TABLE checkpoints (
    checkpoint_id           TEXT PRIMARY KEY
                            CHECK(length(checkpoint_id) = 40
                                  AND substr(checkpoint_id, 1, 4) = 'chk_'
                                  AND checkpoint_id = lower(checkpoint_id)),
    task_id                 TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
    schema_version          TEXT NOT NULL,
    created_at              TEXT NOT NULL CHECK(substr(created_at, -1) = 'Z'),
    created_by              TEXT NOT NULL CHECK(json_valid(created_by)
                                                 AND json_type(created_by) = 'object'),
    task_state              TEXT NOT NULL CHECK(task_state IN (
                              'CREATED','READY','RUNNING','PAUSED','BLOCKED',
                              'VALIDATING','REVIEW','TERMINAL')),
    branch                  TEXT,
    worktree                TEXT,
    head_sha                TEXT,
    active_resource_ids     TEXT NOT NULL CHECK(json_valid(active_resource_ids)
                                                 AND json_type(active_resource_ids) = 'array'),
    pending_validation      TEXT NOT NULL CHECK(json_valid(pending_validation)
                                                 AND json_type(pending_validation) = 'array'),
    next_permitted_action   TEXT CHECK(next_permitted_action IS NULL OR
                                       (json_valid(next_permitted_action)
                                        AND json_type(next_permitted_action) = 'object')),
    blocking_reason         TEXT CHECK(blocking_reason IS NULL OR
                                       (json_valid(blocking_reason)
                                        AND json_type(blocking_reason) = 'object')),
    provider_state          TEXT CHECK(provider_state IS NULL OR
                                       (json_valid(provider_state)
                                        AND json_type(provider_state) = 'object')),
    evidence_refs           TEXT NOT NULL CHECK(json_valid(evidence_refs)
                                                 AND json_type(evidence_refs) = 'array')
) STRICT;

CREATE TABLE idempotency_requests (
    caller_id               TEXT NOT NULL,
    idempotency_key         TEXT NOT NULL,
    operation               TEXT NOT NULL,
    request_fingerprint     TEXT NOT NULL CHECK(length(request_fingerprint) = 64
                                                 AND request_fingerprint = lower(request_fingerprint)),
    created_at              TEXT NOT NULL CHECK(substr(created_at, -1) = 'Z'),
    finalized_at            TEXT CHECK(finalized_at IS NULL OR substr(finalized_at, -1) = 'Z'),
    status                  TEXT NOT NULL CHECK(status IN ('IN_PROGRESS','SUCCEEDED','FAILED')),
    result_reference        TEXT,
    response_code           TEXT,
    response_body           TEXT CHECK(response_body IS NULL OR json_valid(response_body)),
    PRIMARY KEY (caller_id, idempotency_key)
) STRICT;

-- Query and exclusivity indexes.
CREATE INDEX tasks_state_created_idx
    ON tasks(state, created_at);
CREATE INDEX tasks_requester_created_idx
    ON tasks(requested_by, created_at);
CREATE INDEX resource_task_state_idx
    ON resource_leases(task_id, state, resource_type);
CREATE INDEX resource_active_type_idx
    ON resource_leases(resource_type, task_id)
    WHERE state IN ('ALLOCATED','ACTIVE','IDLE','HEARTBEAT_MISSED','STALE_CANDIDATE');
CREATE UNIQUE INDEX active_bound_identity_idx
    ON resource_leases(resource_type, bound_identity)
    WHERE bound_identity IS NOT NULL
      AND state IN ('ACTIVE','IDLE','HEARTBEAT_MISSED','STALE_CANDIDATE');
CREATE UNIQUE INDEX active_preview_endpoint_idx
    ON resource_leases(
        json_extract(metadata, '$.bind_address'),
        json_extract(metadata, '$.port'))
    WHERE resource_type = 'PREVIEW'
      AND state IN ('ALLOCATED','ACTIVE','IDLE','HEARTBEAT_MISSED','STALE_CANDIDATE');
CREATE UNIQUE INDEX active_worktree_path_idx
    ON resource_leases(json_extract(metadata, '$.path'))
    WHERE resource_type = 'WORKTREE'
      AND state IN ('ALLOCATED','ACTIVE','IDLE','HEARTBEAT_MISSED','STALE_CANDIDATE');
CREATE INDEX audit_task_sequence_idx ON audit_events(task_id, sequence);
CREATE INDEX audit_resource_sequence_idx ON audit_events(resource_id, sequence);
CREATE INDEX audit_correlation_idx ON audit_events(correlation_id, sequence);
CREATE INDEX heartbeat_due_idx ON heartbeats(received_at, status);
CREATE INDEX gates_pending_expiry_idx ON gates(status, expires_at, requested_at)
    WHERE status IN ('PENDING','APPROVED');
CREATE INDEX checkpoints_task_created_idx ON checkpoints(task_id, created_at DESC);
CREATE INDEX idempotency_created_idx ON idempotency_requests(created_at);
```

### 3.2 Required transition and immutability triggers

AP0-TC4 must install the following trigger behavior in `0001_initial_schema.sql`. The service remains responsible for authorization and full semantic validation, but the database guards against accidental bypass through the normal service connection.

```sql
CREATE TRIGGER audit_events_no_update
BEFORE UPDATE ON audit_events
BEGIN
  SELECT RAISE(ABORT, 'AUDIT_APPEND_ONLY');
END;

CREATE TRIGGER audit_events_no_delete
BEFORE DELETE ON audit_events
BEGIN
  SELECT RAISE(ABORT, 'AUDIT_APPEND_ONLY');
END;

CREATE TRIGGER checkpoints_no_update
BEFORE UPDATE ON checkpoints
BEGIN
  SELECT RAISE(ABORT, 'CHECKPOINT_IMMUTABLE');
END;

CREATE TRIGGER checkpoints_no_delete
BEFORE DELETE ON checkpoints
BEGIN
  SELECT RAISE(ABORT, 'CHECKPOINT_IMMUTABLE');
END;

CREATE TRIGGER tasks_insert_guard
BEFORE INSERT ON tasks
WHEN NEW.state <> 'CREATED' OR NEW.revision <> 0 OR NEW.last_event_sequence <> 0
BEGIN
  SELECT RAISE(ABORT, 'TASK_MUST_START_CREATED');
END;

CREATE TRIGGER tasks_no_delete
BEFORE DELETE ON tasks
BEGIN
  SELECT RAISE(ABORT, 'TASK_RETAINED');
END;

CREATE TRIGGER resource_leases_insert_guard
BEFORE INSERT ON resource_leases
WHEN NEW.state <> 'ALLOCATED' OR NEW.bound_identity IS NOT NULL
  OR NEW.revision <> 0 OR NEW.last_event_sequence <> 0
BEGIN
  SELECT RAISE(ABORT, 'RESOURCE_MUST_START_ALLOCATED');
END;

CREATE TRIGGER resource_leases_no_delete
BEFORE DELETE ON resource_leases
BEGIN
  SELECT RAISE(ABORT, 'RESOURCE_LEASE_RETAINED');
END;

CREATE TRIGGER gates_insert_guard
BEFORE INSERT ON gates
WHEN NEW.status <> 'PENDING' OR NEW.approved_by IS NOT NULL
  OR NEW.approved_at IS NOT NULL OR NEW.expires_at IS NOT NULL
  OR NEW.authorization_reference IS NOT NULL OR NEW.consumed_at IS NOT NULL
  OR NEW.revision <> 0 OR NEW.last_event_sequence <> 0
BEGIN
  SELECT RAISE(ABORT, 'GATE_MUST_START_PENDING');
END;

CREATE TRIGGER gates_no_delete
BEFORE DELETE ON gates
BEGIN
  SELECT RAISE(ABORT, 'GATE_RETAINED');
END;

CREATE TRIGGER heartbeats_no_delete
BEFORE DELETE ON heartbeats
BEGIN
  SELECT RAISE(ABORT, 'HEARTBEAT_PROJECTION_RETAINED');
END;

CREATE TRIGGER tasks_update_guard
BEFORE UPDATE ON tasks
BEGIN
  SELECT CASE WHEN NEW.task_id <> OLD.task_id
                OR NEW.schema_version <> OLD.schema_version
                OR NEW.created_at <> OLD.created_at
                OR NEW.created_by <> OLD.created_by
                OR NEW.requested_by <> OLD.requested_by
                OR NEW.risk_class <> OLD.risk_class
                OR NEW.task_contract_ref IS NOT OLD.task_contract_ref
                OR NEW.allowed_operations <> OLD.allowed_operations
                OR NEW.resource_budget <> OLD.resource_budget
              THEN RAISE(ABORT, 'TASK_IMMUTABLE_FIELD') END;
  SELECT CASE WHEN OLD.state = 'TERMINAL'
              THEN RAISE(ABORT, 'TASK_TERMINAL_IMMUTABLE') END;
  SELECT CASE WHEN NEW.revision <> OLD.revision + 1
              THEN RAISE(ABORT, 'TASK_REVISION_CONFLICT') END;
  SELECT CASE WHEN NEW.state <> OLD.state AND NOT (
       (OLD.state = 'CREATED'    AND NEW.state IN ('READY','BLOCKED','TERMINAL')) OR
       (OLD.state = 'READY'      AND NEW.state IN ('RUNNING','PAUSED','BLOCKED','TERMINAL')) OR
       (OLD.state = 'RUNNING'    AND NEW.state IN ('VALIDATING','REVIEW','PAUSED','BLOCKED','TERMINAL')) OR
       (OLD.state = 'VALIDATING' AND NEW.state IN ('REVIEW','PAUSED','BLOCKED','TERMINAL')) OR
       (OLD.state = 'REVIEW'     AND NEW.state IN ('PAUSED','BLOCKED','TERMINAL')) OR
       (OLD.state = 'PAUSED'     AND NEW.state IN ('READY','RUNNING','BLOCKED','TERMINAL')) OR
       (OLD.state = 'BLOCKED'    AND NEW.state IN ('READY','TERMINAL'))
  ) THEN RAISE(ABORT, 'INVALID_TASK_STATE_TRANSITION') END;
  SELECT CASE WHEN NEW.current_checkpoint_id IS NOT NULL AND NOT EXISTS (
       SELECT 1 FROM checkpoints c
       WHERE c.checkpoint_id = NEW.current_checkpoint_id AND c.task_id = NEW.task_id
  ) THEN RAISE(ABORT, 'TASK_CHECKPOINT_SCOPE_MISMATCH') END;
END;

CREATE TRIGGER resource_leases_update_guard
BEFORE UPDATE ON resource_leases
BEGIN
  SELECT CASE WHEN NEW.resource_id <> OLD.resource_id
                OR NEW.task_id <> OLD.task_id
                OR NEW.schema_version <> OLD.schema_version
                OR NEW.resource_type <> OLD.resource_type
                OR NEW.created_at <> OLD.created_at
                OR NEW.created_by <> OLD.created_by
                OR NEW.requested_operation <> OLD.requested_operation
                OR NEW.budget_reservation <> OLD.budget_reservation
                OR NEW.expected_identity <> OLD.expected_identity
                OR NEW.cleanup_policy <> OLD.cleanup_policy
                OR NEW.cleanup_authority <> OLD.cleanup_authority
                OR NEW.metadata <> OLD.metadata
              THEN RAISE(ABORT, 'RESOURCE_IMMUTABLE_FIELD') END;
  SELECT CASE WHEN OLD.state = 'TERMINAL'
              THEN RAISE(ABORT, 'RESOURCE_TERMINAL_IMMUTABLE') END;
  SELECT CASE WHEN NEW.revision <> OLD.revision + 1
              THEN RAISE(ABORT, 'RESOURCE_REVISION_CONFLICT') END;
  SELECT CASE WHEN OLD.bound_identity IS NOT NULL
                    AND NEW.bound_identity IS NOT OLD.bound_identity
              THEN RAISE(ABORT, 'RESOURCE_IDENTITY_IMMUTABLE') END;
  SELECT CASE WHEN NEW.state <> OLD.state AND NOT (
       (OLD.state = 'ALLOCATED'         AND NEW.state IN ('ACTIVE','TERMINAL','STALE_CANDIDATE')) OR
       (OLD.state = 'ACTIVE'            AND NEW.state IN ('IDLE','TERMINAL','HEARTBEAT_MISSED','STALE_CANDIDATE')) OR
       (OLD.state = 'IDLE'              AND NEW.state IN ('ACTIVE','TERMINAL','HEARTBEAT_MISSED','STALE_CANDIDATE')) OR
       (OLD.state = 'HEARTBEAT_MISSED'  AND NEW.state IN ('ACTIVE','TERMINAL','STALE_CANDIDATE')) OR
       (OLD.state = 'STALE_CANDIDATE'   AND NEW.state IN ('ACTIVE','TERMINAL'))
  ) THEN RAISE(ABORT, 'INVALID_RESOURCE_STATE_TRANSITION') END;
  SELECT CASE WHEN NEW.state = 'ACTIVE' AND NEW.bound_identity IS NULL
              THEN RAISE(ABORT, 'RESOURCE_ACTIVE_REQUIRES_IDENTITY') END;
END;

CREATE TRIGGER gates_update_guard
BEFORE UPDATE ON gates
BEGIN
  SELECT CASE WHEN NEW.gate_id <> OLD.gate_id
                OR NEW.schema_version <> OLD.schema_version
                OR NEW.task_id <> OLD.task_id
                OR NEW.resource_id IS NOT OLD.resource_id
                OR NEW.requested_operation <> OLD.requested_operation
                OR NEW.risk_class <> OLD.risk_class
                OR NEW.requested_at <> OLD.requested_at
                OR NEW.requested_by <> OLD.requested_by
                OR NEW.required_authority <> OLD.required_authority
              THEN RAISE(ABORT, 'GATE_IMMUTABLE_FIELD') END;
  SELECT CASE WHEN OLD.status IN ('DENIED','EXPIRED','CONSUMED')
              THEN RAISE(ABORT, 'GATE_TERMINAL_IMMUTABLE') END;
  SELECT CASE WHEN NEW.revision <> OLD.revision + 1
              THEN RAISE(ABORT, 'GATE_REVISION_CONFLICT') END;
  SELECT CASE WHEN NEW.status <> OLD.status AND NOT (
       (OLD.status = 'PENDING'  AND NEW.status IN ('APPROVED','DENIED','EXPIRED')) OR
       (OLD.status = 'APPROVED' AND NEW.status IN ('CONSUMED','EXPIRED'))
  ) THEN RAISE(ABORT, 'INVALID_GATE_STATE_TRANSITION') END;
  SELECT CASE WHEN OLD.approved_by IS NOT NULL AND (
                    NEW.approved_by IS NOT OLD.approved_by
                 OR NEW.approved_at IS NOT OLD.approved_at
                 OR NEW.expires_at IS NOT OLD.expires_at
                 OR NEW.authorization_reference IS NOT OLD.authorization_reference)
              THEN RAISE(ABORT, 'GATE_APPROVAL_IMMUTABLE') END;
END;
```

These SQL guards make the following immutability rules concrete:

1. `audit_events` and `checkpoints` are append-only/immutable.
2. `tasks` reject updates to task identity, creation/provenance, risk, contract reference, allowed operations, and budget. AP0 has no in-place authority expansion. A material scope/budget/contract change requires a successor Task or a future explicitly designed amendment model.
3. A permitted Task update increments `revision` by exactly one and only follows the documented state graph. The table-level checks additionally require pause reason/terminal result consistency.
4. `resource_leases` reject updates to ownership, requested scope/reservation, expected identity, cleanup policy/authority, and metadata. `bound_identity` may move only from null to one canonical identity. Preview endpoint/worktree path and other metadata used by exclusive indexes are therefore immutable after allocation.
5. `gates` reject updates to scope/authority fields, permit only the documented lifecycle, freeze approval data once present, and make `CONSUMED` terminal.

The service, not a trigger, performs full semantic validation: contract fingerprint validity, JSON schemas, actor roles, gate scope equality, budget arithmetic, policy version compatibility, and secret-free payload rules.

### 3.3 Family semantics and relational integrity

Task fields have the following physical treatment:

| Contract field | Physical representation | Mutability |
|---|---|---|
| `task_id`, `schema_version`, `created_at`, `created_by`, `requested_by` | typed text columns | immutable |
| `state`, `prerequisite_status`, `pause_reason`, `terminal_result`, `current_checkpoint_id`, `revision` | text/JSON/current-state columns | controlled, revisioned |
| `risk_class`, `task_contract_ref`, `allowed_operations`, `resource_budget` | text/JSON columns | immutable after creation |

`allowed_operations` is a JCS array of objects with at least `operation`, `target_scope`, `gate_requirement`, and `policy_version`. `resource_budget` is a JCS object with nonnegative limits for workers, processes, previews, worktrees, temporary bytes, artifact bytes, and runtime seconds. The service rejects omitted applicable dimensions and rejects `UNKNOWN` for a resource that requires that budget dimension.

A Resource Lease has one immutable Task foreign key. Its `expected_identity` describes the exact bounded result anticipated before creation; `bound_identity` records the immutable identity read back after creation. `active_bound_identity_idx` prevents a bound live identity from belonging to more than one active lease of the same type. The service also validates type-specific identity fields, such as `(pid,start_time,boot_id)` for a process and `(bind_address,port,backing process identity)` for a preview.

A resource creation failure transitions `ALLOCATED -> TERMINAL` with `terminal_reason = RESOURCE_CREATION_FAILED` or a more precise non-secret reason. Its reserved budget is released in the same transaction. The lease, request, expected identity, and audit trail remain retained.

### 3.4 Audit-event chain

Each event is assigned the next global `sequence` inside an active `BEGIN IMMEDIATE` transaction. The service reads the current head from `registry_metadata`, constructs the canonical envelope, computes the event hash, inserts the event, applies the state projection, and updates the head metadata before commit.

The canonical hash input is JCS-encoded UTF-8 JSON with exactly these keys, including explicit JSON `null` where applicable:

```text
{
  "actor": <canonical identity object>,
  "correlation_id": "corr_...",
  "event_id": "evt_...",
  "event_type": "...",
  "occurred_at": "...Z",
  "payload": <canonical payload object>,
  "prior_event_hash": null | "<64 lowercase hex>",
  "resource_id": null | "rsrc_...",
  "schema_version": "1.0.0",
  "sequence": <integer>,
  "task_id": null | "task_..."
}
```

`event_hash = SHA-256(canonical_envelope_utf8)` encoded as 64 lowercase hexadecimal characters. The genesis event has sequence `1`, `prior_event_hash = NULL`, and no implied predecessor. The head metadata is initialized only by the first migration.

Recovery validation reads audit events in sequence order, requires the first event to be a valid genesis event, verifies contiguous sequences, recomputes every hash, compares each event's predecessor to the immediately preceding hash, and compares the final sequence/hash with `registry_metadata`. Any mismatch disables admission, reports `AUDIT_WRITE_FAILED` or `REGISTRY_UNAVAILABLE` as applicable, and requires the recovery procedure; it is never silently repaired during normal startup.

### 3.5 Heartbeats and retention

AP0 selects option B: append-only heartbeat events plus a current-state projection.

- Every accepted heartbeat appends a `HEARTBEAT_RECORDED` Audit Event containing full accepted observation data.
- In the same transaction, `heartbeats` upserts the current stream/scope row and `resource_leases.last_heartbeat` when the scope is a resource. This supports fast liveness reads without discarding history.
- A heartbeat scope is exactly `task:<task_id>` for a Task heartbeat or `resource:<resource_id>` for a Resource heartbeat. A Resource row must have the same Task ID as its lease.
- The service accepts a strictly increasing producer sequence for each scoped producer capability. A repeated equal sequence is accepted only as an idempotent retry with the same canonical request fingerprint; lower/out-of-order sequences return `INVALID_REQUEST` and do not refresh liveness.
- Current heartbeat projection rows are retained while their Task/Lease is retained. Audit heartbeat history has the same minimum retention as Audit Events: at least 365 days after terminalization and no automated deletion in AP0-TC4. Future pruning requires separately authorized retention work and must preserve export/audit requirements.

## 4. Identifier generation

Identifiers are opaque strings with the frozen prefixes:

```text
task_<uuidv7>
rsrc_<uuidv7>
evt_<uuidv7>
gate_<uuidv7>
chk_<uuidv7>
corr_<uuidv7>
```

The UUID component is lowercase canonical 8-4-4-4-12 text. It is neither an authorization token nor a semantic encoding of owner, process, branch, port, path, timestamp, risk, or resource type beyond the family prefix.

AP0-TC4 must first use a standards-conformant UUIDv7 implementation provided by the selected runtime or a reviewed dependency. If the runtime lacks native UUIDv7, use a small local generator with this exact fallback behavior:

1. Obtain the 48-bit Unix epoch millisecond portion from the service clock.
2. Obtain the remaining UUIDv7 random portions from the operating system CSPRNG (`secrets`/`os.urandom` equivalent), never from a PRNG seed, PID, counter, MAC address, hostname, or timestamp-only source.
3. Set RFC 9562 UUID version/variant bits, format in lowercase canonical UUID text, and prefix it by family.
4. On a primary-key collision, retry generation within the allocation transaction up to three times. If all attempts collide, abort with `INTERNAL_ERROR` and append no partial logical mutation.

The timestamp contribution gives ordering locality only. It confers no authority and must not be used as proof of creation time; canonical timestamps remain the persisted `created_at`/event time fields.

## 5. Migration model

### 5.1 Numbering and checksums

Migration files use monotonic zero-padded IDs and an immutable checksum, for example:

```text
0001_initial_schema.sql
0002_add_<bounded_change>.sql
```

The source checksum is SHA-256 of the exact committed migration file bytes. `schema_migrations` records ID, checksum, service version, application time, and a safe description. A startup mismatch between a migration file and its recorded checksum is an integrity failure: the service disables admission and returns `REGISTRY_UNAVAILABLE`; it must not reinterpret or rerun the changed file.

### 5.2 Application, empty-registry bootstrap, and failure behavior

The service determines whether a registry exists before it evaluates persisted admission metadata. Until that determination and all required validation complete, admission is closed in service memory.

For an empty registry (no AP0 schema exists), bootstrap is explicit and does not assume that `registry_metadata` already exists:

1. Hold admission closed in service memory and acquire the local migration lock.
2. Validate the ordered migration set and the exact checksum of `0001_initial_schema.sql`, then open one bounded `BEGIN EXCLUSIVE` bootstrap transaction.
3. Execute `0001_initial_schema.sql`; create the `schema_migrations` record and all required `registry_metadata` rows, including `admission_state = MIGRATING`, schema epoch, event-chain algorithm, genesis head values, and a null/empty migration failure code.
4. Run the bootstrap structural assertions within the bounded migration procedure, commit the bootstrap transaction, then read back the required SQLite pragmas, schema shape/version/checksums, `PRAGMA integrity_check`, `PRAGMA foreign_key_check`, and initial event-chain metadata while admission remains closed in memory.
5. Only after every bootstrap validation succeeds, set persisted `admission_state = READY` in a short transaction and then transition the service to `READY` in memory.
6. If `0001` fails before commit, its transaction rolls back and there is no successful persisted admission state. If it fails after a partial/indeterminate filesystem outcome or any required validation fails, the service remains admission-closed and reports `REGISTRY_UNAVAILABLE`; it must not claim `READY` or admit a request. A later recovery procedure may determine whether a registry exists and, if it does, persist `RECOVERY_REQUIRED` with a non-secret failure code.

For an existing registry and migration `0002+`:

1. The service holds admission closed in memory, acquires the local migration lock, validates the ordered migration set, checksums, current compatible schema epoch, and absence of unknown future migrations.
2. It persists `admission_state = MIGRATING` before applying any pending migration, then starts `BEGIN EXCLUSIVE` for one pending migration at a time.
3. It executes one migration, runs migration-local structural assertions, inserts the migration row, updates schema metadata, and commits.
4. After all pending migrations, required pragmas, integrity checks, foreign-key checks, and event-chain validation succeed, it sets `admission_state = READY` in a short transaction and only then opens admission in memory.
5. On migration failure, SQLite rolls back the affected migration transaction. The service then attempts a separate minimal transaction setting `admission_state = RECOVERY_REQUIRED` and a non-secret `migration_failure_code`. If even that write fails, the registry is unavailable by definition.

While admission is closed in memory or persisted state is `MIGRATING` or `RECOVERY_REQUIRED`, all Task/resource admission, gate consumption, resume, and state mutation requests fail closed. Read-only health diagnostics may report the safe error code and required operator action.

AP0 does not support arbitrary automatic downgrade. A rollback is either (a) a later forward corrective migration, or (b) an isolated restore of a verified compatible backup followed by reconciliation. A migration must not be removed, edited, or silently skipped after it has been recorded.

### 5.3 Record-version compatibility

Database migration compatibility and record `schema_version` compatibility are both required. Unknown future record versions may be surfaced as opaque diagnostic records but cannot be mutated, consumed, resumed, or used for resource admission. Unknown optional JSON fields are retained verbatim in canonical JSON export/import envelopes; the service does not default, discard, or infer their meaning.

## 6. Transaction map

All write transactions use `BEGIN IMMEDIATE`; no network operation, process operation, adapter call, health probe, backup stream, or human wait occurs inside the transaction. External resource creation is deliberately between two short transactions.

| Logical operation | Transactional steps | Required event(s) | Commit/result |
|---|---|---|---|
| Task creation | validate caller/request/idempotency; insert idempotency `IN_PROGRESS`; insert immutable Task in `CREATED`; append event; finalize idempotency response | `TASK_REQUESTED`, `TASK_CREATED` | Task and original response commit together. |
| Task admission | reread Task at expected revision; evaluate prerequisites/policy/gates; update to `READY` or `BLOCKED`; optionally insert pending Gate; append event(s) | `TASK_READY` or `TASK_BLOCKED`, plus `GATE_REQUESTED` if needed | No resource is allocated. |
| Generic Task state transition | validate caller role, allowed state edge, revision, policy and gate; update mutable Task fields/revision; append event | state-specific event | State and event commit atomically. |
| Budget reservation | inside resource allocation transaction, calculate reservations from `ALLOCATED`, `ACTIVE`, `IDLE`, `HEARTBEAT_MISSED`, and `STALE_CANDIDATE` leases; compare Task budget; reserve through new lease insertion | included in `RESOURCE_ALLOCATED` | Concurrent requests serialize through `BEGIN IMMEDIATE`; no oversubscription. |
| Resource allocation | validate Task state/operation/gate and this operation's idempotency key; reserve budget; insert immutable lease `ALLOCATED`; append event; finalize allocation response | `RESOURCE_ALLOCATED` | Runtime creation has not started. `resource_id` is returned as the canonical lifecycle identity. |
| External resource creation | outside a Control Plane transaction, use the allocated `resource_id` and `correlation_id` to request bounded runtime creation and collect observation evidence | none until a later Control Plane mutation | This is not a Control Plane mutation and does not share an idempotency record/key with allocation or binding. |
| Resource identity binding | validate this operation's idempotency key; reread allocated lease; validate exact observed identity against expected identity and exclusive identity index; set immutable bound identity, state `ACTIVE`, revision, event sequence | `IDENTITY_BOUND`, `RESOURCE_ACTIVE` | `BindResourceIdentity` is independently idempotent; lease can become active only with a committed exact binding. |
| Resource creation failure / terminalization | validate this operation's idempotency key; reread allocated lease; set `TERMINAL`, terminal reason, revision; release reservation by excluding terminal lease from budget; append evidence | `RESOURCE_CREATION_FAILED`, `RESOURCE_TERMINAL` | `MarkResourceTerminal` is independently idempotent. Failure evidence survives; no lease deletion. |
| Heartbeat projection update | validate caller lease capability and producer sequence; append event; upsert projection; update lease last heartbeat where applicable | `HEARTBEAT_RECORDED` | Audit history and current liveness commit together. |
| Gate creation | validate requesting caller/operation scope; insert `PENDING` Gate; append event | `GATE_REQUESTED` | A pending Gate grants nothing. |
| Gate approval/denial | Human Gate Adapter validates authority/reference; conditional Gate update at expected revision; append decision event | `GATE_DECIDED` | Approval includes exact scope and expiry. |
| Gate consumption | conditional update only where `status='APPROVED'`, `expires_at > now`, matching Task/resource/operation scope, `consumed_at IS NULL`, and expected revision; set `CONSUMED`; append operation-start event | `GATE_CONSUMED` plus guarded operation event | One transaction makes a Gate non-reusable before the operation is admitted. |
| Checkpoint creation | validate Task/lease consistency and secret-free payload; insert immutable checkpoint; update Task current checkpoint/revision; append event | `CHECKPOINT_CREATED` | A new checkpoint supersedes current pointer only; old checkpoint remains immutable. |
| Task pause | validate reason and disposition; create checkpoint first when policy requires; update Task to `PAUSED` with typed reason; append event | `CHECKPOINT_CREATED` where required, `TASK_PAUSED` | If checkpoint is required and fails, no resumable pause is claimed. |
| Task resume | validate current checkpoint, schema, budget, gates, prerequisites, and post-restart reconciliation result; update to `READY` or `RUNNING`; append event | `TASK_RESUMED` or `TASK_BLOCKED` | Does not reuse old process identity. |
| Terminalization | validate authority and result; ensure no new admission; update Task to `TERMINAL` with immutable terminal result; append event | `TASK_TERMINAL` | Leases remain independent for evidence/review. |
| Audit append | allocate next sequence, read prior head, canonicalize/hash, insert, apply linked projection, update head metadata | event-specific | An audit failure rolls back the logical internal mutation. |

If an external creation happens after a lease-allocation commit but before identity binding, the only durable state is `ALLOCATED`. If the service crashes or the bind transaction fails, the runtime artifact is indeterminate and must not receive autonomous work. Startup/recovery marks the operation for read-only reconciliation; it never assumes success from an in-memory client response.

## 7. Local service and IPC architecture

### 7.1 Selected transport: Unix-domain socket

AP0 uses a Unix-domain socket at a dedicated service-private path. Loopback HTTP is rejected for AP0 because it creates a TCP listener, expands accidental exposure/port-management surface, and does not add a needed interoperability benefit for a single-host control plane.

The service uses a length-prefixed UTF-8 JSON request/response protocol over `AF_UNIX` `SOCK_STREAM`:

```text
4-byte unsigned big-endian payload length
canonical JSON request or response bytes
```

Maximum request size is 256 KiB; maximum response size is 1 MiB. The service rejects invalid framing, noncanonical JSON, unsupported protocol versions, oversized bodies, and pipelined requests that exceed bounded per-connection concurrency. Protocol version `1.0` is the initial AP0 version. A request with a newer unsupported major version fails with `UNSUPPORTED_PROTOCOL` before any mutation.

The socket path and parent directory are owner-only. The service obtains Linux peer credentials (`SO_PEERCRED`) for every connection and records the local UID/PID only as corroborating connection evidence. Peer credentials alone are insufficient to identify roles when local clients share an account.

### 7.2 Caller authentication and bounded authorization context

Each request includes:

```text
RequestEnvelope {
  protocol_version: "1.0",
  operation: OperationName,
  correlation_id: "corr_<uuidv7>",
  caller: { role, identity_id },
  authorization: {
    capability_id,
    capability_proof,
    task_id: optional,
    resource_id: optional,
    allowed_operations: bounded list,
    expires_at,
    nonce
  },
  idempotency_key: required for mutation,
  expected_revision: required for revisioned mutation,
  body: canonical operation object
}
```

The service validates all of the following before dispatching a mutation:

1. UDS filesystem access and peer credential satisfy local client policy.
2. Caller `identity_id` is known to the AP0 identity policy and is valid for the declared role.
3. `capability_proof` validates through the capability-validation interface as a short-lived, capability-scoped proof. The raw proof is never persisted, logged, included in an event, or retrievable by API. The registry retains only a capability identifier/digest and expiry when required for audit correlation.
4. Capability scope matches caller role, Task/Lease, operation, expiry, nonce, and any target constraint. A Worker capability is bound to one Task and one Resource Lease.
5. The bounded authorization context is compatible with the immutable Task allowed-operation grant, risk/gate policy, and resource budget.

TC4 implements the capability-validation interface, scoped authorization behavior, and hermetic test issuer/fixtures only. It does not claim production or runtime capability issuance. Real capability issuance, transport, rotation, and revocation remain a Worker Manager/runtime concern, are outside the registry data model, must use a process-private delivery channel where applicable, and must not persist raw values in SQLite. The service provides no endpoint to retrieve a raw capability, secret, environment value, or credential.

### 7.3 Response envelope

```text
SuccessResponse {
  protocol_version,
  correlation_id,
  result: object,
  result_reference: optional stable record/event reference
}

ErrorResponse {
  protocol_version,
  correlation_id,
  error: {
    code: StableErrorCode,
    message: safe fixed or templated text,
    retryable: boolean,
    details: bounded non-secret identifiers and policy references only
  }
}
```

Errors never contain SQL statements, database paths, socket filesystem details, stack traces, raw adapter output, environment variables, capability proofs, provider credentials, or secret-bearing evidence.

## 8. Authorization roles

The service applies both role authorization and Task/lease capability scope. Role membership never grants ambient host, database, Docker, Git, or cleanup authority.

| Role | Permitted AP0 operations | Explicit prohibitions |
|---|---|---|
| `HERMES_COORDINATOR` | `CreateTask`, `GetTask` within scoped visibility, policy-permitted `TransitionTask`, `PauseTask`, `ResumeTask`, `CreateCheckpoint`, `CreateGate`, bounded `AppendEvent`, `GetTaskResources`, `GetPendingGates`, request reconciliation | cannot directly write SQLite, approve/consume its own human gate, bind runtime identity, increase budget, create arbitrary resource, mutate cleanup authority, execute adapters or cleanup |
| `WORKER_MANAGER` | scoped `GetTask`, `GetTaskResources`, `AllocateResource`, `BindResourceIdentity`, `MarkResourceTerminal`, Task/Worker `RecordHeartbeat`, bounded `TransitionTask` for runtime states, `CreateCheckpoint`, `ConsumeGate` as part of approved admission, `AppendEvent` | cannot create arbitrary Tasks, approve gates, change immutable Task scope/budget, change cleanup authority, use arbitrary host commands, or operate another Task without capability scope |
| `WORKER` | own-resource `RecordHeartbeat`, bounded `AppendEvent` evidence, report own result through scoped `MarkResourceTerminal` request, scoped `GetTask`/`GetTaskResources` read fields needed for work | cannot create Tasks/gates/checkpoints/resources, approve/consume gates, transition another Task, increase any budget, allocate unrestricted resources, bind another identity, change cleanup policy/authority, query arbitrary registry records |
| `REVIEWER` | scoped `GetTask`, `GetTaskResources`, `GetPendingGates`, append bounded review/validation evidence, request read-only reconciliation | cannot change Task lifecycle, allocate/bind resources, approve a gate, or mutate runtime |
| `JANITOR` | AP0 C0 only: request/read reconciliation and append candidate/evidence events under a bounded scope | cannot execute cleanup, mark a resource cleaned, terminate a process, delete paths, manage Docker/worktrees/previews, or grant itself C1/C2 authority |
| `HUMAN_GATE_ADAPTER` | `GetPendingGates`, `ResolveGate` for authority it is provisioned to represent | cannot create Tasks/resources, execute the gated operation, silently extend a gate, approve a mismatched scope, or use a generic human statement without authorization reference |
| `OBSERVABILITY_ADAPTER` | `ReconcileObservation` and bounded observation event append for a lease/adapter scope | cannot mutate runtime, allocate/bind a resource, perform arbitrary reads, expose raw host/docker/security data, or infer ownership |

A role-operation deny is always `UNAUTHORIZED`; a known role with an out-of-scope capability is also `UNAUTHORIZED`, not a fallback to a broader local identity.

## 9. API contract

All mutation operations require caller identity, protocol version, correlation ID, idempotency key, expected revision when a current record is changed, and bounded authorization context. `GetTask`, `GetTaskResources`, and `GetPendingGates` are read-only but still require caller identity, protocol version, correlation ID, and scope authorization.

| Operation | Primary request requirements | Success behavior |
|---|---|---|
| `CreateTask` | immutable Task contract fields, requested scope, risk class, budget | creates `CREATED` Task and returns task ID/revision |
| `GetTask` | task ID and read scope | returns sanitized current Task; never secret-bearing payloads |
| `TransitionTask` | task ID, expected revision, allowed target state and typed reason/result as needed | validates state graph and writes state/event atomically |
| `PauseTask` | task ID, expected revision, typed pause reason, active-resource disposition | creates required checkpoint then pauses, or fails closed |
| `ResumeTask` | task ID, expected revision, checkpoint reference | validates checkpoint/reconciliation/policy then returns `READY` or `RUNNING` |
| `CreateCheckpoint` | task ID, expected revision, secret-free snapshot | inserts immutable checkpoint and updates current pointer |
| `AllocateResource` | Task, type, requested operation, expected identity, reservation, TTL, metadata | inserts `ALLOCATED` lease after gate/budget checks |
| `BindResourceIdentity` | resource ID, expected revision, adapter observation | immutable exact identity binding and `ACTIVE` transition |
| `MarkResourceTerminal` | resource ID, expected revision, typed terminal reason/result evidence | terminalizes resource and preserves lease |
| `RecordHeartbeat` | Task/Resource scope, producer sequence/status/evidence | appends heartbeat event and updates projection |
| `CreateGate` | Task/resource scope, exact operation, risk, authority requirement | creates `PENDING` Gate |
| `ResolveGate` | Gate ID, expected revision, approve/deny decision, authority reference, expiry | atomically decides Gate and emits audit event |
| `ConsumeGate` | Gate ID, expected revision, exact operation context | atomically marks an unexpired matching approved Gate consumed |
| `AppendEvent` | allowlisted evidence event type/payload under caller scope | appends event only; cannot impersonate state mutation |
| `GetTaskResources` | Task ID and read scope | returns resource current state and sanitized metadata |
| `GetPendingGates` | bounded Task/resource filter | returns visible pending/approved-unexpired gates |
| `ReconcileObservation` | expected lease, adapter type/version, sanitized observation | compares expected/observed state, appends result evidence; never mutates runtime |

`AppendEvent` is intentionally constrained. The service owns event types that represent state changes; a caller cannot append `TASK_READY`, `RESOURCE_ACTIVE`, `GATE_CONSUMED`, or a similar authoritative event without the matching service mutation path.

## 10. Idempotency protocol

Every Control Plane mutation has its own idempotency key and its own idempotency record. The namespace is `(caller_id, idempotency_key)`. The same key reused by the same caller for a different operation, target, authorization scope, or canonical request body is an `IDEMPOTENCY_CONFLICT` even if the requested result would otherwise be similar.

`resource_id` is the canonical identity joining lifecycle phases for one Resource Lease: allocation, bounded external creation, identity binding, and terminalization. `correlation_id` joins the broader logical execution across those phases and related events; it does not merge mutation idempotency. `AllocateResource`, `BindResourceIdentity`, and `MarkResourceTerminal` are independently idempotent mutations. External resource creation is not a Control Plane mutation and has no registry idempotency record; its request/evidence is associated through `resource_id` and `correlation_id`.

For every mutation:

1. The service constructs a SHA-256 request fingerprint over a JCS object containing protocol version, operation, caller identity, effective capability scope identifier, expected revision, and body. It excludes the raw capability proof and excludes transport retry details.
2. In the first transaction, it inserts `idempotency_requests` as `IN_PROGRESS` or reads the existing row.
3. If the existing row matches operation and fingerprint and is `SUCCEEDED` or `FAILED`, return the stored original response body/result reference without replaying a state mutation or external creation.
4. If it matches and is `IN_PROGRESS`, return a retryable `REGISTRY_UNAVAILABLE`-style in-progress response only when the caller may safely retry the same key; the service does not launch a duplicate external operation.
5. If any material field differs, return `IDEMPOTENCY_CONFLICT` and append no new mutation.
6. When the logical operation commits, that mutation's transaction finalizes its own record as `SUCCEEDED` or a stable `FAILED` result. A later `BindResourceIdentity` or `MarkResourceTerminal` request creates/finalizes a separate record and key; each response references the same `resource_id` where applicable.

Retention is a minimum of 30 days after finalization and never shorter than the longest Task/Lease retry window. AP0-TC4 performs no automatic deletion; a future retention implementation must preserve incomplete records and export evidence before pruning.

## 11. Error taxonomy

The following machine-readable codes are stable AP0 v1 error codes. The error message is safe text; callers must branch on `code`, not wording.

| Code | Meaning / retry behavior |
|---|---|
| `INVALID_REQUEST` | Malformed envelope, JSON, identifier, timestamp, field combination, or producer sequence. Not retryable without correction. |
| `UNSUPPORTED_SCHEMA` | Record or migration schema version is unknown/invalid/future. Not retryable until compatible reader/migration exists. |
| `UNSUPPORTED_PROTOCOL` | API protocol major version unsupported. Not retryable without compatible client. |
| `UNKNOWN_IDENTITY` | Caller identity is not provisioned. Not retryable without identity provisioning. |
| `UNAUTHORIZED` | Role, peer, capability, scope, gate, or operation authorization fails. Not retryable without changed authorization. |
| `TASK_NOT_FOUND` | Requested Task does not exist or is not visible to caller. Not retryable as submitted. |
| `RESOURCE_NOT_FOUND` | Requested Resource Lease does not exist or is not visible to caller. Not retryable as submitted. |
| `INVALID_STATE_TRANSITION` | Requested Task/Resource/Gate edge or revision is invalid. Not retryable without reread/correction. |
| `TASK_BLOCKED` | Task prerequisite, reconciliation, or policy block prevents progress. Retry only after recorded unblock condition. |
| `TASK_TERMINAL` | Requested normal-work mutation targets terminal Task. Not retryable. |
| `GATE_REQUIRED` | Exact operation needs a pending/approved matching Gate. Retry only after approval. |
| `GATE_DENIED` | Matching Gate is denied. Not retryable without a new Gate. |
| `GATE_EXPIRED` | Gate expired before use. Not retryable without a new Gate. |
| `GATE_ALREADY_CONSUMED` | Gate is single-use and already consumed. Not retryable with that Gate. |
| `BUDGET_EXCEEDED` | Requested reservation exceeds immutable Task budget. Not retryable without a new Task/scope decision. |
| `RESOURCE_LIMIT_REACHED` | Exclusive resource constraint or policy concurrency limit reached. Retry only after state/policy changes. |
| `IDENTITY_BIND_FAILED` | Resource exists only as unbound allocation or observation did not meet expected identity. Requires reconciliation/recovery. |
| `IDENTITY_MISMATCH` | Observed runtime identity conflicts with expected/bound identity. Blocks dependent work. |
| `IDEMPOTENCY_CONFLICT` | Same caller/key has a different request fingerprint/operation. Not retryable with that key. |
| `REGISTRY_UNAVAILABLE` | Registry startup, lock, WAL, migration, storage, or busy timeout prevents safe use. Retry only within bounded transient policy. |
| `AUDIT_WRITE_FAILED` | Required audit event/hash-chain write cannot commit. Associated mutation is not accepted. |
| `CHECKPOINT_FAILED` | Required checkpoint could not validate or persist. A resumable pause/resume is not accepted. |
| `ADAPTER_UNAVAILABLE` | Required bounded adapter cannot produce evidence, including access denial. No heuristic substitute. |
| `OBSERVATION_INCONCLUSIVE` | Adapter result cannot establish expected state safely. No ownership or authority inferred. |
| `INTERNAL_ERROR` | Unexpected non-secret service failure. Retry only if response marks it retryable. |

## 12. Policy defaults

AP0 MVP freezes `max_workers_per_task = 1` and `max_workers_global = 1`. Increasing global parallelism requires later evidence and an explicit policy change.

Defaults favor predictable finite work over throughput. They are policy values, not ambient permissions, and each is stored/referenced by policy version in admission/checkpoint/audit payloads.

| Policy | AP0 default | Rationale |
|---|---:|---|
| Simultaneous Workers per Task | 1 | Keeps one accountable execution chain and avoids unreviewed intra-Task races in the MVP. |
| Simultaneous Workers globally | 1 | AP0 MVP permits one worker globally as well as per Task. Increasing global parallelism requires later evidence and an explicit policy change. |
| Simultaneous Processes per Task | 3 | Covers one Worker plus bounded subordinate processes without normalizing process fan-out. |
| Previews per Task | 1 | One branch/HEAD-backed preview is sufficient for review and prevents ambiguous ownership. |
| Worktrees per Task | 1 | AP0 MVP treats a Task as one bounded development context. |
| Default Worker timeout | 45 minutes | Long enough for bounded implementation/validation work; short enough to surface stuck work for review. |
| Maximum Worker timeout without new policy/gate | 120 minutes | Prevents unbounded extension by a caller. |
| Worker heartbeat interval | 30 seconds while active | Provides liveness evidence without excessive write churn. |
| Independently active Process heartbeat interval | 30 seconds | Matches Worker semantics for a process that may outlive its Worker. |
| Preview owner heartbeat interval | 30 seconds plus health observation | Requires ownership evidence and service health, not one alone. |
| Miss deadline | 90 seconds after last accepted heartbeat | Allows two missed intervals before marking a liveness problem. |
| Grace interval | 60 additional seconds | Allows read-only reconciliation/late receipt before escalation from `HEARTBEAT_MISSED` to review candidate. |
| Preview TTL | 2 hours | Fits a review session and limits forgotten preview retention. |
| Temporary runtime resource TTL guidance | Worker/Test Env: timeout + 15 min; Temp Dir: 24 h; Artifact: evidence-retained; Worktree: review/evidence policy | Separates finite runtime liveness from retained evidence. TTL expiry is never deletion authorization. |
| Preview bind address | `127.0.0.1` | Prevents accidental all-interface exposure. |
| Preview port range | `38000-38199` inclusive | Isolates AP0 allocations from conventional service ports and gives 200 bounded leaseable ports. |
| Automatic retries of transient Control Plane calls | 2 retries after original attempt | Limits duplicate/hidden retry loops; all retries use the same idempotency key. |
| Retry backoff | full-jitter exponential: base 250 ms, cap 2 s | Smooths brief SQLite contention without long uncontrolled waits. |
| Provider quota polling | no fixed reset-time assumption; at most one availability observation every 5 min, full-jitter 0–60 s, max 12 observations per pause | Provider quota calendars are not trusted; bounded observation prevents retry/spawn loops. |

At 90 seconds since the last accepted heartbeat, the service records `HEARTBEAT_MISSED`, stops dependent new admission, and starts the 60-second grace interval. At 150 seconds without accepted heartbeat or conclusive reconciliation, it records `STALE_CANDIDATE` evidence. Neither transition terminates a resource or authorizes cleanup.

## 13. Preview network policy

1. The only AP0 default preview bind address is `127.0.0.1`. `0.0.0.0`, IPv6 all-interface bind, public ingress, reverse-proxy publication, and private-network proxy exposure are denied unless a separately authorized future operation defines the exact boundary.
2. A preview allocation includes immutable metadata: requested `bind_address`, port, health endpoint, Task/Worktree/branch/HEAD evidence, TTL, expected process identity, and declared launcher capability class.
3. Future preview launcher discovery classifies a launcher as one of two capability classes:
   - `SOCKET_ACTIVATION` is the preferred and strongest contract. The Worker Manager reserves the OS port by binding it before spawn and the launcher inherits the manager-held bound socket file descriptor, closing the bind time-of-check/time-of-use gap.
   - `BOUNDED_PORT_HANDOFF` does not inherit a file descriptor. It requires its own later threat model, collision-handling design, and identity readback proof before it can be authorized for use. It is not authorized by this AP0 MVP policy.
   Discovery must not reject a future launcher solely because it lacks inherited-file-descriptor support; it must record the declared capability class. TC4 implements policy, schema, and tests only and launches no preview.
4. For a `SOCKET_ACTIVATION` launcher, the registry unique index reserves `(bind_address, port)` before runtime creation and the manager treats an OS bind failure as a collision, terminalizing the allocated lease with `RESOURCE_CREATION_FAILED`. It never adopts an existing listener merely because it uses the requested port. `BOUNDED_PORT_HANDOFF` collision behavior is deferred with its required later threat model.
5. The health endpoint is explicit and local-only. Default validation is `GET` to the recorded loopback URL, no redirects, 2-second connect timeout, 3-second total response timeout, maximum 32 KiB response body, and expected HTTP `200`. The expected schema is a small secret-free response containing the lease `resource_id`, Task `task_id`, and expected `head_sha` when the preview technology supports it.
6. Ownership proof is the combined evidence of: (a) the immutable registry lease; (b) manager-held/inherited socket reservation; (c) strong backing process identity; (d) Task/Worker lease capability; and (e) health readback. The health body alone is corroborating evidence, not authority.
7. Before `ACTIVE`, the manager reads back listener address/port, backing identity, health result, Task/worktree branch/HEAD evidence, and lease ID. A failure leaves the lease terminal or unbound and blocks all preview use.
8. TTL expiry, health failure, or missed owner heartbeat produces review evidence only. It does not shut down the listener.

## 14. Observability adapter interfaces

Adapters are typed, read-only, scope-bound services or libraries called by the Control Plane Service/Operations Gateway. They never expose shell access to Workers. Every response includes `adapter_version`, `observed_at`, `correlation_id`, a bounded evidence reference, and one of the result statuses described below.

### 14.1 Process observability

```text
ProcessObservation {
  pid: integer | null,
  start_time: string | null,
  boot_id: string | null,
  process_group: integer | null,
  parent_pid: integer | null,
  user: string | null,
  cwd: string | null,
  executable: string | null,
  cgroup: string | null,
  status: MATCHED | MISSING | IDENTITY_MISMATCH | ACCESS_DENIED | INCONCLUSIVE
}
```

Input is a lease-bound expected process identity, never an arbitrary PID query. The minimum strong match is `(pid, start_time, boot_id)`. Process group, parent PID, user, CWD, executable, and cgroup are corroborating evidence. PID-only equality is insufficient. The adapter performs no process mutation.

### 14.2 Git/worktree observability

```text
GitWorktreeObservation {
  repository_identity: string | null,
  worktree_path: string | null,
  registered_state: REGISTERED | UNREGISTERED | UNKNOWN,
  branch: string | DETACHED | UNKNOWN,
  head: string | null,
  base: string | null,
  dirty: CLEAN | DIRTY | UNKNOWN,
  lock_state: LOCKED | UNLOCKED | UNKNOWN,
  status: MATCHED | MISSING | IDENTITY_MISMATCH | ACCESS_DENIED | INCONCLUSIVE
}
```

Input is an explicit lease path and expected repository identity. The adapter is read-only: no worktree create/remove, checkout, reset, clean, ref mutation, lock manipulation, or Git configuration mutation. Dirty or unknown/locked worktree evidence blocks any clean-worktree prerequisite and is retained as drift evidence.

### 14.3 Docker observability

A future Operations Gateway Docker adapter returns only this sanitized response for an explicitly authorized container/service scope:

```text
DockerObservation {
  container_identity: string | null,
  container_name: string | null,
  compose_project: string | null,
  compose_service: string | null,
  image_digest: string | null,
  state: string | null,
  health: string | null,
  restart_policy: string | null,
  networks: [string],
  mounts: [{ destination: string, type: string }],
  published_ports: [{ protocol: "tcp" | "udp", host_address: string, host_port: integer, container_port: integer }],
  approved_labels: { string: string },
  status: MATCHED | MISSING | IDENTITY_MISMATCH | ACCESS_DENIED | INCONCLUSIVE
}
```

It explicitly excludes environment-variable values, secrets, raw inspect JSON, raw command lines, filesystem contents, `docker exec`, Docker socket access, log streaming, image/build/pull actions, Compose operations, and every Docker mutation. AP0-TC4 may define the interface and fixtures only; it does not acquire Docker access.

### 14.4 Security observability

```text
SecurityObservation {
  ssh: {
    permit_root_login: ENABLED | DISABLED | PROHIBITED | UNKNOWN,
    password_authentication: ENABLED | DISABLED | UNKNOWN,
    pubkey_authentication: ENABLED | DISABLED | UNKNOWN,
    allow_tcp_forwarding: ENABLED | DISABLED | UNKNOWN,
    x11_forwarding: ENABLED | DISABLED | UNKNOWN
  },
  firewall: {
    active: ACTIVE | INACTIVE | UNKNOWN,
    default_incoming: ALLOW | DENY | REJECT | UNKNOWN,
    allowed_tcp_rules: [string],
    allowed_udp_rules: [string]
  },
  fail2ban: { active: ACTIVE | INACTIVE | NOT_INSTALLED | UNKNOWN },
  status: MATCHED | ACCESS_DENIED | INCONCLUSIVE
}
```

The adapter returns only named effective policy facts and sanitized port/rule summaries. It returns no arbitrary configuration-file output, private keys, password material, raw firewall configuration, shell output, or mutable system interface. `UNKNOWN`, `ACCESS_DENIED`, and `INCONCLUSIVE` are valid observations; none is silently treated as secure or authorized.

## 15. Reconciliation contract

Reconciliation is read-only. It compares persisted expectations with bounded adapter evidence, records evidence/events, and blocks unsafe further work when needed. It does not stop, delete, adopt, relabel, attach, or repair a runtime resource.

```text
ExpectedResource {
  task_id,
  resource_id,
  resource_type,
  lease_state,
  expected_identity,
  bound_identity,
  heartbeat_requirement,
  ttl,
  policy_version
}

ObservedResource {
  adapter_type,
  adapter_version,
  observation,
  observed_at,
  evidence_ref
}

ReconciliationResult {
  result: MATCHED | MISSING_RUNTIME | UNKNOWN_RUNTIME | IDENTITY_MISMATCH |
          HEARTBEAT_MISSED | STATE_DRIFT | UNOWNED_UNKNOWN | INCONCLUSIVE,
  expected_resource_id: optional,
  evidence_refs: [reference],
  blocking_reason: optional,
  next_permitted_action: optional
}
```

Result semantics:

| Result | Meaning and mandatory behavior |
|---|---|
| `MATCHED` | Strong expected identity and relevant state match. Append observation; do not infer unrelated authority. |
| `MISSING_RUNTIME` | Expected strong identity is absent. Record evidence; do not automatically create a replacement or assume cleanup occurred. |
| `UNKNOWN_RUNTIME` | Observed runtime cannot be confidently linked to a lease. Record it; do not adopt or mutate it. |
| `IDENTITY_MISMATCH` | Expected and observed identity conflict, including PID reuse or wrong repository/HEAD. Block dependent work. |
| `HEARTBEAT_MISSED` | Liveness deadline elapsed. Record the deadline/last accepted heartbeat; do not infer death. |
| `STATE_DRIFT` | Valid observation conflicts with declared lease/task state, health, policy, or expected Git context. Block affected operation. |
| `UNOWNED_UNKNOWN` | No valid AP0 lease exists for observed resource. Preserve unknown status; do not invent Task ownership. |
| `INCONCLUSIVE` | Adapter cannot safely establish a result. Preserve evidence and block only the operation that requires the missing proof. |

Each reconciliation creates a `RECONCILIATION_RECORDED` event with result, adapter version, policy version, evidence references, and correlation ID. The service may update a lease only to record non-destructive evidence states permitted by policy (`HEARTBEAT_MISSED` or `STALE_CANDIDATE`); it may not mutate runtime from reconciliation.

## 16. Quota pause policy

AP0 freezes the following quota behavior:

```text
RUNNING
  -> provider quota unavailable observation
  -> create immutable checkpoint
  -> PAUSED(reason = PROVIDER_QUOTA)
  -> no new Worker, Preview, or Task Worktree admission
```

While paused:

- no new Worker, Preview, Process, or Task Worktree is admitted;
- existing finite resources follow their declared stop/retention policy;
- an active worker may only finish an already-authorized bounded in-flight operation if doing so does not require new provider work; otherwise it stops accepting work and reports state;
- a missed heartbeat remains a missed heartbeat, not an assumed quota pause;
- no provider quota reset time is hardcoded.

Resume path:

```text
availability observed
  -> latest checkpoint valid and supported
  -> read-only reconciliation of non-terminal resources
  -> policy / budget / gate / prerequisite re-evaluation
  -> READY or RUNNING
```

Resume never revives an expired Gate, old process identity, invalid checkpoint, exhausted reservation, or unsupported schema. Provider availability polling follows the bounded policy in section 12.

## 17. Backup and restore test design

AP0-TC4 must implement a hermetic test that never reads, writes, backs up, or restores a live registry.

1. Create an isolated temporary test directory with owner-only permissions and a test-only SQLite registry.
2. Apply all migrations.
3. Insert representative Task, allocated and active Resource Lease, terminal failed Resource Lease, audit chain, current heartbeat projection/history event, approved and consumed Gate, pending Gate, immutable checkpoint, idempotency result, and unknown optional export fields.
4. Verify `PRAGMA integrity_check` returns `ok`, `PRAGMA foreign_key_check` returns no rows, migration checksums match, and event-chain validation succeeds.
5. Perform backup through a SQLite-aware backup API or a tested quiesced WAL-aware backup procedure. A byte-for-byte filesystem copy of only the main database while WAL is active is not an acceptable general backup method.
6. Validate the backup in a separate process/path before acceptance.
7. Restore only to a different isolated path. Never overwrite the source registry in this test.
8. On the restored database, run integrity check, foreign-key check, migration/schema-version validation, event sequence/hash-chain validation, identifier preservation checks, and idempotency response preservation checks.
9. Start the restored service in `RECOVERY_REQUIRED` until it runs read-only reconciliation for every non-terminal or allocated resource. The test asserts that new admission is denied before reconciliation and permitted only after the required recovery state is resolved according to fixture observations.
10. Assert that no test ever contacts a runtime socket, production PostgreSQL, `~/.hermes/state.db`, Docker, systemd, a provider, or a live registry.

## 18. Paperclip conformance fixture

AP0-TC4 must include a versioned portable JSON fixture, for example `tests/fixtures/paperclip/ap0-v1-control-plane-export.json`, with a separately recorded SHA-256 manifest. The fixture is an export artifact, not a SQLite file and not a product-domain dataset.

It contains:

- one active `Task` with immutable scope/budget and current checkpoint;
- one terminal `Task` with terminal result;
- an `ALLOCATED` lease representing an interrupted create path;
- one active Worker/Process identity-bound lease;
- one active Preview lease with loopback metadata;
- one terminal resource-creation-failed lease;
- ordered append-only events including genesis and heartbeat history;
- current heartbeat projection;
- one pending Gate, one approved Gate, one denied Gate, one expired Gate, and one consumed Gate;
- immutable checkpoints for active and quota-paused states;
- known optional fields plus unknown optional JSON fields at record and payload level;
- Task/Lease ownership references and correlation IDs.

A conforming Paperclip importer/exporter must prove all of the following:

1. IDs, timestamps, record schema versions, correlation IDs, event sequences, hashes, and predecessor links are preserved exactly.
2. Unknown optional fields are retained byte-for-byte in canonical JSON or semantically equivalently under JCS; they are not discarded or defaulted.
3. Event ordering and hash-chain validation remain valid after import/export.
4. A `CONSUMED` Gate remains consumed and cannot be used to authorize another operation; denied/expired Gates remain non-authorizing.
5. Task-to-Resource ownership remains unchanged. An `UNOWNED_UNKNOWN` or legacy unknown entry is not converted into an owned lease by import.
6. Active versus terminal state is preserved without claiming live runtime identity was revalidated by import. The imported registry enters reconciliation-required state before new admission.

## 19. Conformance and negative-test matrix

### 19.1 Positive conformance tests

| Area | Required proof |
|---|---|
| Schema startup | Required pragmas read back correctly; owner-mode validation rejects unsafe directory/file modes; migration metadata initializes correctly. |
| Identifier generator | Every family prefix/UUIDv7 form validates; fallback uses CSPRNG source under test seam; no timestamp-only or PID-derived identifier is accepted. |
| Task immutability | Direct service-path attempts to alter immutable Task scope/budget/creator fields fail; permitted revisioned state update succeeds with event. |
| Lease binding | `ALLOCATED` cannot become `ACTIVE` without exact identity; bound identity cannot change; active duplicate identity fails. |
| Audit | Genesis, sequence allocation, canonical JCS hash, head metadata, append-only behavior, and event/state atomicity validate. |
| Heartbeats | Event history plus projection update atomically; sequence ordering and same-request idempotency work; liveness query uses projection. |
| Gates | exact-scope approval, expiry, one-time atomic consumption, and authorization reference behavior validate. |
| Checkpoints | secret-free schema validation, immutability, Task current-pointer update, and task/resource consistency validate. |
| API/authorization | Every role matrix allow/deny is exercised over UDS protocol framing and bounded capability scope. |
| Policy | Task/global resource limits, preview bind policy, port range, timeout/TTL, and bounded retry behavior validate. |
| Backup/restore | Hermetic procedure in section 17 passes and restored registry requires reconciliation. |
| Export/import | Paperclip fixture round-trip satisfies all section 18 invariants. |

### 19.2 Negative cases

| Case | Setup / stimulus | Required result |
|---|---|---|
| PID reuse | Reuse a numeric PID with different start time or boot ID | `IDENTITY_MISMATCH`; no lease binding or cleanup authority. |
| Duplicate Task request | Repeat same `CreateTask` request/key | Original Task/result returned; no second Task/event mutation. |
| Duplicate Resource request | Repeat same allocation request/key | Original lease/result returned; no duplicate reservation or spawn request. |
| Idempotency conflict | Same caller/key, different operation/body/capability scope | `IDEMPOTENCY_CONFLICT`; no mutation. |
| Budget race | Concurrent allocations that jointly exceed budget | At most one commits; other returns `BUDGET_EXCEEDED` or `RESOURCE_LIMIT_REACHED`; no spawn before losing allocation. |
| Port collision | Registry-reserved or OS-bound loopback port is unavailable | Allocation terminalizes with failure evidence; existing listener is never adopted. |
| Worker spawn failure | External creation reports failure after allocation | Lease becomes terminal with `RESOURCE_CREATION_FAILED`; unused reservation released atomically. |
| Identity bind failure | Spawn appears to succeed but adapter cannot prove expected identity | `IDENTITY_BIND_FAILED`; resource remains unbound/non-operational and no worker work is issued. |
| Registry unavailable | Socket absent, migration state recovery-required, WAL setup failure, or busy timeout | No Task/resource admission, Gate consumption, heartbeat acceptance, or new worker start. |
| WAL recovery | Simulate interrupted committed/uncommitted WAL state in isolated fixture | SQLite recovery plus integrity/chain validation determine safe state; admission remains disabled on mismatch. |
| Partial transaction failure | Inject failure after event construction before commit | Neither event nor projection/state mutation persists; idempotency does not claim success. |
| Unsupported future schema | Submit/load record with newer major/unknown required semantics | `UNSUPPORTED_SCHEMA`; only opaque diagnostics, no mutation/defaulting. |
| Unknown caller | Valid protocol but unprovisioned identity | `UNKNOWN_IDENTITY`; no visibility escalation. |
| Gate expiry | Attempt consumption at/after expiry | `GATE_EXPIRED`; Gate cannot be reused or implicitly extended. |
| Gate reuse | Consume approved Gate twice concurrently | Exactly one consumes; other returns `GATE_ALREADY_CONSUMED`; one operation-start event only. |
| Audit failure | Inject event hash/insert/head update failure | Associated logical state change rolls back; `AUDIT_WRITE_FAILED`; no success response. |
| Checkpoint failure | Reject invalid/secret-bearing snapshot or inject insert failure | `CHECKPOINT_FAILED`; Task cannot claim resumable pause; dependent work blocked. |
| Hermes crash | Crash after committed allocation but before external create/bind | Lease remains `ALLOCATED`; restart demands reconciliation and does not assume resource exists. |
| Host reboot | Prior process boot ID changes | Old process identity invalid; resume requires checkpoint plus reconciliation; no PID reuse. |
| Heartbeat missed | Advance test clock beyond 90 then 150 seconds | Evidence transitions to missed/stale candidate; no process termination or cleanup authorization. |
| Quota pause | Provider returns quota-unavailable observation | Checkpoint then `PAUSED(PROVIDER_QUOTA)`; new worker/preview/worktree admission denied; no fixed reset timer. |
| Dirty worktree | Git adapter returns `DIRTY` | `STATE_DRIFT`/block for clean prerequisite; no removal/cleanup. |
| Docker observation denied | Docker adapter returns access denied | `ADAPTER_UNAVAILABLE` or inconclusive evidence; no raw Docker fallback or mutation. |
| Security observation denied | Security adapter returns access denied | `ADAPTER_UNAVAILABLE` or inconclusive evidence; no arbitrary configuration output or mutation. |
| Unknown legacy process | Observation has no matching strong lease identity | `UNOWNED_UNKNOWN`; no Task fabrication, adoption, stop, or deletion. |

No negative path may silently grant authority, treat absence of evidence as approval, create a replacement resource automatically, or make a destructive runtime change.

## 20. AP0-TC4 implementation surface proposal

Repository structure currently places Python services beneath `services/<service>/` with an `app/`, `tests/`, and `requirements.txt` layout. There is no existing root `platform/` source component. Therefore AP0-TC4 should create a bounded standalone local Python service at `services/control_plane/`, rather than introduce a new top-level `platform/control-plane/` convention or embed registry logic in `services/web`/Hermes.

Proposed exact source tree, not created by TC3:

```text
services/control_plane/
  requirements.txt
  app/
    __init__.py
    main.py                    # UDS service process entry point
    service.py                 # operation dispatch and transaction orchestration
    protocol.py                # framed UDS envelopes and version negotiation
    auth.py                    # peer credential and capability-scope validation
    errors.py                  # stable ErrorResponse definitions
    ids.py                     # UUIDv7/native-fallback generation and validation
    models.py                  # validated transport/domain data models
    policy.py                  # frozen AP0 defaults and policy evaluation
    schema.py                  # record JSON schema validation and secret-free checks
    storage/
      __init__.py
      sqlite.py                # connection/pragmas/short transaction helpers
      migrations.py            # ordered checksum migration runner
      repositories.py          # constrained SQL access; no raw caller SQL
      event_chain.py           # JCS envelope hashing and validator
      idempotency.py           # request fingerprint/result protocol
      backup.py                # SQLite-aware backup/restore helpers
    adapters/
      __init__.py
      process.py               # typed read-only process adapter interface
      git_worktree.py          # typed read-only Git/worktree interface
      preview.py               # typed local listener/health interface
      docker.py                # sanitized future gateway interface only
      security.py              # sanitized future gateway interface only
      reconciliation.py        # Expected/Observed/ReconciliationResult
  migrations/
    0001_initial_schema.sql
  tests/
    test_ids.py
    test_schema_contract.py
    test_migrations.py
    test_storage_transactions.py
    test_task_transitions.py
    test_resource_admission.py
    test_event_chain.py
    test_heartbeats.py
    test_gates.py
    test_checkpoints.py
    test_idempotency.py
    test_protocol_uds.py
    test_authorization.py
    test_policy_defaults.py
    test_preview_policy.py
    test_adapters_contract.py
    test_reconciliation.py
    test_backup_restore.py
    test_paperclip_fixture.py
    fixtures/
      paperclip/
        ap0-v1-control-plane-export.json
        ap0-v1-control-plane-export.sha256
```

The proposed TC4 surface intentionally excludes `infra/docker-compose.yml`, production PostgreSQL migrations, systemd units, Dockerfiles, runtime configuration, a Janitor executor, preview runtime launchers, Git worktree mutators, production/runtime capability issuance or transport, and any production/infrastructure integration. TC4 implements only capability validation, scoped authorization behavior, and hermetic test issuer/fixtures. Local service installation/activation and any runtime mutation require a subsequent explicit authorization beyond this TC3 document.

## 21. AP0-TC4 acceptance criteria

AP0-TC4 is complete only when it produces an implementation conforming to this design and demonstrates, in isolated local tests, that:

1. the dedicated SQLite registry is never confused with production PostgreSQL or `~/.hermes/state.db`;
2. required pragmas, owner-only permissions, schema migrations, constraints/indexes, and append-only protections are verified;
3. all mutation paths in section 6 commit state and audit evidence atomically or fail closed;
4. UDS protocol, role authorization, scoped capability validation, hermetic test issuer/fixtures, per-mutation idempotency, and stable errors are tested; TC4 does not claim production/runtime capability issuance;
5. task/resource/gate/checkpoint/heartbeat invariants and policy defaults are tested;
6. preview policy remains loopback-only and port identity-safe; no public bind fallback exists;
7. adapters remain typed/read-only/sanitized and their denied/inconclusive paths are covered;
8. backup/restore and Paperclip fixture tests are hermetic and pass;
9. the full negative matrix is implemented with no destructive host/runtime behavior;
10. implementation validation includes the repository-available checks, diff inspection, and `git diff --check`, without claiming staging, production, or runtime mutation evidence.

## Final verdict

AP0_TC3_R1_READY
