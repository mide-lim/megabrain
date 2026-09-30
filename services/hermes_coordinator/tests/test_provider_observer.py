from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import app.provider_observer as provider_observer_module
from helpers import SERVICE_ROOT
from app.provider_classifier import ProviderState, ReasonCode
from app.provider_observer import HermesUsageProbe, ProviderObserver


FAKE_USAGE_PROBE = """#!/usr/bin/env python3
import json
import os
import sys
import time
from pathlib import Path

mode = os.environ.get('FAKE_USAGE_MODE', 'normal')
marker = os.environ.get('FAKE_USAGE_MARKER')
env_dump = os.environ.get('FAKE_USAGE_ENV_DUMP')
if marker:
    Path(marker).write_text(json.dumps(sys.argv), encoding='utf-8')
if env_dump:
    Path(env_dump).write_text(json.dumps(dict(os.environ), sort_keys=True), encoding='utf-8')
if sys.argv[1:] != ['usage', '--provider', 'openai-codex', '--json']:
    sys.exit(91)
document = {
    'provider': 'openai-codex',
    'source': 'codex account usage',
    'title': 'Account limits',
    'plan': 'Pro',
    'fetched_at': '2026-09-29T12:00:00+00:00',
    'windows': [{'label': '5h', 'used_percent': 20, 'resets_at': '2026-09-29T18:00:00+00:00', 'detail': 'Account limit'}],
    'details': ['Usage is account-level evidence.'],
    'unavailable_reason': None,
}
if mode == 'malformed':
    sys.stdout.write('{')
elif mode == 'duplicate':
    sys.stdout.write(json.dumps(document).replace('"provider": "openai-codex"', '"provider": "openai-codex", "provider": "other"', 1))
elif mode == 'invalid_timestamp':
    document['fetched_at'] = 'not-a-timestamp'
    sys.stdout.write(json.dumps(document))
elif mode == 'negative_percent':
    document['windows'][0]['used_percent'] = -1
    sys.stdout.write(json.dumps(document))
elif mode == 'large_output':
    sys.stdout.write('x' * (70 * 1024))
elif mode == 'large_stderr':
    sys.stdout.write(json.dumps(document))
    sys.stderr.write('e' * (70 * 1024))
elif mode == 'timeout':
    time.sleep(60)
elif mode == 'exit_one':
    sys.stderr.write('No account usage available for provider openai-codex: no credential is configured, the provider has no usage endpoint, or the fetch failed.')
    sys.exit(1)
elif mode == 'nonzero':
    sys.stderr.write('provider command failed')
    sys.exit(7)
else:
    sys.stdout.write(json.dumps(document))
"""


def observer(tmp_path: Path, *, mode: str = "normal", timeout_seconds: float = 1.0) -> tuple[ProviderObserver, Path]:
    tmp_path.mkdir(mode=0o700, parents=True, exist_ok=True)
    executable = tmp_path / "fake-hermes"
    executable.write_text(FAKE_USAGE_PROBE, encoding="utf-8")
    executable.chmod(0o700)
    marker = tmp_path / "argv.json"
    probe = HermesUsageProbe(
        hermes_executable=str(executable),
        timeout_seconds=timeout_seconds,
        environment={
            "FAKE_USAGE_MODE": mode,
            "FAKE_USAGE_MARKER": str(marker),
            "FAKE_USAGE_ENV_DUMP": str(tmp_path / "environment.json"),
        },
        termination_grace_seconds=0.1,
    )
    return ProviderObserver(probe=probe, clock=lambda: datetime(2026, 9, 29, 12, 1, tzinfo=timezone.utc)), marker


def test_observer_invokes_only_the_exact_usage_argv(tmp_path: Path) -> None:
    instance, marker = observer(tmp_path)

    observation = instance.observe("openai_codex")

    assert observation.state is ProviderState.AVAILABLE
    assert json.loads(marker.read_text(encoding="utf-8")) == [
        str(tmp_path / "fake-hermes"), "usage", "--provider", "openai-codex", "--json"
    ]
    assert "--oneshot" not in json.loads(marker.read_text(encoding="utf-8"))


def test_ambiguous_exit_one_with_no_account_usage_message_is_not_auth_expired(tmp_path: Path) -> None:
    instance, _ = observer(tmp_path, mode="exit_one")

    observation = instance.observe("openai_codex")

    assert observation.state is ProviderState.UNKNOWN
    assert observation.state is not ProviderState.AUTH_EXPIRED
    assert observation.reason_code is ReasonCode.PROBE_UNAVAILABLE
    assert observation.probe_exit_code == 1


def test_timeout_is_a_transient_failure(tmp_path: Path) -> None:
    instance, _ = observer(tmp_path, mode="timeout")

    observation = instance.observe("openai_codex")

    assert observation.state is ProviderState.TRANSIENT_FAILURE
    assert observation.reason_code is ReasonCode.PROBE_TIMEOUT
    assert observation.timed_out is True


def test_malformed_or_invalid_usage_evidence_is_unknown(tmp_path: Path) -> None:
    for mode in ["malformed", "duplicate", "invalid_timestamp", "negative_percent", "large_output", "large_stderr"]:
        instance, _ = observer(tmp_path / mode, mode=mode)

        observation = instance.observe("openai_codex")

        assert observation.state is ProviderState.UNKNOWN
        assert observation.reason_code is ReasonCode.PROBE_MALFORMED


def test_ambiguous_nonzero_exit_is_unknown(tmp_path: Path) -> None:
    instance, _ = observer(tmp_path, mode="nonzero")

    observation = instance.observe("openai_codex")

    assert observation.state is ProviderState.UNKNOWN
    assert observation.reason_code is ReasonCode.PROBE_NONZERO
    assert observation.probe_exit_code == 7


def test_unknown_channel_does_not_spawn_a_provider_command(tmp_path: Path) -> None:
    instance, marker = observer(tmp_path)

    observation = instance.observe("untrusted_channel")

    assert observation.state is ProviderState.UNKNOWN
    assert observation.reason_code is ReasonCode.PROVIDER_UNSUPPORTED
    assert not marker.exists()


def test_parent_environment_is_not_leaked_to_fake_hermes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MEGABRAIN_SHOULD_NOT_LEAK", "secret")
    instance, _ = observer(tmp_path)

    observation = instance.observe("openai_codex")

    assert observation.state is ProviderState.AVAILABLE
    environment = json.loads((tmp_path / "environment.json").read_text(encoding="utf-8"))
    assert "MEGABRAIN_SHOULD_NOT_LEAK" not in environment


def test_probe_uses_shell_false_devnull_and_a_new_process_session(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def refusing_popen(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        raise OSError("no executable")

    monkeypatch.setattr(provider_observer_module.subprocess, "Popen", refusing_popen)
    result = HermesUsageProbe(hermes_executable="fake-hermes").execute("openai-codex")

    assert result.spawn_failed is True
    args = captured["args"]
    kwargs = captured["kwargs"]
    assert args == (["fake-hermes", "usage", "--provider", "openai-codex", "--json"],)
    assert isinstance(kwargs, dict)
    assert kwargs["shell"] is False
    assert kwargs["stdin"] is provider_observer_module.subprocess.DEVNULL
    assert kwargs["start_new_session"] is True


def test_probe_timeout_is_limited_to_thirty_seconds() -> None:
    try:
        HermesUsageProbe(timeout_seconds=30.1)
    except ValueError:
        return
    raise AssertionError("timeout above 30 seconds was accepted")
