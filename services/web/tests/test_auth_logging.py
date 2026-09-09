from __future__ import annotations

import ast
import json
from pathlib import Path


WEB_ROOT = Path(__file__).resolve().parents[1]
AUTH_SOURCE_DIR = WEB_ROOT / "app" / "auth"
SENSITIVE_VALUE_NAMES = {
    "access_token",
    "authorization_code",
    "client_secret",
    "code",
    "id_token",
    "nonce",
    "pkce_verifier",
    "raw_session_token",
    "raw_token",
    "refresh_token",
    "session_token",
    "state",
    "token_response",
}
LOG_METHODS = {"critical", "debug", "error", "exception", "info", "log", "warning"}


def _source_trees() -> list[tuple[Path, ast.Module]]:
    return [
        (path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        for path in sorted(AUTH_SOURCE_DIR.glob("*.py"))
    ]


def _is_logging_sink(call: ast.Call) -> bool:
    if isinstance(call.func, ast.Name):
        return call.func.id == "print"
    return isinstance(call.func, ast.Attribute) and call.func.attr in LOG_METHODS


def _contains_sensitive_value(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and child.id in SENSITIVE_VALUE_NAMES:
            return True
        if isinstance(child, ast.Attribute) and child.attr in SENSITIVE_VALUE_NAMES:
            return True
        if isinstance(child, ast.Attribute) and child.attr == "query_params":
            return True
        if isinstance(child, ast.Attribute) and child.attr == "cookies":
            return True
    return False


def test_production_uvicorn_command_disables_access_logging() -> None:
    dockerfile = (WEB_ROOT / "Dockerfile").read_text(encoding="utf-8")
    command_line = next(line for line in dockerfile.splitlines() if line.startswith("CMD "))
    command = json.loads(command_line.removeprefix("CMD "))

    assert command[:2] == ["uvicorn", "app.main:app"]
    assert "--no-access-log" in command


def test_auth_logging_sinks_exclude_callback_and_credential_values() -> None:
    violations: list[str] = []

    for path, tree in _source_trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _is_logging_sink(node):
                if _contains_sensitive_value(node):
                    violations.append(f"{path.name}:{node.lineno}")

    assert violations == []
