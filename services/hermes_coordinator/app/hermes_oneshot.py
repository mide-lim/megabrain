from __future__ import annotations

import os
import signal
import stat
import subprocess
import threading
import time
from pathlib import Path
from typing import BinaryIO, Mapping, cast

from .config import PRIVATE_FILE_MODE, ensure_private_runtime_directory, write_runtime_profile
from .errors import ExecutionStatus, UsageError, UsageStatus
from .execution_guard import ExecutionGuard
from .models import ExecutionAdmission, ExecutionResult
from .usage import read_private_usage_file

MAX_TASK_PACKET_BYTES = 256 * 1024
MAX_CAPTURE_BYTES = 64 * 1024
DEFAULT_TERMINATION_GRACE_SECONDS = 1.0
SAFE_INHERITED_ENV_KEYS = ("PATH", "LANG", "LC_ALL", "TZ")


class _BoundedCapture(threading.Thread):
    def __init__(self, stream: BinaryIO, limit: int) -> None:
        super().__init__(daemon=True)
        self.stream = stream
        self.limit = limit
        self.buffer = bytearray()
        self.truncated = False

    def run(self) -> None:
        while chunk := self.stream.read(8192):
            remaining = self.limit - len(self.buffer)
            if remaining > 0:
                self.buffer.extend(chunk[:remaining])
            if len(chunk) > remaining:
                self.truncated = True

    def text(self) -> str:
        return bytes(self.buffer).decode("utf-8", errors="replace")


