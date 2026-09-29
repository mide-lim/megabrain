"""Ordered immutable SQL migrations and bootstrap verification."""
from __future__ import annotations
import hashlib, sqlite3
from pathlib import Path
from .sqlite import immediate,verify_pragmas
from ..models import utc_now
from ..errors import fail
MIGRATIONS_DIR=Path(__file__).parents[2]/"migrations"
def migration_files(directory: Path=MIGRATIONS_DIR):
    files=sorted(directory.glob("[0-9][0-9][0-9][0-9]_*.sql"))
    if not files or files[0].name != "0001_initial_schema.sql": raise fail("REGISTRY_UNAVAILABLE","invalid migration set")
    return files
def checksum(path: Path)->str: return hashlib.sha256(path.read_bytes()).hexdigest()
def apply_migrations(con: sqlite3.Connection, service_version="1.0.0", directory: Path=MIGRATIONS_DIR) -> None:
    files=migration_files(directory); existing={}
    if con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'").fetchone():
        existing={r["migration_id"]:r["checksum_sha256"] for r in con.execute("SELECT migration_id,checksum_sha256 FROM schema_migrations")}
    for f in files:
        digest=checksum(f)
        if f.name in existing:
            if existing[f.name] != digest: raise fail("REGISTRY_UNAVAILABLE","migration checksum mismatch")
            continue
        metadata_exists = bool(con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='registry_metadata'").fetchone())
        try:
            if metadata_exists:
                with immediate(con):
                    con.execute("UPDATE registry_metadata SET metadata_value='MIGRATING',updated_at=? WHERE metadata_key='admission_state'",(utc_now(),))
                    con.execute("UPDATE registry_metadata SET metadata_value='',updated_at=? WHERE metadata_key='migration_failure_code'",(utc_now(),))
            # 0001 bootstraps metadata itself; later migrations observe persisted
            # MIGRATING state before their SQL runs, so admission stays fail-closed.
            con.executescript(f.read_text())
            with immediate(con):
                con.execute("INSERT INTO schema_migrations VALUES(?,?,?,?,?)",(f.name,digest,utc_now(),service_version,f.stem))
                for k,v in {"admission_state":"MIGRATING","schema_epoch":"1","event_chain_algorithm":"sha256-jcs-v1","event_chain_head_sequence":"0","event_chain_head_hash":"","migration_failure_code":"","recovery_pending_resources":"[]"}.items(): con.execute("INSERT OR IGNORE INTO registry_metadata VALUES(?,?,?)",(k,v,utc_now()))
        except sqlite3.Error as e:
            if con.in_transaction:
                con.execute("ROLLBACK")
            if con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='registry_metadata'").fetchone():
                try:
                    with immediate(con):
                        con.execute("UPDATE registry_metadata SET metadata_value='RECOVERY_REQUIRED',updated_at=? WHERE metadata_key='admission_state'",(utc_now(),))
                        con.execute("UPDATE registry_metadata SET metadata_value=?,updated_at=? WHERE metadata_key='migration_failure_code'",(f.name,utc_now()))
                except sqlite3.Error:
                    pass
            raise fail("REGISTRY_UNAVAILABLE","migration failed") from e
    verify_pragmas(con)
    if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or con.execute("PRAGMA foreign_key_check").fetchall(): raise fail("REGISTRY_UNAVAILABLE","registry integrity check failed")
    state = con.execute("SELECT metadata_value FROM registry_metadata WHERE metadata_key='admission_state'").fetchone()
    if state and state[0] == "MIGRATING":
        with immediate(con): con.execute("UPDATE registry_metadata SET metadata_value='READY',updated_at=? WHERE metadata_key='admission_state'",(utc_now(),))
def admission_ready(con):
    row=con.execute("SELECT metadata_value FROM registry_metadata WHERE metadata_key='admission_state'").fetchone()
    return bool(row and row[0]=="READY")
