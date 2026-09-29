from __future__ import annotations

import json
from pathlib import Path

import pytest

from helpers import SERVICE_ROOT, admission, mode, runner, wait_for_gone
from app.config import ensure_private_runtime_directory
from app.errors import ExecutionStatus, UsageStatus
from app.hermes_oneshot import MAX_CAPTURE_BYTES, MAX_TASK_PACKET_BYTES


def test_argv_is_explicit_and_fake_hermes_is_the_only_executable(tmp_path: Path) -> None:
    instance, marker, _ = runner(tmp_path)
    expected = instance.build_argv("packet", tmp_path / "runtime" / "usage.json")

    result = instance.run(admission(), "packet")

    observed = json.loads(marker.read_text(encoding="utf-8"))
    assert expected == [str(tmp_path / "fake-hermes"), "--oneshot", "packet", "--usage-file", str(tmp_path / "runtime" / "usage.json")]
    assert observed[0] == str(tmp_path / "fake-hermes")
    assert observed[1:] == ["--oneshot", "packet", "--usage-file", str(tmp_path / "runtime" / "usage" / "corr-1.json")]
    assert result.status is ExecutionStatus.COMPLETED


def test_task_packet_size_is_checked_before_spawn(tmp_path: Path) -> None:
    instance, marker, _ = runner(tmp_path)

    result = instance.run(admission(), "x" * (MAX_TASK_PACKET_BYTES + 1))

    assert result.status is ExecutionStatus.TASK_PACKET_TOO_LARGE
    assert not marker.exists()


def test_runtime_profile_and_usage_file_are_private(tmp_path: Path) -> None:
    instance, _, _ = runner(tmp_path)

    result = instance.run(admission(), "packet")
    runtime = tmp_path / "runtime"

    assert result.status is ExecutionStatus.COMPLETED
    assert mode(runtime) == 0o700
    assert mode(runtime / "config.yaml") == 0o600
    assert mode(runtime / "usage" / "corr-1.json") == 0o600
    profile = (runtime / "config.yaml").read_text(encoding="utf-8")
    assert "max_turns: 7" in profile
    assert "platform_toolsets:\n  cli: []" in profile
    assert "background_review:\n    enabled: false" in profile


def test_repeated_turns_rewrite_profile_without_reusing_usage_file(tmp_path: Path) -> None:
    instance, _, _ = runner(tmp_path)

    first = instance.run(admission(), "packet-1")
    second = instance.run(
        admission(
            correlation_id="corr-2",
            max_iterations=8,
            usage_file_path="usage/corr-2.json",
        ),
        "packet-2",
    )

    assert first.status is ExecutionStatus.COMPLETED
    assert second.status is ExecutionStatus.COMPLETED
    profile = (tmp_path / "runtime" / "config.yaml").read_text(encoding="utf-8")
    assert "max_turns: 8" in profile
    assert (tmp_path / "runtime" / "usage" / "corr-1.json").exists()
    assert (tmp_path / "runtime" / "usage" / "corr-2.json").exists()


