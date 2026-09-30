"""Typed, read-only process-observation adapter contracts."""
from dataclasses import dataclass
from typing import Literal

Status = Literal["MATCHED", "MISSING", "IDENTITY_MISMATCH", "ACCESS_DENIED", "INCONCLUSIVE"]


@dataclass(frozen=True)
class ProcessObservation:
    pid: int
    start_time: str
    boot_id: str
    uid: int
    parent_pid: int
    process_group: int
    cwd: str
    executable: str
    cgroup: str | None
    status: Status


class ProcessAdapter:
    """Read bounded host evidence for an already allocated resource only."""

    def observe(self, resource_id: str) -> ProcessObservation:
        raise NotImplementedError
