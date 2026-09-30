"""Coordinator-side systemd bootstrap reader and short-lived capability binding."""
from __future__ import annotations

import json
import os
import stat
from dataclasses import replace
from pathlib import Path

from .coordinator_service import CoordinatorWorkItem, WorkSource

_MAX_CREDENTIAL_BYTES = 4096


def _read_credential(path: Path) -> bytes:
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > _MAX_CREDENTIAL_BYTES: raise ValueError
            value = os.read(fd, _MAX_CREDENTIAL_BYTES + 1)
            if len(value) > _MAX_CREDENTIAL_BYTES: raise ValueError
            return value
        finally: os.close(fd)
    except (OSError, ValueError) as exc:
        raise RuntimeError("production bootstrap credential unavailable") from exc


def _bootstrap(directory: Path) -> tuple[str, str]:
    try:
        value = json.loads(_read_credential(directory / "control-plane-coordinator-bootstrap").decode("utf-8"))
        if not isinstance(value, dict) or set(value) != {"version", "bootstrap_id", "secret"} or value["version"] != 1 or not isinstance(value["bootstrap_id"], str) or not value["bootstrap_id"] or not isinstance(value["secret"], str) or len(value["secret"]) < 32:
            raise ValueError
        return value["bootstrap_id"], value["secret"]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("production bootstrap credential unavailable") from exc


class IdleWorkSource:
    """Production-safe source until later control-plane task discovery exists."""
    def next_work(self) -> None: return None


class _BoundWorkSource:
    def __init__(self, source: WorkSource, provider: "ProductionCapabilityProvider") -> None: self._source, self._provider = source, provider
    def __repr__(self) -> str: return "<BoundProductionWorkSource>"
    def next_work(self) -> CoordinatorWorkItem | None:
        work = self._source.next_work()
        if work is None: return None
        if not isinstance(work, CoordinatorWorkItem): raise RuntimeError("invalid selected work item")
        capabilities = self._provider._exchange(work)
        if not isinstance(capabilities, dict) or set(capabilities) != {"coordinator_capability", "observer_capability"} or not all(isinstance(capabilities[key], dict) for key in capabilities):
            raise RuntimeError("invalid production capability exchange")
        return replace(work, coordinator_capability=capabilities["coordinator_capability"], observer_capability=capabilities["observer_capability"])


class ProductionCapabilityProvider:
    """Binds each selected work item through the sole bootstrap UDS operation."""
    def __init__(self, transport, *, credential_directory: str | Path | None = None) -> None:
        directory = Path(credential_directory) if credential_directory is not None else Path(os.environ.get("CREDENTIALS_DIRECTORY", ""))
        if not str(directory): raise RuntimeError("production bootstrap credential unavailable")
        self._transport, self._bootstrap_id, self._secret = transport, *_bootstrap(directory)
    def __repr__(self) -> str: return "<ProductionCapabilityProvider>"
    def bind(self, work_source: WorkSource) -> WorkSource: return _BoundWorkSource(work_source, self)
    def _exchange(self, work: CoordinatorWorkItem) -> dict:
        return self._transport.exchange_coordinator_bootstrap(bootstrap_id=self._bootstrap_id, bootstrap_secret=self._secret, task_id=work.task_id, channel_id=work.channel_id, correlation_id=work.correlation_id)