def test_host_environment_is_not_inherited(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MEGABRAIN_SHOULD_NOT_LEAK", "secret")
    instance, _, _ = runner(tmp_path)

    result = instance.run(admission(), "packet")

    assert result.status is ExecutionStatus.COMPLETED
    observed = json.loads((tmp_path / "env.json").read_text(encoding="utf-8"))
    assert "MEGABRAIN_SHOULD_NOT_LEAK" not in observed
    assert observed["HOME"] == str(tmp_path / "runtime")
    assert observed["HERMES_HOME"] == str(tmp_path / "runtime")


def test_interactive_hermes_config_and_production_path_are_untouched(tmp_path: Path, monkeypatch) -> None:
    interactive = tmp_path / "interactive"
    interactive.mkdir(mode=0o700)
    interactive_config = interactive / "config.yaml"
    interactive_config.write_text("interactive: true\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(interactive))
    production = Path("/var/lib/megabrain-hermes-coordinator/hermes-home")
    existed_before = production.exists()
    instance, _, _ = runner(tmp_path)

    result = instance.run(admission(), "packet")

    assert result.status is ExecutionStatus.COMPLETED
    assert interactive_config.read_text(encoding="utf-8") == "interactive: true\n"
    assert production.exists() is existed_before


def test_usage_missing_and_malformed_are_reported_after_execution(tmp_path: Path) -> None:
    missing, missing_marker, _ = runner(tmp_path / "missing", mode="missing")
    malformed, malformed_marker, _ = runner(tmp_path / "malformed", mode="malformed")

    missing_result = missing.run(admission(), "packet")
    malformed_result = malformed.run(admission(), "packet")

    assert missing_marker.exists() and malformed_marker.exists()
    assert missing_result.status is ExecutionStatus.USAGE_MISSING
    assert missing_result.usage_status is UsageStatus.MISSING
    assert malformed_result.status is ExecutionStatus.USAGE_MALFORMED
    assert malformed_result.usage_status is UsageStatus.MALFORMED


def test_api_call_overrun_is_post_execution_evidence(tmp_path: Path) -> None:
    instance, marker, _ = runner(tmp_path)

    result = instance.run(admission(recommended_api_call_budget=0), "packet")

    assert marker.exists()
    assert result.status is ExecutionStatus.USAGE_BUDGET_EXCEEDED
    assert result.usage is not None and result.usage.api_calls == 1


def test_auxiliary_api_calls_count_toward_post_run_budget(tmp_path: Path) -> None:
    instance, marker, _ = runner(tmp_path, mode="aux_overrun")

    result = instance.run(admission(recommended_api_call_budget=2), "packet")

    assert marker.exists()
    assert result.status is ExecutionStatus.USAGE_BUDGET_EXCEEDED
    assert result.usage is not None
    assert result.usage.api_calls == 1
    assert result.usage.total_api_calls == 3


def test_stdout_and_stderr_are_bounded(tmp_path: Path) -> None:
    instance, _, _ = runner(tmp_path, mode="output")

    result = instance.run(admission(), "packet")

    assert result.status is ExecutionStatus.COMPLETED
    assert len(result.stdout.encode("utf-8")) == MAX_CAPTURE_BYTES
    assert len(result.stderr.encode("utf-8")) == MAX_CAPTURE_BYTES
    assert result.stdout_truncated is True
    assert result.stderr_truncated is True


def test_timeout_terminates_process_group(tmp_path: Path) -> None:
    instance, _, pids = runner(tmp_path, mode="sleep")

    result = instance.run(admission(timeout_seconds=1), "packet")

    parent_pid = int(pids.read_text(encoding="utf-8").strip())
    assert result.status is ExecutionStatus.TIMEOUT
    assert result.timed_out is True
    assert result.termination_signal == "SIGTERM"
    assert wait_for_gone(parent_pid)


def test_sigterm_resistant_group_is_killed_without_descendants(tmp_path: Path) -> None:
    instance, _, pids = runner(tmp_path, mode="ignore_term")

    result = instance.run(admission(timeout_seconds=1), "packet")

    recorded = [int(pid) for pid in pids.read_text(encoding="utf-8").splitlines()]
    assert result.status is ExecutionStatus.TIMEOUT
    assert result.termination_signal == "SIGKILL"
    assert all(wait_for_gone(pid) for pid in recorded)


def test_spawn_failure_is_bounded_result(tmp_path: Path) -> None:
    from app.hermes_oneshot import HermesOneShotRunner

    instance = HermesOneShotRunner(tmp_path / "runtime", hermes_executable=str(tmp_path / "absent"))

    result = instance.run(admission(), "packet")

    assert result.status is ExecutionStatus.SPAWN_FAILED
    assert result.stdout == result.stderr == ""


def test_unsafe_usage_path_fails_closed_before_spawn(tmp_path: Path) -> None:
    instance, marker, _ = runner(tmp_path)

    result = instance.run(admission(usage_file_path="../outside.json"), "packet")

    assert result.status is ExecutionStatus.INVALID_EXECUTION_CONFIG
    assert not marker.exists()


def test_usage_path_rejects_symlink_escape_and_existing_file(tmp_path: Path) -> None:
    from app.hermes_oneshot import HermesOneShotRunner

    runtime = ensure_private_runtime_directory(tmp_path / "runtime")
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    (runtime / "escape").symlink_to(outside, target_is_directory=True)
    (runtime / "existing.json").write_text("unsafe", encoding="utf-8")
    instance, _, _ = runner(tmp_path / "fake")

    with pytest.raises(ValueError):
        instance._prepare_usage_path(runtime, "escape/usage.json")
    with pytest.raises(ValueError):
        instance._prepare_usage_path(runtime, "existing.json")
