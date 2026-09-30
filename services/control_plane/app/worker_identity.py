"""Typed pre-spawn Worker expectations and post-spawn process identities."""
from __future__ import annotations

import hashlib
import hmac
import re
import uuid
from typing import Protocol, TypedDict


LAUNCH_EXPECTATION_KIND = "WORKER_PROCESS_V1"
_MAX_PROFILE_LENGTH = 128
_MAX_REFERENCE_LENGTH = 4096
_MAX_START_TIME_LENGTH = 128
_MAX_NONCE_LENGTH = 128
_NONCE_MINIMUM_LENGTH = 43  # URL-safe base64 characters for at least 256 bits.
_PROFILE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_NONCE = re.compile(r"[A-Za-z0-9_-]+\Z")
_HEX_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class LaunchExpectation(TypedDict):
    kind: str
    expected_boot_id: str
    expected_uid: int
    executable_class: str
    worktree_ref: str
    nonce_sha256: str


class ObservedProcessIdentity(TypedDict):
    pid: int
    start_time: str
    boot_id: str
    uid: int
    parent_pid: int
    process_group: int
    cwd: str
    executable: str
    cgroup: str | None


class WorkerIdentityVerifier(Protocol):
    """Trusted launcher/process evidence boundary; no production default exists."""

    def verify(self, resource_id: str, expectation: LaunchExpectation, observation: ObservedProcessIdentity) -> bool: ...


def _exact_object(value: object, fields: set[str], label: str) -> dict:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"exact {label} object required")
    return value


def _integer(value: object, label: str, *, positive: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < (1 if positive else 0):
        raise ValueError(f"valid {label} required")
    return value


def _bounded_text(value: object, label: str, maximum: int, *, ascii_only: bool = False) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum or "\x00" in value:
        raise ValueError(f"bounded {label} required")
    if ascii_only and (not value.isascii() or any(ord(char) < 0x20 or ord(char) > 0x7E for char in value)):
        raise ValueError(f"safe ASCII {label} required")
    return value


def _boot_id(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("canonical boot id required")
    try:
        canonical = str(uuid.UUID(value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("canonical boot id required") from exc
    if value != canonical:
        raise ValueError("canonical boot id required")
    return value


def validate_launch_expectation(value: object) -> LaunchExpectation:
    """Validate and return the exact persisted pre-spawn Worker expectation."""
    fields = {
        "kind", "expected_boot_id", "expected_uid", "executable_class", "worktree_ref", "nonce_sha256",
    }
    expectation = _exact_object(value, fields, "launch expectation")
    if expectation["kind"] != LAUNCH_EXPECTATION_KIND:
        raise ValueError("unsupported worker expectation kind")
    executable_class = _bounded_text(expectation["executable_class"], "executable class", _MAX_PROFILE_LENGTH, ascii_only=True)
    if not _PROFILE.fullmatch(executable_class):
        raise ValueError("configured executable class required")
    digest = expectation["nonce_sha256"]
    if not isinstance(digest, str) or not _HEX_DIGEST.fullmatch(digest):
        raise ValueError("lowercase SHA-256 digest required")
    return {
        "kind": LAUNCH_EXPECTATION_KIND,
        "expected_boot_id": _boot_id(expectation["expected_boot_id"]),
        "expected_uid": _integer(expectation["expected_uid"], "expected uid"),
        "executable_class": executable_class,
        "worktree_ref": _bounded_text(expectation["worktree_ref"], "worktree reference", _MAX_REFERENCE_LENGTH),
        "nonce_sha256": digest,
    }


def validate_observed_process_identity(value: object) -> ObservedProcessIdentity:
    """Validate and return the exact post-spawn Worker process identity."""
    fields = {
        "pid", "start_time", "boot_id", "uid", "parent_pid", "process_group", "cwd", "executable", "cgroup",
    }
    observation = _exact_object(value, fields, "observed process identity")
    cgroup = observation["cgroup"]
    if cgroup is not None:
        cgroup = _bounded_text(cgroup, "cgroup", _MAX_REFERENCE_LENGTH, ascii_only=True)
    return {
        "pid": _integer(observation["pid"], "pid", positive=True),
        "start_time": _bounded_text(observation["start_time"], "start time", _MAX_START_TIME_LENGTH),
        "boot_id": _boot_id(observation["boot_id"]),
        "uid": _integer(observation["uid"], "uid"),
        "parent_pid": _integer(observation["parent_pid"], "parent pid"),
        "process_group": _integer(observation["process_group"], "process group", positive=True),
        "cwd": _bounded_text(observation["cwd"], "cwd", _MAX_REFERENCE_LENGTH),
        "executable": _bounded_text(observation["executable"], "executable", _MAX_REFERENCE_LENGTH),
        "cgroup": cgroup,
    }


def validate_launch_nonce(value: object) -> str:
    """Accept one bounded URL-safe ASCII nonce; entropy originates with the Manager."""
    if not isinstance(value, str) or not value.isascii() or not _NONCE.fullmatch(value):
        raise ValueError("URL-safe ASCII launch nonce required")
    if not _NONCE_MINIMUM_LENGTH <= len(value) <= _MAX_NONCE_LENGTH:
        raise ValueError("launch nonce length outside security bound")
    return value


def launch_nonce_matches(expectation: object, launch_nonce: object) -> bool:
    """Compare the transient nonce with its persisted digest without retaining it."""
    try:
        expected = validate_launch_expectation(expectation)
        nonce = validate_launch_nonce(launch_nonce)
    except ValueError:
        return False
    actual_digest = hashlib.sha256(nonce.encode("ascii")).hexdigest()
    return hmac.compare_digest(actual_digest, expected["nonce_sha256"])


def matches_launch_expectation(expectation: object, observation: object, launch_nonce: object, verified_evidence: object) -> bool:
    """Pure association check; launcher-specific evidence is supplied externally."""
    try:
        expected = validate_launch_expectation(expectation)
        observed = validate_observed_process_identity(observation)
    except ValueError:
        return False
    return (
        verified_evidence is True
        and observed["boot_id"] == expected["expected_boot_id"]
        and observed["uid"] == expected["expected_uid"]
        and launch_nonce_matches(expected, launch_nonce)
    )
