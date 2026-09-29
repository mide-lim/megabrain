import shutil

import pytest

from app.errors import ControlPlaneError
from app.storage.migrations import apply_migrations
from app.storage.event_chain import append_event
from app.storage.sqlite import connect, immediate


def test_bootstrap_enforces_pragmas_schema_guards_and_checksum_immutability(tmp_path):
    con = connect(tmp_path / "state" / "registry.db"); apply_migrations(con)
    metadata = dict(con.execute("SELECT metadata_key,metadata_value FROM registry_metadata"))
    assert metadata["admission_state"] == "READY" and metadata["event_chain_head_sequence"] == "0"
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    with immediate(con):
        append_event(con, "GENESIS", {"identity_id": "tester"}, "corr_018f3d4a-7b8c-7c9d-8e1f-0123456789ab", {})
    with pytest.raises(Exception, match="AUDIT_APPEND_ONLY"):
        con.execute("UPDATE audit_events SET event_type='changed'")
    migration_dir = tmp_path / "migrations"; migration_dir.mkdir()
    source = __import__("pathlib").Path(__file__).parents[1] / "migrations" / "0001_initial_schema.sql"
    copied = migration_dir / source.name; shutil.copy(source, copied)
    second = connect(tmp_path / "second.db"); apply_migrations(second, directory=migration_dir)
    copied.write_text(copied.read_text() + "\n-- altered")
    with pytest.raises(ControlPlaneError, match="REGISTRY_UNAVAILABLE"):
        apply_migrations(second, directory=migration_dir)
    second.close(); con.close()


def test_incremental_migration_closes_admission_and_failure_requires_recovery(tmp_path):
    migration_dir = tmp_path / "migrations"; migration_dir.mkdir()
    source = __import__("pathlib").Path(__file__).parents[1] / "migrations" / "0001_initial_schema.sql"
    shutil.copy(source, migration_dir / source.name)
    con = connect(tmp_path / "registry.db"); apply_migrations(con, directory=migration_dir)
    (migration_dir / "0002_probe.sql").write_text(
        "BEGIN EXCLUSIVE; CREATE TABLE migration_probe AS SELECT metadata_value AS state "
        "FROM registry_metadata WHERE metadata_key='admission_state'; COMMIT;"
    )
    apply_migrations(con, directory=migration_dir)
    assert con.execute("SELECT state FROM migration_probe").fetchone()[0] == "MIGRATING"
    assert con.execute("SELECT metadata_value FROM registry_metadata WHERE metadata_key='admission_state'").fetchone()[0] == "READY"
    (migration_dir / "0003_broken.sql").write_text("BEGIN EXCLUSIVE; CREATE TABLE broken(; COMMIT;")
    with pytest.raises(ControlPlaneError, match="REGISTRY_UNAVAILABLE"):
        apply_migrations(con, directory=migration_dir)
    metadata = dict(con.execute("SELECT metadata_key,metadata_value FROM registry_metadata"))
    assert metadata["admission_state"] == "RECOVERY_REQUIRED"
    assert metadata["migration_failure_code"] == "0003_broken.sql"
    con.close()


def test_registry_refuses_preexisting_group_or_world_accessible_directory(tmp_path):
    unsafe = tmp_path / "unsafe"; unsafe.mkdir(mode=0o755); unsafe.chmod(0o755)
    with pytest.raises(ControlPlaneError, match="REGISTRY_UNAVAILABLE"):
        connect(unsafe / "registry.db")
