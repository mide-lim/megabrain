"""Persistent, bounded orchestration for independently admitted coordinator turns."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Callable, Protocol

from .control_plane_client import (
    ControlPlaneClientError,
    ControlPlaneProtocolError,
    ControlPlaneRemoteError,
    ControlPlaneUnavailableError,
)
from .coordinator_turn import CoordinatorTurnRunner
from .errors import ExecutionStatus
from .provider_classifier import ProviderObservation
from .provider_control_plane import ProviderObservationClient
from .provider_observer import ProviderObserver


class CoordinatorLifecycle(StrEnum):
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    READY = "READY"
    DEGRADED = "DEGRADED"
    STOPPING = "STOPPING"
    FAILED = "FAILED"


class CoordinatorActivity(StrEnum):
    IDLE = "IDLE"
    OBSERVING_PROVIDER = "OBSERVING_PROVIDER"
    RECORDING_OBSERVATION = "RECORDING_OBSERVATION"
    RUNNING_TURN = "RUNNING_TURN"


class WorkSource(Protocol):
    """External selector that supplies no more than one already-selected item."""

    def next_work(self) -> CoordinatorWorkItem | None: ...


class StopSignal(Protocol):
    def is_set(self) -> bool: ...

    def wait(self, timeout: float) -> bool: ...


@dataclass(frozen=True)
class CoordinatorWorkItem:
    task_id: str
    correlation_id: str
    channel_id: str
    task_packet: str = field(repr=False)
    observed_context_tokens: int
    max_iterations: int
    timeout_seconds: int
    usage_file_path: str
    recommended_api_call_budget: int | None
    coordinator_capability: Mapping[str, Any] = field(repr=False)
    observer_capability: Mapping[str, Any] = field(repr=False)

    def __post_init__(self) -> None:
        for value in (self.task_id, self.correlation_id, self.channel_id, self.task_packet, self.usage_file_path):
            if not isinstance(value, str) or not value:
                raise ValueError("bounded coordinator work identifiers and inputs are required")
        if not isinstance(self.observed_context_tokens, int) or isinstance(self.observed_context_tokens, bool) or self.observed_context_tokens < 0:
            raise ValueError("observed context tokens must be a non-negative integer")
        for value in (self.max_iterations, self.timeout_seconds):
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError("turn limits must be positive integers")
        if self.recommended_api_call_budget is not None and (
            not isinstance(self.recommended_api_call_budget, int)
            or isinstance(self.recommended_api_call_budget, bool)
            or self.recommended_api_call_budget <= 0
        ):
            raise ValueError("recommended API-call budget must be positive when set")
        if not isinstance(self.coordinator_capability, Mapping) or not isinstance(self.observer_capability, Mapping):
            raise ValueError("capabilities must be injected mappings")
        object.__setattr__(self, "coordinator_capability", _freeze_mapping(self.coordinator_capability))
        object.__setattr__(self, "observer_capability", _freeze_mapping(self.observer_capability))

    def coordinator_capability_payload(self) -> dict[str, Any]:
        return _mutable_mapping(self.coordinator_capability)

    def observer_capability_payload(self) -> dict[str, Any]:
        return _mutable_mapping(self.observer_capability)


@dataclass(frozen=True)
class CoordinatorCycleResult:
    status: str
    task_id: str | None = None


@dataclass(frozen=True)
class CoordinatorHealthSnapshot:
    state: CoordinatorLifecycle
    activity: CoordinatorActivity
    started_at: datetime | None
    last_cycle_at: datetime | None
    last_success_at: datetime | None
    heartbeat_at: datetime | None
    cycles_total: int
    cycles_failed: int
    last_task_id: str | None
    last_result_status: str | None
    consecutive_failures: int


class CoordinatorService:
    """Keeps the process alive while each coordinator model turn remains bounded."""

    def __init__(
        self,
        *,
        work_source: WorkSource,
        provider_observer: ProviderObserver,
        provider_observation_client: ProviderObservationClient,
        turn_runner: CoordinatorTurnRunner,
        idle_interval_seconds: float = 1.0,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if (
            not isinstance(idle_interval_seconds, (int, float))
            or isinstance(idle_interval_seconds, bool)
            or not 1.0 <= float(idle_interval_seconds) <= 5.0
        ):
            raise ValueError("idle interval must remain between one and five seconds")
        self.work_source = work_source
        self.provider_observer = provider_observer
        self.provider_observation_client = provider_observation_client
        self.turn_runner = turn_runner
        self.idle_interval_seconds = float(idle_interval_seconds)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._state = CoordinatorLifecycle.STOPPED
        self._activity = CoordinatorActivity.IDLE
        self._started_at: datetime | None = None
        self._last_cycle_at: datetime | None = None
        self._last_success_at: datetime | None = None
        self._heartbeat_at: datetime | None = None
        self._cycles_total = 0
        self._cycles_failed = 0
        self._last_task_id: str | None = None
        self._last_result_status: str | None = None
        self._consecutive_failures = 0

    def start(self) -> None:
        if self._state is CoordinatorLifecycle.STOPPED:
            now = self._now()
            self._state = CoordinatorLifecycle.STARTING
            self._started_at = now
            self._heartbeat_at = now
            self._state = CoordinatorLifecycle.READY
        elif self._state is CoordinatorLifecycle.FAILED:
            raise RuntimeError("a failed coordinator requires replacement")

    def request_stop(self) -> None:
        if self._state in {CoordinatorLifecycle.STARTING, CoordinatorLifecycle.READY, CoordinatorLifecycle.DEGRADED}:
            self._state = CoordinatorLifecycle.STOPPING
            self._activity = CoordinatorActivity.IDLE
            self._heartbeat_at = self._now()

    def run_cycle(self) -> CoordinatorCycleResult:
        if self._state is CoordinatorLifecycle.STOPPED:
            raise RuntimeError("start the coordinator before running a cycle")
        if self._state is CoordinatorLifecycle.STOPPING:
            return CoordinatorCycleResult("STOPPING")
        if self._state is CoordinatorLifecycle.FAILED:
            return CoordinatorCycleResult("FAILED")

        self._begin_cycle()
        try:
            work_item = self.work_source.next_work()
        except Exception:
            return self._recover("WORK_SOURCE_FAILED")
        if work_item is None:
            return self._succeed("IDLE")
        if not isinstance(work_item, CoordinatorWorkItem):
            return self._fatal("INVALID_WORK_ITEM")

        self._last_task_id = work_item.task_id
        self._activity = CoordinatorActivity.OBSERVING_PROVIDER
        try:
            observation = self.provider_observer.observe(work_item.channel_id)
        except Exception:
            return self._recover("PROVIDER_OBSERVATION_FAILED", work_item.task_id)
        if not isinstance(observation, ProviderObservation):
            return self._fatal("INVALID_PROVIDER_OBSERVATION", work_item.task_id)

        self._activity = CoordinatorActivity.RECORDING_OBSERVATION
        try:
            self.provider_observation_client.record_provider_observation(
                observation,
                work_item.correlation_id,
                work_item.observer_capability_payload(),
                idempotency_key=self._observation_key(work_item),
            )
        except ControlPlaneUnavailableError:
            return self._recover(ExecutionStatus.CONTROL_PLANE_UNAVAILABLE.value, work_item.task_id)
        except ControlPlaneRemoteError:
            return self._recover(ExecutionStatus.CONTROL_PLANE_UNAUTHORIZED.value, work_item.task_id)
        except (ControlPlaneProtocolError, ControlPlaneClientError):
            return self._recover(ExecutionStatus.CONTROL_PLANE_PROTOCOL_ERROR.value, work_item.task_id)
        except (TypeError, ValueError):
            return self._fatal("INVALID_OBSERVATION_CONFIGURATION", work_item.task_id)
        except Exception:
            return self._recover("OBSERVATION_RECORD_FAILED", work_item.task_id)

        self._activity = CoordinatorActivity.RUNNING_TURN
        try:
            result = self.turn_runner.run(
                task_id=work_item.task_id,
                correlation_id=work_item.correlation_id,
                channel_id=work_item.channel_id,
                observed_context_tokens=work_item.observed_context_tokens,
                max_iterations=work_item.max_iterations,
                timeout_seconds=work_item.timeout_seconds,
                usage_file_path=work_item.usage_file_path,
                recommended_api_call_budget=work_item.recommended_api_call_budget,
                capability=work_item.coordinator_capability_payload(),
                task_packet=work_item.task_packet,
                admission_idempotency_key=self._admission_key(work_item),
            )
        except (TypeError, ValueError):
            return self._fatal("INVALID_TURN_CONFIGURATION", work_item.task_id)
        except Exception:
            return self._recover("COORDINATOR_TURN_FAILED", work_item.task_id)

        status = result.status.value
        if result.status in {
            ExecutionStatus.CONTROL_PLANE_UNAVAILABLE,
            ExecutionStatus.CONTROL_PLANE_PROTOCOL_ERROR,
            ExecutionStatus.CONTROL_PLANE_UNAUTHORIZED,
        }:
            return self._recover(status, work_item.task_id)
        return self._succeed(status, work_item.task_id)

    def run_forever(self, stop_event: StopSignal) -> None:
        if self._state is CoordinatorLifecycle.STOPPED:
            self.start()
        while self._state in {CoordinatorLifecycle.READY, CoordinatorLifecycle.DEGRADED} and not stop_event.is_set():
            self.run_cycle()
            if self._state not in {CoordinatorLifecycle.READY, CoordinatorLifecycle.DEGRADED} or stop_event.wait(self.idle_interval_seconds):
                break
        if stop_event.is_set() or self._state is CoordinatorLifecycle.STOPPING:
            self.request_stop()
            self._state = CoordinatorLifecycle.STOPPED
            self._activity = CoordinatorActivity.IDLE
            self._heartbeat_at = self._now()

    def health_snapshot(self) -> CoordinatorHealthSnapshot:
        return CoordinatorHealthSnapshot(
            state=self._state,
            activity=self._activity,
            started_at=self._started_at,
            last_cycle_at=self._last_cycle_at,
            last_success_at=self._last_success_at,
            heartbeat_at=self._heartbeat_at,
            cycles_total=self._cycles_total,
            cycles_failed=self._cycles_failed,
            last_task_id=self._last_task_id,
            last_result_status=self._last_result_status,
            consecutive_failures=self._consecutive_failures,
        )

    def _begin_cycle(self) -> None:
        now = self._now()
        self._cycles_total += 1
        self._last_cycle_at = now
        self._heartbeat_at = now
        self._activity = CoordinatorActivity.IDLE

    def _succeed(self, status: str, task_id: str | None = None) -> CoordinatorCycleResult:
        now = self._now()
        self._state = CoordinatorLifecycle.READY
        self._activity = CoordinatorActivity.IDLE
        self._heartbeat_at = now
        self._last_success_at = now
        self._last_result_status = status
        self._consecutive_failures = 0
        return CoordinatorCycleResult(status, task_id)

    def _recover(self, status: str, task_id: str | None = None) -> CoordinatorCycleResult:
        self._state = CoordinatorLifecycle.DEGRADED
        self._activity = CoordinatorActivity.IDLE
        self._heartbeat_at = self._now()
        self._cycles_failed += 1
        self._last_result_status = status
        self._consecutive_failures += 1
        return CoordinatorCycleResult(status, task_id)

    def _fatal(self, status: str, task_id: str | None = None) -> CoordinatorCycleResult:
        self._state = CoordinatorLifecycle.FAILED
        self._activity = CoordinatorActivity.IDLE
        self._heartbeat_at = self._now()
        self._cycles_failed += 1
        self._last_result_status = status
        self._consecutive_failures += 1
        return CoordinatorCycleResult(status, task_id)

    def _now(self) -> datetime:
        value = self.clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("coordinator clock must return an offset-aware datetime")
        return value.astimezone(timezone.utc)

    def _observation_key(self, work_item: CoordinatorWorkItem) -> str:
        return f"coordinator-provider-observation:{work_item.task_id}:{work_item.correlation_id}:{self._cycles_total}"

    def _admission_key(self, work_item: CoordinatorWorkItem) -> str:
        return f"coordinator-model-call:{work_item.task_id}:{work_item.correlation_id}:{self._cycles_total}"


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType({key: _freeze_value(item) for key, item in value.items()})


def _freeze_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _freeze_mapping(value)
    if isinstance(value, list):
        return tuple(_freeze_value(item) for item in value)
    return value


def _mutable_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    return {key: _mutable_value(item) for key, item in value.items()}


def _mutable_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _mutable_mapping(value)
    if isinstance(value, tuple):
        return [_mutable_value(item) for item in value]
    return value
