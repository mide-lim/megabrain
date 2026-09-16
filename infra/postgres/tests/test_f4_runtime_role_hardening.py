from __future__ import annotations

import re
from pathlib import Path


SECURITY_DIR = Path(__file__).resolve().parents[1] / "security" / "f4"
ROLE_CREATION = SECURITY_DIR / "001_f4_runtime_roles.sql"
GRANTS = SECURITY_DIR / "002_f4_runtime_grants.sql"
VERIFIER = SECURITY_DIR / "003_f4_runtime_grants_verify.sql"
ROLLBACK = SECURITY_DIR / "004_f4_runtime_grants_rollback.sql"
DOCUMENTATION = Path(__file__).resolve().parents[3] / "docs" / "F4_DATABASE_ROLE_HARDENING.md"
ARTIFACTS = (ROLE_CREATION, GRANTS, VERIFIER, ROLLBACK)
RUNTIME_ROLES = ("megabrain_mgb020", "megabrain_mgb030")


def artifact(path: Path) -> str:
    assert path.is_file(), f"missing F4 role-hardening artifact: {path}"
    return path.read_text(encoding="utf-8")


def normalized(path: Path) -> str:
    return " ".join(artifact(path).upper().split())


def executable_lines(sql: str) -> str:
    return "\n".join(
        line
        for line in sql.splitlines()
        if not line.lstrip().startswith(("--", "\\"))
    )


def compact(sql: str) -> str:
    return re.sub(r"\s+", "", sql)


def granted_columns(sql: str, privilege: str, role: str) -> str:
    match = re.search(
        rf"GRANT {privilege} \(([^;]+?)\) ON TABLE APP\.REELS TO {role}",
        sql,
    )
    assert match is not None
    return match.group(1)


def test_role_creation_is_noninteractive_nologin_structure_with_restrictive_attributes() -> None:
    sql = normalized(ROLE_CREATION)

    for role in ("MEGABRAIN_MGB020", "MEGABRAIN_MGB030"):
        assert f"CREATE ROLE {role} NOLOGIN" in sql
        assert f"ALTER ROLE {role} LOGIN" not in sql
        assert f"\\PASSWORD {role}" not in sql
    assert "MGB020_PASSWORD" not in sql
    assert "MGB030_PASSWORD" not in sql
    assert "PASSWORD" not in executable_lines(artifact(ROLE_CREATION)).upper()
    for attribute in (
        "NOSUPERUSER",
        "NOCREATEDB",
        "NOCREATEROLE",
        "NOREPLICATION",
        "NOBYPASSRLS",
        "NOINHERIT",
    ):
        assert sql.count(attribute) == 2
    assert "GRANT " not in sql
    assert "ALTER DEFAULT PRIVILEGES" not in sql
    assert "ALTER OWNER" not in sql


def test_verifier_proves_privilege_boundaries_before_human_login_provisioning() -> None:
    sql = artifact(VERIFIER)

    for role_check in (
        "MGB020_ROLE_ATTRIBUTES_RESTRICTIVE",
        "MGB030_ROLE_ATTRIBUTES_RESTRICTIVE",
    ):
        start = sql.index(role_check)
        end = sql.index("),", start)
        assert "rolcanlogin" not in sql[start:end].lower()


def test_grants_are_explicit_column_scoped_and_never_broad_or_ddl_capable() -> None:
    sql = normalized(GRANTS)

    assert "GRANT ALL" not in sql
    assert "GRANT CREATE ON SCHEMA APP" not in sql
    assert "ALTER OWNER" not in sql
    assert "ALTER TABLE" not in sql
    assert "ALTER DEFAULT PRIVILEGES" not in sql
    assert compact(granted_columns(sql, "UPDATE", "MEGABRAIN_WEB")) == "CURATION_STATUS"
    assert "GRANT USAGE ON SCHEMA APP TO MEGABRAIN_MGB020, MEGABRAIN_MGB030" in sql
    for role in RUNTIME_ROLES:
        assert f"REVOKE CREATE ON SCHEMA APP FROM {role.upper()}" in sql


