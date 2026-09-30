from __future__ import annotations

import os
import signal
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import BinaryIO, Callable, Mapping, cast

from .provider_classifier import (
    CHANNEL_PROVIDERS,
    ProviderObservation,
    ProviderObservationClassifier,
    ProviderState,
    ReasonCode,
    utc_rfc3339,
)
from .provider_usage import UsageParseError, UsageSchemaError, parse_hermes_usage_json

MAX_CAPTURE_BYTES = 64 * 1024
DEFAULT_TIMEOUT_SECONDS = 10.0
MAX_TIMEOUT_SECONDS = 30.0
DEFAULT_TERMINATION_GRACE_SECONDS = 1.0
SAFE_INHERITED_ENV_KEYS = ("PATH", "LANG", "LC_ALL", "TZ", "HOME", "HERMES_HOME")


class _BoundedCapture(threading.Thread):
    def __init__(self, stream: BinaryIO, limit: int) -> None:
        super().__init__(daemon=True)
        self.stream = stream
        self.limit = limit
        self.data = bytearray()
        self.truncated = False

    def run(self) -> None:
        while chunk := self.stream.read(8192):
            remaining = self.limit - len(self.data)
            if remaining > 0:
                self.data.extend(chunk[:remaining])
            if len(chunk) > remaining:
                self.truncated = True


@dataclass(frozen=True)
class ProbeExecution:
    exit_code: int | None
    timed_out: bool
    stdout: bytes
    stdout_truncated: bool
    stderr_truncated: bool
    spawn_failed: bool = False


