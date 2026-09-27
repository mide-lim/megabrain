from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SECURITY_DIR = REPO_ROOT / "infra/postgres/security/f6"
GRANT = SECURITY_DIR / "007_i1_b_web_applicable_enrichment_read_grant.sql"
VERIFIER = SECURITY_DIR / "008_i1_b_web_applicable_enrichment_read_verify.sql"
ROLLBACK = SECURITY_DIR / "009_i1_b_web_applicable_enrichment_read_rollback.sql"
NEW_COLUMNS = ("source_object_key", "source_sha256", "pipeline_version")
REEL_IDENTITY_COLUMN = ("sha256",)
PRESENTATION_COLUMNS = (
    "id",
    "reel_id",
    "completed_at",
    "media_duration_seconds",
    "outcome",
    "transcript_text",
    "transcript_language",
)


def artifact(path: Path) -> str:
    assert path.is_file(), f"missing I1-B Web authority artifact: {path}"
    return path.read_text(encoding="utf-8")


def executable_sql(sql: str) -> str:
    lines: list[str] = []
    for line in sql.splitlines():
        lines.append(line.split("--", 1)[0])
    return "\n".join(lines)


def normalized(sql: str) -> str:
    return " ".join(executable_sql(sql).upper().split())


def sql_without_quoted_literals(sql: str) -> str:
    return re.sub(r"'(?:''|[^'])*'", "''", executable_sql(sql))


def column_grants(sql: str, statement: str, privilege: str, role_keyword: str) -> list[tuple[tuple[str, ...], str, str]]:
    return [
        (
            tuple(column.strip().lower() for column in columns.split(",")),
            relation.lower(),
            role.lower(),
        )
        for columns, relation, role in re.findall(
            rf"\b{statement}\s+{privilege}\s*\(([^)]+)\)\s+ON\s+(?:TABLE\s+)?(app\.[a-z_][a-z0-9_]*)\s+{role_keyword}\s+([a-z_][a-z0-9_]*)\s*;",
            executable_sql(sql),
            flags=re.IGNORECASE | re.DOTALL,
        )
    ]


def table_grants(sql: str, statement: str, privilege: str, role_keyword: str) -> list[tuple[str, str]]:
    return [
        (relation.lower(), role.lower())
        for relation, role in re.findall(
            rf"\b{statement}\s+{privilege}\s+ON\s+(?:TABLE\s+)?(app\.[a-z_][a-z0-9_]*)\s+{role_keyword}\s+([a-z_][a-z0-9_]*)\s*;",
            executable_sql(sql),
            flags=re.IGNORECASE | re.DOTALL,
        )
    ]


def test_i1_b_grant_adds_only_the_three_web_applicable_enrichment_read_columns() -> None:
    grant = artifact(GRANT)
    assert artifact(VERIFIER)
    assert artifact(ROLLBACK)

    assert column_grants(grant, "GRANT", "SELECT", "TO") == [
        (REEL_IDENTITY_COLUMN, "app.reels", "megabrain_web"),
        (NEW_COLUMNS, "app.reel_enrichments", "megabrain_web")
    ]
    assert table_grants(grant, "GRANT", "SELECT", "TO") == []
    executable = normalized(grant)
    assert "BEGIN;" in executable
    assert executable.endswith("COMMIT;")
    for prerequisite in (
        "MEGABRAIN_WEB",
        "APP.REELS",
        "APP.REEL_ENRICHMENTS",
        "SHA256",
        "SOURCE_OBJECT_KEY",
        "SOURCE_SHA256",
        "PIPELINE_VERSION",
    ):
        assert prerequisite in executable
    for forbidden in (
        "GRANT INSERT",
        "GRANT UPDATE",
        "GRANT DELETE",
        "REEL_ENRICHMENT_ATTEMPTS",
        "SEQUENCE",
        "GRANT ROLE",
        "ALTER ROLE",
        "PUBLIC",
    ):
        assert forbidden not in executable


def test_i1_b_verifier_proves_exact_enrichment_select_allowlist_and_forbidden_boundaries() -> None:
    verifier = artifact(VERIFIER)
    executable = normalized(verifier)

    assert "\\SET ON_ERROR_STOP ON" in executable
    assert not re.search(
        r"\b(?:INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|GRANT|REVOKE|TRUNCATE)\b",
        sql_without_quoted_literals(verifier),
    )
    for check in (
        "WEB_I1_B_CAN_READ_APPLICABLE_ENRICHMENT_TUPLE",
        "WEB_I1_B_CAN_READ_REEL_SOURCE_SHA256",
        "WEB_I1_B_REELS_TABLE_WIDE_SELECT",
        "WEB_I1_B_ENRICHMENTS_TABLE_WIDE_SELECT",
        "WEB_I1_B_CANNOT_WRITE_ENRICHMENTS",
        "WEB_I1_B_CANNOT_ACCESS_ENRICHMENT_ATTEMPTS",
        "WEB_I1_B_CANNOT_USE_ENRICHMENT_RESULT_SEQUENCE",
        "WEB_I1_B_EFFECTIVE_ENRICHMENT_SELECT_ALLOWLIST",
        "WEB_I1_B_EFFECTIVE_REEL_SELECT_ALLOWLIST",
        "WEB_I1_B_NO_UNEXPECTED_ROLE_MEMBERSHIPS",
        "WEB_I1_B_NO_UNEXPECTED_PUBLIC_AUTHORITY",
    ):
        assert check in verifier
    for column in PRESENTATION_COLUMNS + NEW_COLUMNS:
        assert f"'{column}'" in verifier
    assert "'sha256'" in verifier
    for function in (
        "HAS_COLUMN_PRIVILEGE",
        "HAS_TABLE_PRIVILEGE",
        "HAS_SEQUENCE_PRIVILEGE",
        "HAS_SCHEMA_PRIVILEGE",
    ):
        assert function in executable
    assert "\\IF :I1_B_WEB_APPLICABLE_ENRICHMENT_READ_VERIFIER_ALL_PASS" in executable
    assert "\\QUIT 3" in executable


def test_i1_b_rollback_is_acknowledgement_gated_and_removes_exactly_the_new_select_delta() -> None:
    rollback = artifact(ROLLBACK)
    executable = normalized(rollback)

    assert "\\SET ON_ERROR_STOP ON" in executable
    assert "\\IF :{?I1_B_WEB_APPLICABLE_ENRICHMENT_READ_ROLLBACK_ACK}" in executable
    assert "\\IF :I1_B_WEB_APPLICABLE_ENRICHMENT_READ_ROLLBACK_ACK" in executable
    assert "MUST BE TRUE" in executable
    assert column_grants(rollback, "REVOKE", "SELECT", "FROM") == [
        (REEL_IDENTITY_COLUMN, "app.reels", "megabrain_web"),
        (NEW_COLUMNS, "app.reel_enrichments", "megabrain_web")
    ]
    assert table_grants(rollback, "REVOKE", "SELECT", "FROM") == []
    for forbidden in (
        "REEL_ENRICHMENT_ATTEMPTS",
        "INSERT",
        "UPDATE",
        "DELETE",
        "SEQUENCE",
    ):
        assert forbidden not in executable