def test_mgb020_and_mgb030_receive_only_their_lifecycle_write_boundaries() -> None:
    sql = normalized(GRANTS)

    mgb020_update = granted_columns(sql, "UPDATE", "MEGABRAIN_MGB020")
    mgb030_update = granted_columns(sql, "UPDATE", "MEGABRAIN_MGB030")
    assert "TRANSCRIPTION_STATUS" not in mgb020_update
    assert "TRANSCRIPTION_ATTEMPT_ID" not in mgb020_update
    assert "CURATION_STATUS" not in mgb020_update
    assert compact(mgb030_update) == "TRANSCRIPTION_STATUS,TRANSCRIPTION_ATTEMPT_ID,UPDATED_AT"
    assert "GRANT INSERT ON TABLE APP.REELS TO MEGABRAIN_MGB020" not in sql
    assert "GRANT DELETE ON TABLE APP.REELS TO MEGABRAIN_MGB020" not in sql
    assert "GRANT DELETE ON TABLE APP.REELS TO MEGABRAIN_MGB030" not in sql
    assert "GRANT USAGE ON SEQUENCE APP.REEL_ENRICHMENTS_ID_SEQ TO MEGABRAIN_MGB030" in sql
    assert "GRANT SELECT ON SEQUENCE" not in sql
    assert "GRANT UPDATE ON SEQUENCE" not in sql


def test_web_and_runtime_non_lifecycle_privileges_are_source_scoped() -> None:
    sql = normalized(GRANTS)

    compact_grants = compact(sql)
    assert "GRANTSELECT(ID,SHORTCODE,ORIGINAL_URL,SOURCE,DOWNLOAD_STATUS,CURATION_STATUS,TRANSCRIPTION_STATUS,TELEGRAM_CHAT_ID,TELEGRAM_USER_ID,TELEGRAM_MESSAGE_ID,RAW_MESSAGE,RECEIVED_AT,TITLE,CREATOR,CAPTION,DURATION_SECONDS,FILENAME,MIME_TYPE,FILE_SIZE_BYTES,STORAGE_PROVIDER,STORAGE_BUCKET,OBJECT_KEY,DOWNLOADED_AT)ONTABLEAPP.REELSTOMEGABRAIN_WEB" in compact_grants
    assert "GRANTINSERT(SHORTCODE,ORIGINAL_URL,SOURCE,DOWNLOAD_STATUS,TELEGRAM_CHAT_ID,TELEGRAM_USER_ID,TELEGRAM_MESSAGE_ID,RAW_MESSAGE,RECEIVED_AT)ONTABLEAPP.REELSTOMEGABRAIN_WEB" in compact_grants
    assert "GRANT SELECT ON TABLE APP.REEL_ENRICHMENT_ATTEMPTS TO MEGABRAIN_WEB" not in sql
    assert "GRANT INSERT ON TABLE APP.REEL_ENRICHMENTS TO MEGABRAIN_WEB" not in sql
    assert "GRANT SELECT (ID, NAME) ON TABLE APP.CATEGORIES TO MEGABRAIN_WEB" in sql
    assert "GRANT INSERT (NAME) ON TABLE APP.CATEGORIES TO MEGABRAIN_WEB" in sql