class HermesOneShotRunner:
    """Runs an admitted Hermes turn with external time and process-group bounds."""

    def __init__(
        self,
        runtime_dir: Path,
        *,
        hermes_executable: str = "hermes",
        environment: Mapping[str, str] | None = None,
        guard: ExecutionGuard | None = None,
        termination_grace_seconds: float = DEFAULT_TERMINATION_GRACE_SECONDS,
        hermes_home: Path | None = None,
    ) -> None:
        self.runtime_dir = Path(runtime_dir)
        self.hermes_executable = hermes_executable
        self.environment = dict(environment or {})
        self.guard = guard or ExecutionGuard()
        self.termination_grace_seconds = termination_grace_seconds
        self.hermes_home = None if hermes_home is None else Path(hermes_home)

    def build_argv(self, task_packet: str, usage_path: Path) -> list[str]:
        return [self.hermes_executable, "--oneshot", task_packet, "--usage-file", str(usage_path)]

    def run(self, admission: ExecutionAdmission | None, task_packet: str) -> ExecutionResult:
        decision = self.guard.evaluate(admission)
        if not decision.allowed:
            return ExecutionResult(status=decision.status)
        if not isinstance(task_packet, str) or len(task_packet.encode("utf-8")) > MAX_TASK_PACKET_BYTES:
            return ExecutionResult(status=ExecutionStatus.TASK_PACKET_TOO_LARGE)
        assert admission is not None
        try:
            runtime_dir = ensure_private_runtime_directory(self.runtime_dir)
            # Hermes max_turns bounds its loop iterations; reported api_calls are
            # post-run evidence and deliberately are not treated as equivalent.
            write_runtime_profile(runtime_dir, max_iterations=admission.max_iterations)
            usage_path = self._prepare_usage_path(runtime_dir, admission.usage_file_path)
        except (OSError, ValueError):
            return ExecutionResult(status=ExecutionStatus.INVALID_EXECUTION_CONFIG)

        environment = {
            key: value for key in SAFE_INHERITED_ENV_KEYS
            if (value := os.environ.get(key))
        }
        environment.update(self.environment)
        hermes_home = self.hermes_home or runtime_dir
        environment["HOME"] = str(hermes_home)
        environment["HERMES_HOME"] = str(hermes_home)
        started = time.monotonic()
        process: subprocess.Popen[bytes] | None = None
        stdout: _BoundedCapture | None = None
        stderr: _BoundedCapture | None = None
        timed_out = False
        interrupted = False
        termination_signal: str | None = None
        try:
            process = subprocess.Popen(
                self.build_argv(task_packet, usage_path),
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
                process.wait(timeout=admission.timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                termination_signal = self._terminate_group(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=self.termination_grace_seconds)
                except subprocess.TimeoutExpired:
                    termination_signal = self._terminate_group(process.pid, signal.SIGKILL)
                    process.wait(timeout=self.termination_grace_seconds)
            except KeyboardInterrupt:
                interrupted = True
                termination_signal = self._terminate_group(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=self.termination_grace_seconds)
                except subprocess.TimeoutExpired:
                    termination_signal = self._terminate_group(process.pid, signal.SIGKILL)
                    process.wait(timeout=self.termination_grace_seconds)
        except OSError:
            return ExecutionResult(status=ExecutionStatus.SPAWN_FAILED)
        finally:
            if stdout is not None:
                stdout.join(timeout=self.termination_grace_seconds)
            if stderr is not None:
                stderr.join(timeout=self.termination_grace_seconds)
        duration_ms = int((time.monotonic() - started) * 1000)
        assert process is not None
        captured_stdout = stdout.text() if stdout is not None else ""
        captured_stderr = stderr.text() if stderr is not None else ""
        usage_status = UsageStatus.VALID
        usage = None
        try:
            usage = read_private_usage_file(usage_path)
        except FileNotFoundError:
            usage_status = UsageStatus.MISSING
        except UsageError:
            usage_status = UsageStatus.MALFORMED
        status = self._status(
            exit_code=process.returncode,
            timed_out=timed_out,
            interrupted=interrupted,
            usage_status=usage_status,
            api_calls=None if usage is None else usage.total_api_calls,
            budget=admission.recommended_api_call_budget,
        )
        if termination_signal is None and process.returncode is not None and process.returncode < 0:
            termination_signal = signal.Signals(-process.returncode).name
        return ExecutionResult(
            status=status,
            exit_code=process.returncode,
            timed_out=timed_out,
            termination_signal=termination_signal,
            duration_ms=duration_ms,
            usage_status=usage_status,
            usage=usage,
            stdout=captured_stdout,
            stderr=captured_stderr,
            stdout_truncated=False if stdout is None else stdout.truncated,
            stderr_truncated=False if stderr is None else stderr.truncated,
            process_id=process.pid,
        )

    @staticmethod
    def _terminate_group(pid: int, sig: signal.Signals) -> str:
        try:
            os.killpg(pid, sig)
        except ProcessLookupError:
            pass
        return sig.name

    @staticmethod
    def _status(
        *,
        exit_code: int | None,
        timed_out: bool,
        interrupted: bool,
        usage_status: UsageStatus,
        api_calls: int | None,
        budget: int | None,
    ) -> ExecutionStatus:
        if interrupted:
            return ExecutionStatus.INTERRUPTED
        if timed_out:
            return ExecutionStatus.TIMEOUT
        if usage_status is UsageStatus.MISSING:
            return ExecutionStatus.USAGE_MISSING
        if usage_status is UsageStatus.MALFORMED:
            return ExecutionStatus.USAGE_MALFORMED
        if budget is not None and api_calls is not None and api_calls > budget:
            return ExecutionStatus.USAGE_BUDGET_EXCEEDED
        if exit_code != 0:
            return ExecutionStatus.PROCESS_FAILED
        return ExecutionStatus.COMPLETED

    @staticmethod
    def _prepare_usage_path(runtime_dir: Path, requested_path: str) -> Path:
        if not isinstance(requested_path, str) or not requested_path:
            raise ValueError("usage path is required")
        raw_path = Path(requested_path)
        if ".." in raw_path.parts:
            raise ValueError("usage path traversal")
        candidate = raw_path if raw_path.is_absolute() else runtime_dir / raw_path
        resolved = candidate.resolve(strict=False)
        try:
            resolved.relative_to(runtime_dir)
        except ValueError as exc:
            raise ValueError("usage path escapes runtime") from exc
        parent = resolved.parent
        relative_parent = parent.relative_to(runtime_dir)
        current = runtime_dir
        for part in relative_parent.parts:
            current = current / part
            try:
                metadata = os.lstat(current)
            except FileNotFoundError:
                current.mkdir(mode=0o700)
                os.chmod(current, 0o700)
                metadata = os.lstat(current)
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise ValueError("unsafe usage directory")
            if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) != 0o700:
                raise ValueError("usage directory is not private")
        try:
            existing = os.lstat(resolved)
        except FileNotFoundError:
            existing = None
        if existing is not None:
            raise ValueError("usage file already exists")
        fd = os.open(resolved, os.O_WRONLY | os.O_CREAT | os.O_EXCL, PRIVATE_FILE_MODE)
        try:
            os.fchmod(fd, PRIVATE_FILE_MODE)
        finally:
            os.close(fd)
        return resolved
