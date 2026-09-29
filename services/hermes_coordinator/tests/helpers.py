from __future__ import annotations

import os
import stat
import sys
import time
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

FAKE_HERMES = """#!/usr/bin/env python3
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

mode = os.environ.get('FAKE_HERMES_MODE', 'normal')
marker = os.environ.get('FAKE_HERMES_MARKER')
pids = os.environ.get('FAKE_HERMES_PIDS')
env_dump = os.environ.get('FAKE_HERMES_ENV_DUMP')
if marker:
    Path(marker).write_text(json.dumps(sys.argv), encoding='utf-8')
if env_dump:
    Path(env_dump).write_text(json.dumps(dict(os.environ), sort_keys=True), encoding='utf-8')
if pids:
    Path(pids).write_text(str(os.getpid()) + '\\n', encoding='utf-8')
if sys.argv[1:2] != ['--oneshot'] or len(sys.argv) != 5 or sys.argv[3] != '--usage-file':
    sys.exit(91)
usage = Path(sys.argv[4])
def report():
    return {
        'estimated_cost_usd': 0.01, 'cost_status': 'estimated', 'cost_source': 'fixture',
        'input_tokens': 2, 'output_tokens': 3, 'cache_read_tokens': 1, 'cache_write_tokens': 0,
        'reasoning_tokens': 0, 'total_tokens': 5, 'api_calls': 1, 'model': 'fake',
        'provider': 'test', 'session_id': 'sid', 'completed': True, 'partial': False,
        'interrupted': False, 'turn_exit_reason': 'stop', 'failed': False, 'service_tier': None,
        'auxiliary': {'api_calls': 0, 'input_tokens': 0, 'output_tokens': 0,
                      'cache_read_tokens': 0, 'cache_write_tokens': 0, 'reasoning_tokens': 0,
                      'estimated_cost_usd': 0, 'total_tokens': 0, 'by_task': {}},
        'total_including_auxiliary': {'estimated_cost_usd': 0.01, 'total_tokens': 5, 'api_calls': 1},
    }
def write_usage(value=None):
    usage.write_text(json.dumps(value or report()), encoding='utf-8')
if mode == 'missing':
    usage.unlink()
elif mode == 'malformed':
    usage.write_text('{', encoding='utf-8')
elif mode == 'negative':
    value = report(); value['api_calls'] = -1; write_usage(value)
elif mode == 'nonfinite':
    usage.write_text(json.dumps(report()).replace('"api_calls": 1', '"api_calls": NaN', 1), encoding='utf-8')
elif mode == 'aux_overrun':
    value = report()
    value['auxiliary']['api_calls'] = 2
    value['total_including_auxiliary']['api_calls'] = 3
    write_usage(value)
else:
    write_usage()
if mode == 'output':
    sys.stdout.write('o' * (70 * 1024))
    sys.stderr.write('e' * (70 * 1024))
    sys.stdout.flush()
    sys.stderr.flush()
if mode == 'fail':
    sys.exit(7)
if mode in {'sleep', 'ignore_term'}:
    if mode == 'ignore_term':
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        child = subprocess.Popen([sys.executable, '-c', 'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)'])
        if pids:
            with Path(pids).open('a', encoding='utf-8') as handle:
                handle.write(str(child.pid) + '\\n')
    time.sleep(60)
"""


def admission(**overrides: object):
    from app.models import ExecutionAdmission

    values: dict[str, object] = {
        "correlation_id": "corr-1",
        "task_id": "task-1",
        "decision": "ADMIT",
        "max_iterations": 7,
        "timeout_seconds": 2,
        "context_tokens": 1,
        "context_soft_limit": 80,
        "context_hard_limit": 120,
        "usage_file_path": "usage/corr-1.json",
        "recommended_api_call_budget": 2,
    }
    values.update(overrides)
    return ExecutionAdmission(**values)


def runner(tmp_path: Path, *, mode: str = "normal", grace: float = 0.15):
    from app.hermes_oneshot import HermesOneShotRunner

    tmp_path.mkdir(mode=0o700, parents=True, exist_ok=True)
    executable = tmp_path / "fake-hermes"
    executable.write_text(FAKE_HERMES, encoding="utf-8")
    executable.chmod(0o700)
    marker = tmp_path / "spawn.json"
    pids = tmp_path / "pids.txt"
    instance = HermesOneShotRunner(
        tmp_path / "runtime",
        hermes_executable=str(executable),
        environment={
            "FAKE_HERMES_MODE": mode,
            "FAKE_HERMES_MARKER": str(marker),
            "FAKE_HERMES_PIDS": str(pids),
            "FAKE_HERMES_ENV_DUMP": str(tmp_path / "env.json"),
        },
        termination_grace_seconds=grace,
    )
    return instance, marker, pids


def wait_for_gone(pid: int, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    proc = Path("/proc") / str(pid)
    while time.monotonic() < deadline:
        if not proc.exists():
            return True
        try:
            state = (proc / "stat").read_text(encoding="utf-8").split()[2]
        except FileNotFoundError:
            return True
        if state == "Z":
            return True
        time.sleep(0.02)
    return False


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)
