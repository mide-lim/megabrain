import pytest

from app.control_plane_client import ControlPlaneRemoteError
from app.lease_lifecycle import (
    BoundWorkerLease,
    WorkerLeaseLifecycle,
    WorkerLeaseSpec,
)


CAPABILITY = {"opaque": "test-capability"}
NONCE = "FAKE_TC8C_LAUNCH_NONCE_SENTINEL_" + ("A" * 32)


class SpyClient:
    def __init__(self):
        self.calls = []
        self.fail_allocate = False
        self.fail_bind = False

    def allocate_worker(self, **kwargs):
        self.calls.append(("allocate", kwargs))
        if self.fail_allocate:
            raise ControlPlaneRemoteError("RESOURCE_LIMIT_REACHED")
        return {"resource_id": "rsrc_test", "revision": 0, "state": "ALLOCATED"}

    def bind_worker(self, **kwargs):
        self.calls.append(("bind", kwargs))
        if self.fail_bind:
            raise ControlPlaneRemoteError("IDENTITY_BIND_FAILED")
        return {"resource_id": kwargs["resource_id"], "revision": kwargs["expected_revision"] + 1, "state": "ACTIVE"}

    def terminalize_worker(self, **kwargs):
        self.calls.append(("terminal", kwargs))
        return {"resource_id": kwargs["resource_id"], "revision": kwargs["expected_revision"] + 1, "state": "TERMINAL"}


def spec():
    return WorkerLeaseSpec(
        task_id="task_018f3d4a-7b8c-7c9d-8e1f-0123456789ab",
        correlation_id="corr_018f3d4a-7b8c-7c9d-8e1f-0123456789ac",
        requested_operation={"operation": "worker.run", "target_scope": "task-worktree"},
        expected_boot_id="018f3d4a-7b8c-7c9d-8e1f-0123456789ad",
        expected_uid=1000,
        executable_class="fake-worker-v1",
        worktree_ref="/fake/worktree",
    )


def observation():
    return {
        "pid": 101,
        "start_time": "500",
        "boot_id": spec().expected_boot_id,
        "uid": 1000,
        "parent_pid": 1,
        "process_group": 101,
        "cwd": "/fake/worktree",
        "executable": "/fake/bin/worker",
        "cgroup": None,
    }


def test_prepare_allocation_generates_nonce_once_and_retry_is_stable():
    count = 0

    def nonce_factory():
        nonlocal count
        count += 1
        return NONCE

    client = SpyClient()
    lifecycle = WorkerLeaseLifecycle(client, nonce_factory=nonce_factory)
    intent = lifecycle.prepare_allocation(spec())

    assert count == 1
    assert NONCE not in repr(intent)
    first = lifecycle.allocate(intent, CAPABILITY)
    second = lifecycle.allocate(intent, CAPABILITY)

    assert count == 1
    assert first.resource_id == second.resource_id == "rsrc_test"
    allocate_calls = [call for kind, call in client.calls if kind == "allocate"]
    assert allocate_calls[0]["idempotency_key"] == allocate_calls[1]["idempotency_key"]
    assert allocate_calls[0]["expectation"] == allocate_calls[1]["expectation"]
    assert "launch_nonce" not in allocate_calls[0]["expectation"]
    assert NONCE not in repr(first)


def test_bind_passes_transient_nonce_and_returns_nonce_free_bound_handle():
    client = SpyClient()
    lifecycle = WorkerLeaseLifecycle(client, nonce_factory=lambda: NONCE)
    allocated = lifecycle.allocate(lifecycle.prepare_allocation(spec()), CAPABILITY)

    bound = lifecycle.bind(allocated, observation(), CAPABILITY)

    assert isinstance(bound, BoundWorkerLease)
    assert bound.revision == 1
    assert not hasattr(bound, "launch_nonce")
    bind_call = [call for kind, call in client.calls if kind == "bind"][0]
    assert bind_call["launch_nonce"] == NONCE
    assert bind_call["expected_revision"] == 0


def test_bind_failure_does_not_terminalize_or_invent_active_state():
    client = SpyClient()
    client.fail_bind = True
    lifecycle = WorkerLeaseLifecycle(client, nonce_factory=lambda: NONCE)
    allocated = lifecycle.allocate(lifecycle.prepare_allocation(spec()), CAPABILITY)

    with pytest.raises(ControlPlaneRemoteError, match="IDENTITY_BIND_FAILED"):
        lifecycle.bind(allocated, observation(), CAPABILITY)

    assert [kind for kind, _ in client.calls] == ["allocate", "bind"]


def test_allocation_failure_produces_no_fake_lease():
    client = SpyClient()
    client.fail_allocate = True
    lifecycle = WorkerLeaseLifecycle(client, nonce_factory=lambda: NONCE)
    intent = lifecycle.prepare_allocation(spec())

    with pytest.raises(ControlPlaneRemoteError, match="RESOURCE_LIMIT_REACHED"):
        lifecycle.allocate(intent, CAPABILITY)

    assert [kind for kind, _ in client.calls] == ["allocate"]


def test_explicit_terminalization_for_allocated_and_bound_leases_is_revisioned_and_idempotent():
    client = SpyClient()
    lifecycle = WorkerLeaseLifecycle(client, nonce_factory=lambda: NONCE)
    allocated = lifecycle.allocate(lifecycle.prepare_allocation(spec()), CAPABILITY)

    terminal_allocated = lifecycle.terminalize(allocated, "RESOURCE_CREATION_FAILED", CAPABILITY)
    terminal_allocated_retry = lifecycle.terminalize(allocated, "RESOURCE_CREATION_FAILED", CAPABILITY)
    assert terminal_allocated == terminal_allocated_retry
    terminal_calls = [call for kind, call in client.calls if kind == "terminal"]
    assert terminal_calls[0]["expected_revision"] == 0
    assert terminal_calls[0]["idempotency_key"] == terminal_calls[1]["idempotency_key"]

    bound = lifecycle.bind(allocated, observation(), CAPABILITY)
    terminal_bound = lifecycle.terminalize(bound, "COMPLETED", CAPABILITY)
    assert terminal_bound.revision == 2
    assert [call for kind, call in client.calls if kind == "terminal"][-1]["expected_revision"] == 1


def test_invalid_spec_nonce_and_terminal_reason_fail_before_control_plane_call():
    client = SpyClient()
    bad = spec()
    bad = WorkerLeaseSpec(**{**bad.__dict__, "expected_uid": -1})
    with pytest.raises(ValueError):
        WorkerLeaseLifecycle(client, nonce_factory=lambda: NONCE).prepare_allocation(bad)
    with pytest.raises(ValueError):
        WorkerLeaseLifecycle(client, nonce_factory=lambda: "short").prepare_allocation(spec())

    lifecycle = WorkerLeaseLifecycle(client, nonce_factory=lambda: NONCE)
    allocated = lifecycle.allocate(lifecycle.prepare_allocation(spec()), CAPABILITY)
    before = len(client.calls)
    with pytest.raises(ValueError):
        lifecycle.terminalize(allocated, "DELETE_EVERYTHING", CAPABILITY)
    assert len(client.calls) == before
