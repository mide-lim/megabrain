import pytest

from app.adapters.docker import DockerObservation
from app.adapters.git_worktree import GitWorktreeObservation
from app.adapters.process import ProcessObservation
from app.adapters.security import SecurityObservation
from app.adapters.reconciliation import ExpectedResource, ObservedResource, reconcile


def test_adapter_contracts_are_typed_sanitized_and_denied_or_dirty_evidence_never_authorizes_mutation():
    assert ProcessObservation(1, "s", "b", None, None, None, None, None, None, "MATCHED").pid == 1
    assert DockerObservation(None, None, None, None, None, None, None, None, (), (), (), {}, "ACCESS_DENIED").status == "ACCESS_DENIED"
    assert SecurityObservation({}, {}, {}, "INCONCLUSIVE").status == "INCONCLUSIVE"
    git = GitWorktreeObservation("repo", "/task", "REGISTERED", "agent/x", "bad-head", "base", "DIRTY", "UNLOCKED", "IDENTITY_MISMATCH")
    expected = ExpectedResource("task", "rsrc", "WORKTREE", "ACTIVE", {}, None, False, None, "1.0.0")
    assert reconcile(expected, ObservedResource("git", "1", {"status": git.status}, "2026-09-29T00:00:00.000Z", "evidence:dirty")).result == "IDENTITY_MISMATCH"
    assert reconcile(expected, ObservedResource("docker", "1", {"status": "ACCESS_DENIED"}, "2026-09-29T00:00:00.000Z", "evidence:docker")).blocking_reason["code"] == "ADAPTER_UNAVAILABLE"
    assert reconcile(expected, ObservedResource("security", "1", {"status": "ACCESS_DENIED"}, "2026-09-29T00:00:00.000Z", "evidence:security")).blocking_reason["code"] == "ADAPTER_UNAVAILABLE"