def test_verifier_is_catalog_read_only_and_proves_positive_and_negative_boundaries() -> None:
    sql = artifact(VERIFIER)
    executable = executable_lines(sql).upper()

    assert re.search(r"^\s*(INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|GRANT|REVOKE|TRUNCATE)\b", executable, re.MULTILINE) is None
    for function in (
        "HAS_SCHEMA_PRIVILEGE",
        "HAS_TABLE_PRIVILEGE",
        "HAS_COLUMN_PRIVILEGE",
        "HAS_SEQUENCE_PRIVILEGE",
    ):
        assert function in executable
    for check_name in (
        "WEB_ROLE_ATTRIBUTES_RESTRICTIVE",
        "MGB020_CAN_WRITE_DOWNLOAD",
        "MGB020_CAN_WRITE_TRANSCRIPTION",
        "MGB020_CAN_WRITE_CURATION",
        "MGB020_REELS_TABLE_WIDE_SELECT",
        "MGB020_REELS_TABLE_WIDE_UPDATE",
        "MGB020_AUTH_ACCESS",
        "MGB020_AUTH_TRANSACTION_ACCESS",
        "MGB020_AUTH_SESSION_ACCESS",
        "MGB030_CAN_WRITE_DOWNLOAD",
        "MGB030_CAN_WRITE_TRANSCRIPTION",
        "MGB030_CAN_WRITE_CURATION",
        "MGB030_REELS_TABLE_WIDE_SELECT",
        "MGB030_REELS_TABLE_WIDE_UPDATE",
        "MGB030_AUTH_ACCESS",
        "MGB030_AUTH_TRANSACTION_ACCESS",
        "MGB030_AUTH_SESSION_ACCESS",
        "WEB_CAN_WRITE_DOWNLOAD",
        "WEB_CAN_WRITE_TRANSCRIPTION",
        "WEB_CAN_WRITE_CURATION",
        "WEB_REELS_TABLE_WIDE_SELECT",
        "WEB_REELS_TABLE_WIDE_INSERT",
        "WEB_REELS_TABLE_WIDE_UPDATE",
        "WEB_REELS_EXCESS_SELECT",
        "WEB_REELS_EXCESS_INSERT",
        "EFFECTIVE_COLUMN_ALLOWLIST",
        "EFFECTIVE_TABLE_ALLOWLIST",
        "EFFECTIVE_SEQUENCE_ALLOWLIST",
        "RUNTIME_ROLES_OWN_NO_REVIEWED_OBJECTS",
        "ALL_RUNTIME_ROLES_HAVE_NO_MEMBERSHIPS",
        "MAINTAIN",
    ):
        assert check_name in sql


def test_rollback_is_dedicated_role_only_and_requires_human_credential_reassignment() -> None:
    sql = normalized(ROLLBACK)

    assert "DROP ROLE MEGABRAIN_MGB020" in sql
    assert "DROP ROLE MEGABRAIN_MGB030" in sql
    assert "MEGABRAIN_WEB" not in sql
    assert re.search(r"ALTER ROLE MEGABRAIN(?:\s|;)", sql) is None
    assert "REASSIGN OWNED" not in sql
    assert "DROP OWNED" not in sql
    assert "ALTER ROLE MEGABRAIN_MGB020 NOLOGIN" in sql
    assert "ALTER ROLE MEGABRAIN_MGB030 NOLOGIN" in sql
    assert "F4_DEDICATED_CREDENTIALS_DETACHED" in sql
    assert "\\IF :F4_DEDICATED_CREDENTIALS_DETACHED" in sql
    assert "PG_TERMINATE_BACKEND" in sql
    assert re.search(
        r"ALTER ROLE megabrain_mgb030 NOLOGIN;\s*COMMIT;.*?BEGIN;\s*DO",
        artifact(ROLLBACK),
        re.DOTALL,
    ) is not None


def test_documentation_never_recommends_passwords_in_process_arguments() -> None:
    documentation = artifact(DOCUMENTATION)

    assert "--set=mgb020_password" not in documentation
    assert "--set=mgb030_password" not in documentation
    assert "process argv" in documentation


def test_artifacts_are_reviewable_sql_files_without_committed_secret_material() -> None:
    for path in ARTIFACTS:
        sql = artifact(path)
        assert sql.rstrip().endswith(";") or sql.rstrip().endswith("\\quit")
        assert "\x00" not in sql
        assert not re.search(r"(?i)(password|passwd|secret)\s*=\s*['\"][^'\"]+", sql)
