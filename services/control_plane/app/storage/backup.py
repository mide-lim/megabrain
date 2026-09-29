"""SQLite-aware hermetic backup and isolated restore helpers."""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from .event_chain import validate_chain
from .sqlite import connect, prepare_directory


def backup(source: sqlite3.Connection, destination: str | Path):
    destination = Path(destination); prepare_directory(destination.parent)
    target = sqlite3.connect(destination)
    try: source.backup(target)
    finally: target.close()
    os.chmod(destination, 0o600)


def restore(source: str | Path, destination: str | Path):
    src = sqlite3.connect(source); dst = Path(destination); prepare_directory(dst.parent)
    if dst.exists():
        raise ValueError("restore destination must be isolated")
    target = sqlite3.connect(dst)
    try: src.backup(target)
    finally: target.close(); src.close()
    os.chmod(dst, 0o600)
    con = connect(dst)
    if not (con.execute("PRAGMA integrity_check").fetchone()[0] == "ok" and not con.execute("PRAGMA foreign_key_check").fetchall() and validate_chain(con)):
        con.close(); raise ValueError("invalid backup")
    pending = [row[0] for row in con.execute("SELECT resource_id FROM resource_leases WHERE state != 'TERMINAL'")]
    con.execute("BEGIN IMMEDIATE")
    try:
        con.execute("UPDATE registry_metadata SET metadata_value='RECOVERY_REQUIRED' WHERE metadata_key='admission_state'")
        con.execute("UPDATE registry_metadata SET metadata_value=? WHERE metadata_key='recovery_pending_resources'", (json.dumps(pending, separators=(",", ":")),))
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK"); con.close(); raise
    return con


def validate_backup(path):
    con = connect(path)
    try: return con.execute("PRAGMA integrity_check").fetchone()[0] == "ok" and not con.execute("PRAGMA foreign_key_check").fetchall() and validate_chain(con)
    finally: con.close()
