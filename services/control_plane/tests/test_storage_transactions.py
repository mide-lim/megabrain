import pytest

import app.service as service_module
from app.errors import ControlPlaneError
from app.service import ControlPlaneService
from app.storage.sqlite import connect, immediate
from helpers import CORR, HERMES, task_body


def test_audit_append_failure_rolls_back_task_and_idempotency_success(monkeypatch, tmp_path):
    service = ControlPlaneService(tmp_path / "db.sqlite")
    def broken(*args, **kwargs): raise RuntimeError("injected")
    monkeypatch.setattr(service_module, "append_event", broken)
    with pytest.raises(ControlPlaneError, match="AUDIT_WRITE_FAILED"):
        service.create_task(HERMES, "audit-failure", CORR, task_body())
    assert service.con.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0
    assert service.con.execute("SELECT count(*) FROM idempotency_requests").fetchone()[0] == 0
    service.close()


def test_interrupted_wal_transaction_recovers_only_committed_state(tmp_path):
    database = tmp_path / "wal.db"; connection = connect(database); connection.execute("CREATE TABLE probe(value INTEGER UNIQUE)")
    with pytest.raises(Exception):
        with immediate(connection):
            connection.execute("INSERT INTO probe VALUES(1)")
            connection.execute("INSERT INTO probe VALUES(1)")
    connection.close()
    recovered = connect(database)
    assert recovered.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert recovered.execute("SELECT count(*) FROM probe").fetchone()[0] == 0
    recovered.close()
