from pathlib import Path

from helpers import SERVICE_ROOT  # noqa: F401
from app.config import write_runtime_profile


def test_runtime_profile_is_private_and_bounded(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    config_path = write_runtime_profile(runtime, max_iterations=7)

    assert config_path.read_text(encoding="utf-8") == (
        "agent:\n"
        "  max_turns: 7\n"
        "platform_toolsets:\n"
        "  cli: []\n"
        "auxiliary:\n"
        "  background_review:\n"
        "    enabled: false\n"
    )
    assert config_path.stat().st_mode & 0o777 == 0o600
    assert runtime.stat().st_mode & 0o777 == 0o700
