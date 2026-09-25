from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]

F6_DIR = ROOT / "infra" / "postgres" / "security" / "f6"

GRANT = F6_DIR / "004_f6_mgb030_runtime_read_grant.sql"
VERIFY = F6_DIR / "005_f6_mgb030_runtime_read_verify.sql"
ROLLBACK = F6_DIR / "006_f6_mgb030_runtime_read_rollback.sql"

WORKFLOW = ROOT / "workflows" / "MGB-030-enrichment-reel.json"


EXPECTED_REELS_SELECT = (
    "id",
    "shortcode",
    "object_key",
    "sha256",
    "file_size_bytes",
    "download_status",
    "transcription_status",
    "transcription_attempt_id",
    "updated_at",
)

EXPECTED_ATTEMPTS_SELECT = (
    "attempt_id",
    "reel_id",
    "source_object_key",
    "expected_sha256",
    "expected_size_bytes",
    "pipeline_version",
    "contract_version",
    "language_hint",
    "status",
    "retryable",
    "error_code",
    "error_stage",
    "started_at",
    "provider_request_id",
    "retry_of_attempt_id",
)

EXPECTED_ENRICHMENTS_SELECT = (
    "id",
    "reel_id",
    "source_attempt_id",
    "source_object_key",
    "source_sha256",
    "pipeline_version",
    "outcome",
)


def read(path: Path) -> str:
    assert path.is_file(), f"missing artifact: {path}"
    return path.read_text(encoding="utf-8")


def compact_columns(value: str) -> tuple[str, ...]:
    return tuple(
        column.strip().lower()
        for column in value.split(",")
    )


def column_statement(
    sql: str,
    statement: str,
    relation: str,
    role_keyword: str,
) -> tuple[str, ...]:
    match = re.search(
        rf"\b{statement}\s+SELECT\s*"
        rf"\(([^)]+)\)\s+"
        rf"ON\s+TABLE\s+"
        rf"{re.escape(relation)}\s+"
        rf"{role_keyword}\s+"
        rf"megabrain_mgb030\s*;",
        sql,
        flags=re.IGNORECASE | re.DOTALL,
    )

    assert match is not None, (
        f"missing {statement} SELECT for {relation}"
    )

    return compact_columns(
        match.group(1)
    )


def verifier_allowlist(
    sql: str,
    relation: str,
) -> tuple[str, ...]:
    match = re.search(
        rf"\(\s*"
        rf"'megabrain_mgb030'\s*,\s*"
        rf"'{re.escape(relation)}'\s*,\s*"
        rf"'SELECT'\s*,\s*"
        rf"ARRAY\s*\[([^]]+)\]\s*"
        rf"\)",
        sql,
        flags=re.IGNORECASE | re.DOTALL,
    )

    assert match is not None, (
        f"missing verifier allowlist: {relation}"
    )

    return tuple(
        re.findall(
            r"'([^']+)'",
            match.group(1),
        )
    )


def executable_lines(sql: str) -> str:
    return "\n".join(
        line
        for line in sql.splitlines()
        if not line.lstrip().startswith(
            ("--", "\\")
        )
    )


def test_grant_is_exactly_four_select_columns() -> None:
    sql = read(GRANT)

    assert column_statement(
        sql,
        "GRANT",
        "app.reels",
        "TO",
    ) == (
        "updated_at",
    )

    assert column_statement(
        sql,
        "GRANT",
        "app.reel_enrichment_attempts",
        "TO",
    ) == (
        "started_at",
        "provider_request_id",
        "retry_of_attempt_id",
    )

    executable = executable_lines(sql).upper()

    assert "GRANT SELECT ON TABLE" not in executable
    assert "GRANT INSERT" not in executable
    assert "GRANT UPDATE" not in executable
    assert "GRANT DELETE" not in executable
    assert "GRANT CREATE" not in executable
    assert "ALTER ROLE" not in executable
    assert "PASSWORD" not in executable
    assert "LOGIN" not in executable


def test_verifier_exact_effective_select_allowlists() -> None:
    sql = read(VERIFY)

    assert verifier_allowlist(
        sql,
        "app.reels",
    ) == EXPECTED_REELS_SELECT

    assert verifier_allowlist(
        sql,
        "app.reel_enrichment_attempts",
    ) == EXPECTED_ATTEMPTS_SELECT

    assert verifier_allowlist(
        sql,
        "app.reel_enrichments",
    ) == EXPECTED_ENRICHMENTS_SELECT

    for name in (
        "MGB030_F6_CAN_READ_REELS_UPDATED_AT",
        "MGB030_F6_CAN_READ_ATTEMPT_SCHEDULING_FIELDS",
        "MGB030_REELS_TABLE_WIDE_SELECT",
        "MGB030_ATTEMPTS_TABLE_WIDE_SELECT",
        "MGB030_ENRICHMENTS_TABLE_WIDE_SELECT",
        "MGB030_F6_EFFECTIVE_SELECT_ALLOWLIST",
        "MGB030_F6_NO_UNEXPECTED_ROLE_MEMBERSHIPS",
        "MGB030_F6_NO_UNEXPECTED_PUBLIC_AUTHORITY",
    ):
        assert name in sql


def test_verifier_is_read_only_and_fail_closed() -> None:
    sql = read(VERIFY)
    executable = executable_lines(sql)

    assert re.search(
        r"^\s*"
        r"(INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|"
        r"GRANT|REVOKE|TRUNCATE)\b",
        executable,
        flags=re.IGNORECASE | re.MULTILINE,
    ) is None

    assert "\\set ON_ERROR_STOP on" in sql
    assert "\\gset" in sql

    assert re.search(
        r"\\if\s+"
        r":f6_mgb030_runtime_read_verifier_all_pass"
        r"\s*\\else\s*"
        r"\\quit\s+3\s*"
        r"\\endif",
        sql,
    ) is not None


def test_rollback_is_acknowledgement_gated_and_exact() -> None:
    sql = read(ROLLBACK)

    assert (
        "\\if "
        ":{?f6_mgb030_runtime_read_rollback_ack}"
        in sql
    )

    assert (
        "\\if "
        ":f6_mgb030_runtime_read_rollback_ack"
        in sql
    )

    assert column_statement(
        sql,
        "REVOKE",
        "app.reels",
        "FROM",
    ) == (
        "updated_at",
    )

    assert column_statement(
        sql,
        "REVOKE",
        "app.reel_enrichment_attempts",
        "FROM",
    ) == (
        "started_at",
        "provider_request_id",
        "retry_of_attempt_id",
    )

    executable = executable_lines(sql).upper()

    assert "REVOKE SELECT ON TABLE" not in executable
    assert "REVOKE UPDATE" not in executable
    assert "REVOKE INSERT" not in executable
    assert "REVOKE DELETE" not in executable


def test_delta_matches_canonical_f6_workflow_reads() -> None:
    workflow = read(WORKFLOW)

    for required in (
        "ORDER BY reel.updated_at ASC",
        "attempt.started_at ASC",
        "attempt.provider_request_id",
        "retry_of_attempt_id",
    ):
        assert required in workflow


def test_no_secret_material() -> None:
    for path in (
        GRANT,
        VERIFY,
        ROLLBACK,
    ):
        sql = read(path)

        assert "\x00" not in sql

        assert not re.search(
            r"(?i)"
            r"(password|passwd|secret)"
            r"\s*=\s*"
            r"['\"][^'\"]+",
            sql,
        )
