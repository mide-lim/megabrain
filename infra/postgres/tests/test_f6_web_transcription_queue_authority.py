from __future__ import annotations

import re
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SECURITY_DIR = REPO_ROOT / "infra" / "postgres" / "security" / "f6"
GRANT = SECURITY_DIR / "001_f6_web_transcription_queue_grant.sql"
VERIFIER = SECURITY_DIR / "002_f6_web_transcription_queue_verify.sql"
ROLLBACK = SECURITY_DIR / "003_f6_web_transcription_queue_rollback.sql"
DOCUMENTATION = REPO_ROOT / "docs" / "F6_TC4_WEB_TRANSCRIPTION_QUEUE_AUTHORITY.md"
WEB_REELS = REPO_ROOT / "services" / "web" / "app" / "reels.py"
CANONICAL_BASE = "a54d205c5033cc1ecb9d62dd62137f262c8e8805"
F4_HISTORICAL_ARTIFACTS = (
    "infra/postgres/security/f4/001_f4_runtime_roles.sql",
    "infra/postgres/security/f4/002_f4_runtime_grants.sql",
    "infra/postgres/security/f4/003_f4_runtime_grants_verify.sql",
    "infra/postgres/security/f4/004_f4_runtime_grants_rollback.sql",
    "infra/postgres/security/f4/005_f4_web_auth_owner_query_select_hotfix.sql",
    "infra/postgres/security/f4/006_f4_web_auth_owner_query_select_hotfix_rollback.sql",
)
F4_WEB_SELECT_ALLOWLIST = (
    "id",
    "shortcode",
    "original_url",
    "source",
    "download_status",
    "curation_status",
    "transcription_status",
    "telegram_chat_id",
    "telegram_user_id",
    "telegram_message_id",
    "raw_message",
    "received_at",
    "title",
    "creator",
    "caption",
    "duration_seconds",
    "filename",
    "mime_type",
    "file_size_bytes",
    "storage_provider",
    "storage_bucket",
    "object_key",
    "downloaded_at",
)
F6_UPDATE_ALLOWLIST = (
    "curation_status",
    "transcription_status",
    "transcription_attempt_id",
    "updated_at",
)


def artifact(path: Path) -> str:
    assert path.is_file(), f"missing F6 TC4-A artifact: {path}"
    return path.read_text(encoding="utf-8")


def executable_lines(sql: str) -> str:
    return "\n".join(
        line
        for line in sql.splitlines()
        if not line.lstrip().startswith(("--", "\\"))
    )


def normalized(sql: str) -> str:
    return " ".join(sql.upper().split())


def compact_columns(columns: str) -> tuple[str, ...]:
    return tuple(column.strip().lower() for column in columns.split(","))


def reels_column_privileges(sql: str, statement: str, privilege: str, role_keyword: str) -> list[tuple[tuple[str, ...], str]]:
    return [
        (compact_columns(columns), role.lower())
        for columns, role in re.findall(
            rf"{statement}\s+{privilege}\s*\(([^)]+)\)\s+ON\s+TABLE\s+app\.reels\s+{role_keyword}\s+([a-z_]+)\s*;",
            sql,
            flags=re.IGNORECASE | re.DOTALL,
        )
    ]


def grants_on_reels(sql: str, privilege: str) -> list[tuple[tuple[str, ...], str]]:
    return reels_column_privileges(sql, "GRANT", privilege, "TO")


def revokes_on_reels(sql: str, privilege: str) -> list[tuple[tuple[str, ...], str]]:
    return reels_column_privileges(sql, "REVOKE", privilege, "FROM")


