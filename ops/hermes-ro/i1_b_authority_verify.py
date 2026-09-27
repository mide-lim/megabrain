#!/usr/bin/env python3
"""Single-purpose F6 I1-B authority-verifier launcher source.

This file is source only. A future human-authorized installer places it at the
root-owned runtime path. Its public CLI accepts no arguments.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from typing import Callable, Mapping, Sequence


OPERATION_NAME = "i1-b-authority-verify"
CONTAINER_NAME = "megabrain-postgres"
RUNTIME_VERIFIER_PATH = Path(
    "/usr/local/lib/megabrain-hermes-ro/i1-b/"
    "008_i1_b_web_applicable_enrichment_read_verify.sql"
)
EXPECTED_VERIFIER_BLOB = "b6651e8e9136bcd11faa4912e39df1c8c0099a22"
EXPECTED_VERIFIER_MODE = 0o600
MAX_OUTPUT_BYTES = 16_384
AUDIT_LOG_PATH = Path("/var/log/megabrain-hermes-ro/i1-b-authority-verify.log")

# This constant shell fragment only expands POSTGRES_USER and POSTGRES_DB from
# the container's existing environment. It receives no caller-provided input.
FIXED_DOCKER_COMMAND = [
    "/usr/bin/docker",
    "exec",
    "-i",
    "--user",
    "postgres",
    CONTAINER_NAME,
    "/bin/sh",
    "-c",
    'exec psql -q -X --no-password -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"',
]
SANITIZED_ENV = {
    "HOME": "/nonexistent",
    "LANG": "C",
    "LC_ALL": "C",
    "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
}

CHECK_EXPECTATIONS = {
    "WEB_I1_B_CAN_READ_APPLICABLE_ENRICHMENT_TUPLE": True,
    "WEB_I1_B_CAN_READ_REEL_SOURCE_SHA256": True,
    "WEB_I1_B_CANNOT_ACCESS_ENRICHMENT_ATTEMPTS": True,
    "WEB_I1_B_CANNOT_USE_ENRICHMENT_RESULT_SEQUENCE": True,
    "WEB_I1_B_CANNOT_WRITE_ENRICHMENTS": True,
    "WEB_I1_B_EFFECTIVE_ENRICHMENT_SELECT_ALLOWLIST": True,
    "WEB_I1_B_EFFECTIVE_REEL_SELECT_ALLOWLIST": True,
    "WEB_I1_B_ENRICHMENTS_TABLE_WIDE_SELECT": False,
    "WEB_I1_B_NO_UNEXPECTED_PUBLIC_AUTHORITY": True,
    "WEB_I1_B_NO_UNEXPECTED_ROLE_MEMBERSHIPS": True,
    "WEB_I1_B_REELS_TABLE_WIDE_SELECT": False,
    "WEB_I1_B_SCHEMA_CREATE": False,
    "WEB_I1_B_SCHEMA_USAGE": True,
}


@dataclass(frozen=True)
class ChildResult:
    returncode: int
    stdout: bytes
    stderr: bytes


@dataclass(frozen=True)
class LaunchResult:
    exit_code: int
    result_class: str
    output: str


@dataclass(frozen=True)
class VerifierMetadata:
    mode: int
    uid: int
    gid: int


Runner = Callable[[list[str], bytes, dict[str, str]], ChildResult]
AuditWriter = Callable[[Mapping[str, object]], bool]


def git_blob_sha1(contents: bytes) -> str:
    """Return the canonical SHA-1 Git blob identifier for bytes."""
    prefix = f"blob {len(contents)}\0".encode("ascii")
    return hashlib.sha1(prefix + contents).hexdigest()


def validate_verifier_bytes(contents: bytes, metadata: VerifierMetadata) -> bytes:
    if not stat.S_ISREG(metadata.mode):
        raise ValueError("runtime verifier is not a regular file")
    if metadata.uid != 0 or metadata.gid != 0:
        raise ValueError("runtime verifier ownership is invalid")
    if stat.S_IMODE(metadata.mode) != EXPECTED_VERIFIER_MODE:
        raise ValueError("runtime verifier mode is invalid")
    if git_blob_sha1(contents) != EXPECTED_VERIFIER_BLOB:
        raise ValueError("runtime verifier blob identity is invalid")
    return contents


def _read_runtime_verifier(path: Path = RUNTIME_VERIFIER_PATH) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError("runtime verifier is unavailable") from exc
    try:
        metadata = os.fstat(descriptor)
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 65_536)
            if not chunk:
                break
            chunks.append(chunk)
        return validate_verifier_bytes(
            b"".join(chunks),
            VerifierMetadata(metadata.st_mode, metadata.st_uid, metadata.st_gid),
        )
    finally:
        os.close(descriptor)


def _build_psql_input(verifier_bytes: bytes) -> bytes:
    return b"BEGIN TRANSACTION READ ONLY;\n" + verifier_bytes + b"\nROLLBACK;\n"


def _subprocess_runner(command: list[str], payload: bytes, environment: dict[str, str]) -> ChildResult:
    completed = subprocess.run(
        command,
        input=payload,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
        check=False,
        shell=False,
        timeout=30,
    )
    return ChildResult(completed.returncode, completed.stdout, completed.stderr)


def _parse_bool(value: str) -> bool | None:
    if value == "t":
        return True
    if value == "f":
        return False
    return None


def _parse_verifier_report(stdout: bytes) -> tuple[dict[str, bool], str] | None:
    if len(stdout) > MAX_OUTPUT_BYTES:
        return None
    try:
        lines = stdout.decode("ascii", "strict").splitlines()
    except UnicodeDecodeError:
        return None
    expected_names = sorted(CHECK_EXPECTATIONS)
    if len(lines) != len(expected_names):
        return None

    statuses: dict[str, bool] = {}
    for expected_name, line in zip(expected_names, lines, strict=True):
        parts = line.split(" | ")
        if len(parts) != 4:
            return None
        name, status, expected_text, actual_text = parts
        expected = _parse_bool(expected_text)
        actual = _parse_bool(actual_text)
        if name != expected_name or expected != CHECK_EXPECTATIONS[name] or actual is None:
            return None
        if status not in {"PASS", "FAIL"}:
            return None
        if (status == "PASS") != (actual == expected):
            return None
        statuses[name] = status == "PASS"
    return statuses, "\n".join(lines)


def expected_pass_report() -> bytes:
    def postgres_bool(value: bool) -> str:
        return "t" if value else "f"

    return ("\n".join(
        f"{name} | PASS | {postgres_bool(CHECK_EXPECTATIONS[name])} | {postgres_bool(CHECK_EXPECTATIONS[name])}"
        for name in sorted(CHECK_EXPECTATIONS)
    )).encode("ascii")


def _audit_record(result_class: str, child_status: int, statuses: Mapping[str, bool]) -> dict[str, object]:
    return {
        "timestamp": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "operation": OPERATION_NAME,
        "verifier_blob": EXPECTED_VERIFIER_BLOB,
        "result_class": result_class,
        "child_exit_status": child_status,
        "checks": {name: "PASS" if passed else "FAIL" for name, passed in sorted(statuses.items())},
    }


def _default_audit(record: Mapping[str, object]) -> bool:
    encoded = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")
    try:
        descriptor = os.open(
            AUDIT_LOG_PATH,
            os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_gid != 0:
                return False
            if stat.S_IMODE(metadata.st_mode) != 0o600:
                return False
            os.write(descriptor, encoded)
        finally:
            os.close(descriptor)
    except OSError:
        return False
    return True


def _finish(
    exit_code: int,
    result_class: str,
    output: str,
    audit: AuditWriter,
    statuses: Mapping[str, bool],
    child_status: int,
) -> LaunchResult:
    if not audit(_audit_record(result_class, child_status, statuses)):
        return LaunchResult(71, "AUDIT_FAILURE", "result=RUNTIME_FAILURE")
    return LaunchResult(exit_code, result_class, output)


def run(
    argv: Sequence[str],
    *,
    runner: Runner = _subprocess_runner,
    verifier_bytes: bytes | None = None,
    audit: AuditWriter = _default_audit,
) -> LaunchResult:
    if argv:
        return _finish(64, "BOUNDARY_FAILURE", "result=BOUNDARY_FAILURE", audit, {}, 64)

    try:
        verifier = verifier_bytes if verifier_bytes is not None else _read_runtime_verifier()
    except ValueError:
        return _finish(65, "SOURCE_IDENTITY_FAILURE", "result=SOURCE_IDENTITY_FAILURE", audit, {}, 65)

    try:
        child = runner(list(FIXED_DOCKER_COMMAND), _build_psql_input(verifier), dict(SANITIZED_ENV))
    except (OSError, subprocess.SubprocessError):
        return _finish(72, "RUNTIME_FAILURE", "result=RUNTIME_FAILURE", audit, {}, 72)

    if child.returncode not in {0, 3}:
        return _finish(
            child.returncode if child.returncode else 72,
            "RUNTIME_FAILURE",
            "result=RUNTIME_FAILURE",
            audit,
            {},
            child.returncode,
        )

    parsed = _parse_verifier_report(child.stdout)
    if parsed is None:
        return _finish(70, "OUTPUT_GRAMMAR_FAILURE", "result=OUTPUT_GRAMMAR_FAILURE", audit, {}, child.returncode)
    statuses, report = parsed

    if child.returncode == 0 and all(statuses.values()):
        return _finish(0, "PASS", report + "\nresult=PASS", audit, statuses, 0)
    if child.returncode == 3 and not all(statuses.values()):
        return _finish(3, "VERIFIER_ASSERTION_FAILURE", report + "\nresult=VERIFIER_ASSERTION_FAILURE", audit, statuses, 3)
    return _finish(72, "RUNTIME_FAILURE", "result=RUNTIME_FAILURE", audit, statuses, child.returncode)


def main(argv: Sequence[str] | None = None) -> int:
    result = run(sys.argv[1:] if argv is None else argv)
    print(result.output)
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
