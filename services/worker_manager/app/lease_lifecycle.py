"""In-memory Worker lease orchestration; the Control Plane remains authoritative."""
from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol

_NONCE = re.compile(r"[A-Za-z0-9_-]+\Z")
_TERMINAL_REASONS = {"RESOURCE_CREATION_FAILED", "COMPLETED", "FAILED"}


class WorkerLeaseClient(Protocol):
    def allocate_worker(self, **kwargs: Any) -> dict[str, Any]: ...
    def bind_worker(self, **kwargs: Any) -> dict[str, Any]: ...
    def terminalize_worker(self, **kwargs: Any) -> dict[str, Any]: ...


@dataclass(frozen=True)
class WorkerLeaseSpec:
    task_id: str
    correlation_id: str
    requested_operation: Mapping[str, Any]
    expected_boot_id: str
    expected_uid: int
    executable_class: str
    worktree_ref: str


@dataclass(frozen=True)
class WorkerAllocationIntent:
    spec: WorkerLeaseSpec
    expectation: Mapping[str, Any]
    idempotency_key: str
    launch_nonce: str = field(repr=False)


@dataclass(frozen=True)
class AllocatedWorkerLease:
    task_id: str
    correlation_id: str
    resource_id: str
    revision: int
    expectation: Mapping[str, Any]
    launch_nonce: str = field(repr=False)


@dataclass(frozen=True)
class BoundWorkerLease:
    task_id: str
    correlation_id: str
    resource_id: str
    revision: int
    observation: Mapping[str, Any]


@dataclass(frozen=True)
class TerminalWorkerLease:
    task_id: str
    correlation_id: str
    resource_id: str
    revision: int
    reason: str


class WorkerLeaseLifecycle:
    def __init__(
        self,
        client: WorkerLeaseClient,
        *,
        nonce_factory: Callable[[], str] = lambda: secrets.token_urlsafe(32),
    ) -> None:
        self.client = client
        self.nonce_factory = nonce_factory

    def prepare_allocation(self, spec: WorkerLeaseSpec) -> WorkerAllocationIntent:
        self._validate_spec(spec)
        nonce = self.nonce_factory()
        if not isinstance(nonce, str) or not nonce.isascii() or not 43 <= len(nonce) <= 128 or not _NONCE.fullmatch(nonce):
            raise ValueError("nonce factory returned an invalid launch nonce")
        expectation = {
            "kind": "WORKER_PROCESS_V1",
            "expected_boot_id": spec.expected_boot_id,
            "expected_uid": spec.expected_uid,
            "executable_class": spec.executable_class,
            "worktree_ref": spec.worktree_ref,
            "nonce_sha256": hashlib.sha256(nonce.encode("ascii")).hexdigest(),
        }
        return WorkerAllocationIntent(
            spec=spec,
            expectation=expectation,
            idempotency_key=self._key("worker-allocate", spec.task_id, spec.correlation_id),
            launch_nonce=nonce,
        )

    def allocate(self, intent: WorkerAllocationIntent, capability: dict[str, Any]) -> AllocatedWorkerLease:
        result = self.client.allocate_worker(
            task_id=intent.spec.task_id,
            correlation_id=intent.spec.correlation_id,
            capability=capability,
            idempotency_key=intent.idempotency_key,
            requested_operation=dict(intent.spec.requested_operation),
            expectation=dict(intent.expectation),
        )
        return AllocatedWorkerLease(
            task_id=intent.spec.task_id,
            correlation_id=intent.spec.correlation_id,
            resource_id=result["resource_id"],
            revision=result["revision"],
            expectation=dict(intent.expectation),
            launch_nonce=intent.launch_nonce,
        )

    def bind(
        self,
        lease: AllocatedWorkerLease,
        observation: Mapping[str, Any],
        capability: dict[str, Any],
    ) -> BoundWorkerLease:
        key = self._key("worker-bind", lease.resource_id, lease.correlation_id, str(lease.revision))
        result = self.client.bind_worker(
            resource_id=lease.resource_id,
            correlation_id=lease.correlation_id,
            capability=capability,
            idempotency_key=key,
            expected_revision=lease.revision,
            observation=dict(observation),
            launch_nonce=lease.launch_nonce,
        )
        return BoundWorkerLease(
            task_id=lease.task_id,
            correlation_id=lease.correlation_id,
            resource_id=lease.resource_id,
            revision=result["revision"],
            observation=dict(observation),
        )

    def terminalize(
        self,
        lease: AllocatedWorkerLease | BoundWorkerLease,
        reason: str,
        capability: dict[str, Any],
    ) -> TerminalWorkerLease:
        if reason not in _TERMINAL_REASONS:
            raise ValueError("unsupported Worker terminal reason")
        key = self._key("worker-terminal", lease.resource_id, lease.correlation_id, str(lease.revision), reason)
        result = self.client.terminalize_worker(
            resource_id=lease.resource_id,
            correlation_id=lease.correlation_id,
            capability=capability,
            idempotency_key=key,
            expected_revision=lease.revision,
            reason={"code": reason},
        )
        return TerminalWorkerLease(
            task_id=lease.task_id,
            correlation_id=lease.correlation_id,
            resource_id=lease.resource_id,
            revision=result["revision"],
            reason=reason,
        )

    @staticmethod
    def _key(operation: str, *parts: str) -> str:
        material = "\x1f".join((operation, *parts)).encode("utf-8")
        return f"{operation}:{hashlib.sha256(material).hexdigest()[:40]}"

    @staticmethod
    def _validate_spec(spec: WorkerLeaseSpec) -> None:
        text_fields = (
            spec.task_id,
            spec.correlation_id,
            spec.expected_boot_id,
            spec.executable_class,
            spec.worktree_ref,
        )
        if any(not isinstance(value, str) or not value or "\x00" in value or len(value) > 4096 for value in text_fields):
            raise ValueError("bounded Worker lease specification required")
        if not isinstance(spec.expected_uid, int) or isinstance(spec.expected_uid, bool) or spec.expected_uid < 0:
            raise ValueError("nonnegative expected uid required")
        if not isinstance(spec.requested_operation, Mapping) or not spec.requested_operation:
            raise ValueError("requested operation required")