def canonical_file(path: str) -> str:
    completed = subprocess.run(
        ["git", "show", f"{CANONICAL_BASE}:{path}"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def test_f6_artifacts_exist_and_grant_only_the_required_web_queue_delta() -> None:
    grant = artifact(GRANT)
    assert artifact(VERIFIER)
    assert artifact(ROLLBACK)
    assert artifact(DOCUMENTATION)

    assert grants_on_reels(grant, "SELECT") == [
        (("transcription_attempt_id",), "megabrain_web"),
    ]
    assert grants_on_reels(grant, "UPDATE") == [
        (
            ("transcription_status", "transcription_attempt_id", "updated_at"),
            "megabrain_web",
        ),
    ]

    executable = normalized(executable_lines(grant))
    for prerequisite in ("MEGABRAIN_WEB", "APP.REELS", "TRANSCRIPTION_STATUS", "TRANSCRIPTION_ATTEMPT_ID", "UPDATED_AT"):
        assert prerequisite in executable
    for forbidden in (
        "GRANT SELECT ON TABLE APP.REELS",
        "GRANT UPDATE ON TABLE APP.REELS",
        "GRANT INSERT",
        "GRANT DELETE",
        "REEL_ENRICHMENT_ATTEMPTS",
        "REEL_ENRICHMENTS",
        "CREATE ON SCHEMA",
        "GRANT ROLE",
        "ALTER ROLE",
        "PASSWORD",
        "LOGIN",
    ):
        assert forbidden not in executable


def test_f6_verifier_is_catalog_read_only_and_fails_closed_on_exact_boundaries() -> None:
    sql = artifact(VERIFIER)
    executable = executable_lines(sql)
    uppercase = normalized(executable)

    assert re.search(r"^\s*(INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|GRANT|REVOKE|TRUNCATE)\b", executable, re.MULTILINE) is None
    for function in (
        "HAS_SCHEMA_PRIVILEGE",
        "HAS_TABLE_PRIVILEGE",
        "HAS_COLUMN_PRIVILEGE",
        "HAS_SEQUENCE_PRIVILEGE",
    ):
        assert function in uppercase
    for check_name in (
        "WEB_F6_CAN_SELECT_TRANSCRIPTION_ATTEMPT",
        "WEB_F6_CAN_QUEUE_TRANSCRIPTION",
        "WEB_CAN_WRITE_CURATION",
        "WEB_CANNOT_WRITE_DOWNLOAD",
        "WEB_REELS_TABLE_WIDE_UPDATE",
        "WEB_REELS_TABLE_WIDE_SELECT",
        "WEB_CANNOT_DELETE_REELS",
        "WEB_CANNOT_ACCESS_ENRICHMENT_ATTEMPTS",
        "WEB_CANNOT_WRITE_ENRICHMENT_RESULTS",
        "WEB_F6_EFFECTIVE_SELECT_ALLOWLIST",
        "WEB_F6_EFFECTIVE_UPDATE_ALLOWLIST",
        "WEB_F6_NO_UNEXPECTED_ROLE_MEMBERSHIPS",
        "WEB_F6_NO_UNEXPECTED_PUBLIC_AUTHORITY",
    ):
        assert check_name in sql
    assert "\\set ON_ERROR_STOP on" in sql
    assert "\\gset" in sql
    assert re.search(
        r"\\if\s+:f6_web_transcription_queue_verifier_all_pass\s*\\else\s*\\quit\s+3\s*\\endif",
        sql,
    ) is not None


def test_f6_verifier_encodes_exact_effective_web_reels_allowlists() -> None:
    sql = artifact(VERIFIER)

    assert "ARRAY[" in sql
    for column in F4_WEB_SELECT_ALLOWLIST + ("transcription_attempt_id",):
        assert f"'{column}'" in sql
    for column in F6_UPDATE_ALLOWLIST:
        assert f"'{column}'" in sql

    select_allowlist_match = re.search(
        r"\(\s*'megabrain_web',\s*'app\.reels',\s*'SELECT',\s*ARRAY\[([^]]+)\]\s*\)",
        sql,
        flags=re.IGNORECASE | re.DOTALL,
    )
    update_allowlist_match = re.search(
        r"\(\s*'megabrain_web',\s*'app\.reels',\s*'UPDATE',\s*ARRAY\[([^]]+)\]\s*\)",
        sql,
        flags=re.IGNORECASE | re.DOTALL,
    )
    assert select_allowlist_match is not None
    assert update_allowlist_match is not None
    assert tuple(re.findall(r"'([^']+)'", select_allowlist_match.group(1))) == F4_WEB_SELECT_ALLOWLIST + (
        "transcription_attempt_id",
    )
    assert tuple(re.findall(r"'([^']+)'", update_allowlist_match.group(1))) == F6_UPDATE_ALLOWLIST


def test_f6_rollback_is_acknowledgement_gated_and_revokes_only_the_f6_delta() -> None:
    sql = artifact(ROLLBACK)
    executable = normalized(executable_lines(sql))

    assert "\\set ON_ERROR_STOP on" in sql
    assert "\\if :{?f6_web_transcription_queue_rollback_ack}" in sql
    assert "\\if :f6_web_transcription_queue_rollback_ack" in sql
    assert "f6_web_transcription_queue_rollback_ack must be true" in sql
    assert revokes_on_reels(sql, "SELECT") == [
        (("transcription_attempt_id",), "megabrain_web"),
    ]
    assert revokes_on_reels(sql, "UPDATE") == [
        (
            ("transcription_status", "transcription_attempt_id", "updated_at"),
            "megabrain_web",
        ),
    ]
    for preserved in (
        "CURATION_STATUS",
        "AUTH_USERS",
        "AUTH_TRANSACTIONS",
        "AUTH_SESSIONS",
        "CATEGORIES",
        "REEL_CATEGORIES",
        "MEGABRAIN_MGB020",
        "MEGABRAIN_MGB030",
    ):
        assert preserved not in executable
    assert "Transcrever" in artifact(DOCUMENTATION)


def test_f4_historical_security_artifacts_are_byte_identical_to_the_canonical_base() -> None:
    for relative_path in F4_HISTORICAL_ARTIFACTS:
        assert (REPO_ROOT / relative_path).read_text(encoding="utf-8") == canonical_file(relative_path)


def test_canonical_web_request_and_fallback_queries_require_the_f6_overlay_columns() -> None:
    web_source = artifact(WEB_REELS)

    request_match = re.search(
        r"REQUEST_TRANSCRIPTION_QUERY\s*=\s*\"\"\"(.*?)\"\"\"",
        web_source,
        flags=re.DOTALL,
    )
    fallback_match = re.search(
        r"REQUEST_TRANSCRIPTION_LIFECYCLE_QUERY\s*=\s*\"\"\"(.*?)\"\"\"",
        web_source,
        flags=re.DOTALL,
    )
    assert request_match is not None
    assert fallback_match is not None
    request_query = request_match.group(1)
    fallback_query = fallback_match.group(1)

    assert "UPDATE app.reels" in request_query
    for assignment in (
        "transcription_status = 'queued'",
        "transcription_attempt_id = NULL",
        "updated_at = NOW()",
    ):
        assert assignment in request_query
    assert "transcription_attempt_id" in fallback_query
    assert "SELECT" in fallback_query
    assert "reel_enrichment_attempts" not in request_query
    assert "reel_enrichments" not in request_query
    assert "INSERT" not in request_query
    assert "DELETE" not in request_query


def test_f6_documentation_preserves_the_authority_split_and_source_only_status() -> None:
    documentation = artifact(DOCUMENTATION)

    for required_text in (
        "not_requested|failed → queued",
        "queued → processing → completed|failed",
        "F4 authority",
        "F6 authority",
        "megabrain_web",
        "transcription_attempt_id",
        "schema migration required: NO",
        "runtime security authority delta required: YES",
        "NOT APPLIED",
        "NOT DEPLOYED",
        "NOT CUT OVER",
        "TC4-WEB-QUEUE-AUTHORITY",
        "no unexpected PUBLIC authority",
        "no unexpected role memberships",
        "Transcrever",
    ):
        assert required_text in documentation