class HermesUsageProbe:
    """Bounded read-only adapter for the Hermes account-usage command."""

    def __init__(
        self,
        *,
        hermes_executable: str = "hermes",
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        environment: Mapping[str, str] | None = None,
        termination_grace_seconds: float = DEFAULT_TERMINATION_GRACE_SECONDS,
    ) -> None:
        if isinstance(timeout_seconds, bool) or not 0 < timeout_seconds <= MAX_TIMEOUT_SECONDS:
            raise ValueError("timeout_seconds is outside conservative bounds")
        if isinstance(termination_grace_seconds, bool) or termination_grace_seconds <= 0:
            raise ValueError("termination_grace_seconds must be positive")
        if not isinstance(hermes_executable, str) or not hermes_executable:
            raise ValueError("hermes_executable is required")
        if any(not isinstance(key, str) or not isinstance(value, str) for key, value in (environment or {}).items()):
            raise ValueError("configured environment must contain strings")
        self.hermes_executable = hermes_executable
        self.timeout_seconds = float(timeout_seconds)
        self.environment = dict(environment or {})
        self.termination_grace_seconds = float(termination_grace_seconds)

    def build_argv(self, provider: str) -> list[str]:
        if provider not in CHANNEL_PROVIDERS.values():
            raise ValueError("provider is not explicitly supported")
        return [self.hermes_executable, "usage", "--provider", provider, "--json"]

    def execute(self, provider: str) -> ProbeExecution:
        environment = {key: value for key in SAFE_INHERITED_ENV_KEYS if (value := os.environ.get(key)) is not None}
        environment.update(self.environment)
        process: subprocess.Popen[bytes] | None = None
        stdout: _BoundedCapture | None = None
        stderr: _BoundedCapture | None = None
        timed_out = False
        try:
            process = subprocess.Popen(
                self.build_argv(provider),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
                shell=False,
                env=environment,
            )
            assert process.stdout is not None and process.stderr is not None
            stdout = _BoundedCapture(cast(BinaryIO, process.stdout), MAX_CAPTURE_BYTES)
            stderr = _BoundedCapture(cast(BinaryIO, process.stderr), MAX_CAPTURE_BYTES)
            stdout.start()
            stderr.start()
            try:
                process.wait(timeout=self.timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                self._terminate_group(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=self.termination_grace_seconds)
                except subprocess.TimeoutExpired:
                    self._terminate_group(process.pid, signal.SIGKILL)
                    process.wait(timeout=self.termination_grace_seconds)
        except OSError:
            return ProbeExecution(None, False, b"", False, False, spawn_failed=True)
        finally:
            if stdout is not None:
                stdout.join(timeout=self.termination_grace_seconds)
            if stderr is not None:
                stderr.join(timeout=self.termination_grace_seconds)
        assert process is not None
        return ProbeExecution(
            exit_code=process.returncode,
            timed_out=timed_out,
            stdout=b"" if stdout is None else bytes(stdout.data),
            stdout_truncated=False if stdout is None else stdout.truncated,
            stderr_truncated=False if stderr is None else stderr.truncated,
        )

    @staticmethod
    def _terminate_group(pid: int, sig: signal.Signals) -> None:
        try:
            os.killpg(pid, sig)
        except ProcessLookupError:
            pass


class ProviderObserver:
    def __init__(
        self,
        *,
        probe: HermesUsageProbe | None = None,
        classifier: ProviderObservationClassifier | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.probe = probe or HermesUsageProbe()
        self.classifier = classifier or ProviderObservationClassifier()
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def observe(self, channel_id: str) -> ProviderObservation:
        observed_at = self.clock()
        provider = CHANNEL_PROVIDERS.get(channel_id)
        if provider is None:
            return self.classifier.unknown(
                channel_id=channel_id,
                provider=None,
                observed_at=observed_at,
                probe_exit_code=None,
                reason_code=ReasonCode.PROVIDER_UNSUPPORTED,
            )
        execution = self.probe.execute(provider)
        if execution.timed_out:
            return self._probe_observation(
                channel_id=channel_id,
                provider=provider,
                observed_at=observed_at,
                state=ProviderState.TRANSIENT_FAILURE,
                reason_code=ReasonCode.PROBE_TIMEOUT,
                exit_code=execution.exit_code,
                timed_out=True,
            )
        if execution.spawn_failed:
            return self._probe_observation(
                channel_id=channel_id,
                provider=provider,
                observed_at=observed_at,
                state=ProviderState.TRANSIENT_FAILURE,
                reason_code=ReasonCode.PROBE_UNAVAILABLE,
                exit_code=None,
                timed_out=False,
            )
        if execution.stdout_truncated or execution.stderr_truncated:
            return self.classifier.unknown(
                channel_id=channel_id,
                provider=provider,
                observed_at=observed_at,
                probe_exit_code=execution.exit_code,
                reason_code=ReasonCode.PROBE_MALFORMED,
            )
        if execution.exit_code == 0:
            try:
                usage = parse_hermes_usage_json(execution.stdout)
            except UsageSchemaError:
                return self.classifier.unknown(
                    channel_id=channel_id,
                    provider=provider,
                    observed_at=observed_at,
                    probe_exit_code=0,
                    reason_code=ReasonCode.PROBE_SCHEMA_UNSUPPORTED,
                )
            except UsageParseError:
                return self.classifier.unknown(
                    channel_id=channel_id,
                    provider=provider,
                    observed_at=observed_at,
                    probe_exit_code=0,
                    reason_code=ReasonCode.PROBE_MALFORMED,
                )
            return self.classifier.classify(
                channel_id=channel_id,
                usage=usage,
                observed_at=observed_at,
                probe_exit_code=0,
            )
        return self.classifier.unknown(
            channel_id=channel_id,
            provider=provider,
            observed_at=observed_at,
            probe_exit_code=execution.exit_code,
            reason_code=ReasonCode.PROBE_UNAVAILABLE if execution.exit_code == 1 else ReasonCode.PROBE_NONZERO,
        )

    @staticmethod
    def _probe_observation(
        *,
        channel_id: str,
        provider: str,
        observed_at: datetime,
        state: ProviderState,
        reason_code: ReasonCode,
        exit_code: int | None,
        timed_out: bool,
    ) -> ProviderObservation:
        return ProviderObservation(
            channel_id=channel_id,
            provider=provider,
            state=state,
            observed_at=utc_rfc3339(observed_at),
            provider_fetched_at=None,
            reset_at=None,
            source=None,
            reason_code=reason_code,
            windows_summary=(),
            probe_exit_code=exit_code,
            timed_out=timed_out,
        )
