#!/usr/bin/env python3
"""Human-only bootstrap for fixed inert GitHub App runtime configuration."""
from __future__ import annotations

import argparse
import getpass
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any, TextIO


class BootstrapError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _load_runtime() -> Any:
    path = Path(__file__).with_name("github_app_runtime_config.py")
    specification = importlib.util.spec_from_file_location("megabrain_runtime_config", path)
    if specification is None or specification.loader is None:
        raise BootstrapError("runtime_loader_unavailable")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


RUNTIME = _load_runtime()


def _result() -> dict[str, object]:
    return {"status": "failed", "failure_code": None, "config_written": False}


def _payload(app_id: str, installation_id: str) -> bytes:
    if not app_id.isdecimal() or not installation_id.isdecimal():
        raise BootstrapError("bootstrap_identifier_rejected")
    return (
        f"github_app_id={app_id}\n"
        f"github_app_installation_id={installation_id}\n"
        f"private_key_path={RUNTIME.APPROVED_KEY_PATH}\n"
    ).encode("utf-8")


def run_bootstrap(*, replace: bool = False, stdin: TextIO | None = None, stdout: TextIO | None = None) -> dict[str, object]:
    """Create the one fixed file only from a local interactive TTY."""
    result = _result()
    input_stream = sys.stdin if stdin is None else stdin
    output_stream = sys.stdout if stdout is None else stdout
    if not input_stream.isatty() or not output_stream.isatty():
        result["failure_code"] = "bootstrap_tty_required"
        return result
    if replace:
        result["failure_code"] = "bootstrap_replacement_requires_human_maintenance"
        return result
    try:
        uid, gid = RUNTIME._identity()
        RUNTIME._validate_parent_chain(RUNTIME.CONFIG_PATH, uid, gid)
        RUNTIME._validate_key(uid, gid, str(RUNTIME.APPROVED_KEY_PATH))
        app_id = getpass.getpass("GitHub App ID: ", stream=output_stream)
        installation_id = getpass.getpass("GitHub App installation ID: ", stream=output_stream)
        payload = _payload(app_id, installation_id)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(RUNTIME.CONFIG_PATH, flags, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            os.write(descriptor, payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        directory = os.open(RUNTIME.CONFIG_PATH.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        RUNTIME.load_runtime_config()
        result["config_written"] = True
        result["status"] = "ok"
    except FileExistsError:
        result["failure_code"] = "bootstrap_config_exists"
    except BootstrapError as exc:
        result["failure_code"] = exc.code
    except RUNTIME.RuntimeConfigError as exc:
        result["failure_code"] = exc.code
    except OSError:
        result["failure_code"] = "bootstrap_write_rejected"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Create the fixed protected GitHub App runtime configuration.")
    parser.add_argument("--replace", action="store_true")
    arguments = parser.parse_args()
    result = run_bootstrap(replace=arguments.replace)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
