from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .errors import ExecutionStatus, UsageStatus


@dataclass(frozen=True)
class ExecutionAdmission:
    correlation_id: str
    task_id: str
    decision: str | None
    max_iterations: Any
    timeout_seconds: Any
    context_tokens: Any
    context_soft_limit: Any
    context_hard_limit: Any
    usage_file_path: str
    recommended_api_call_budget: Any = None


@dataclass(frozen=True)
class GuardDecision:
    allowed: bool
    status: ExecutionStatus


@dataclass(frozen=True)
class UsageEvidence:
    model: str | None
    provider: str | None
    api_calls: int | None
    input_tokens: int | None
    output_tokens: int | None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    reasoning_tokens: int | None = None
    total_tokens: int | None = None
    estimated_cost_usd: float | None = None
    total_api_calls: int | None = None
    completed: bool | None = None
    partial: bool | None = None
    interrupted: bool | None = None
    failed: bool = False
    turn_exit_reason: str | None = None


@dataclass(frozen=True)
class ExecutionResult:
    status: ExecutionStatus
    exit_code: int | None = None
    timed_out: bool = False
    termination_signal: str | None = None
    duration_ms: int = 0
    usage_status: UsageStatus = UsageStatus.NOT_RUN
    usage: UsageEvidence | None = None
    stdout: str = ""
    stderr: str = ""
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    process_id: int | None = None
