"""SQLite connection, owner-mode checks, and bounded transactions."""
from __future__ import annotations
import os, sqlite3
from contextlib import contextmanager
from pathlib import Path
from ..errors import fail
REQUIRED_PRAGMAS={"foreign_keys":1,"journal_mode":"wal","busy_timeout":2500,"synchronous":2,"trusted_schema":0}
def assert_owner_only(path: Path, is_dir: bool=False) -> None:
    if path.exists() and (path.stat().st_mode & 0o077): raise fail("REGISTRY_UNAVAILABLE","unsafe registry permissions")
    if is_dir and path.exists() and not path.is_dir(): raise fail("REGISTRY_UNAVAILABLE","registry parent is not a directory")
def prepare_directory(directory: str|Path) -> Path:
    p=Path(directory)
    if p.exists():
        assert_owner_only(p,True)
    else:
        p.mkdir(mode=0o700,parents=True,exist_ok=False)
        os.chmod(p,0o700)
    return p
def connect(path: str|Path) -> sqlite3.Connection:
    path=Path(path); prepare_directory(path.parent)
    if path.exists(): assert_owner_only(path)
    con=sqlite3.connect(path, timeout=2.5, isolation_level=None, check_same_thread=False)
    con.row_factory=sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON"); con.execute("PRAGMA journal_mode=WAL"); con.execute("PRAGMA busy_timeout=2500"); con.execute("PRAGMA synchronous=FULL"); con.execute("PRAGMA trusted_schema=OFF")
    if path.exists(): os.chmod(path,0o600)
    verify_pragmas(con); return con
def verify_pragmas(con: sqlite3.Connection) -> None:
    values={"foreign_keys":con.execute("PRAGMA foreign_keys").fetchone()[0],"journal_mode":con.execute("PRAGMA journal_mode").fetchone()[0].lower(),"busy_timeout":con.execute("PRAGMA busy_timeout").fetchone()[0],"synchronous":con.execute("PRAGMA synchronous").fetchone()[0],"trusted_schema":con.execute("PRAGMA trusted_schema").fetchone()[0]}
    if values != REQUIRED_PRAGMAS: raise fail("REGISTRY_UNAVAILABLE","required SQLite pragma unavailable")
@contextmanager
def immediate(con: sqlite3.Connection):
    try:
        con.execute("BEGIN IMMEDIATE"); yield con; con.execute("COMMIT")
    except Exception:
        if con.in_transaction: con.execute("ROLLBACK")
        raise
