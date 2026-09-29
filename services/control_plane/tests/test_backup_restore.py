from app.errors import ControlPlaneError
from app.service import ControlPlaneService
from app.storage.backup import backup, restore, validate_backup
from helpers import CORR, CORR2, MANAGER, OBSERVER, ready_task, worker_request


def test_sqlite_backup_restore_is_isolated_and_requires_each_nonterminal_lease_reconciled(tmp_path):
    source = tmp_path / "source.db"; service = ControlPlaneService(source)
    task_id = ready_task(service, MANAGER)
    resource = service.allocate_resource(MANAGER, "allocation", CORR, task_id, worker_request())
    target = tmp_path / "backups" / "copy.db"; backup(service.con, target)
    assert validate_backup(target)
    restored = restore(target, tmp_path / "restore" / "registry.db")
    assert restored.execute("SELECT metadata_value FROM registry_metadata WHERE metadata_key='admission_state'").fetchone()[0] == "RECOVERY_REQUIRED"
    restored.close(); service.close()
    recovered = ControlPlaneService(tmp_path / "restore" / "registry.db")
    assert recovered.get_task(task_id)["task_id"] == task_id
    try:
        recovered.create_task(MANAGER, "blocked-recovery", CORR, __import__("helpers").task_body())
        assert False, "recovery-required registry admitted a task"
    except ControlPlaneError as exc:
        assert exc.code == "REGISTRY_UNAVAILABLE"
    reconciliation = recovered.reconcile_observation(OBSERVER, "reconcile", CORR2, resource["resource_id"], "process", "1.0", {"status": "MISSING"}, "2026-09-29T00:00:00.000Z", "evidence:missing")
    assert reconciliation["result"] == "MISSING_RUNTIME"
    assert recovered.con.execute("SELECT metadata_value FROM registry_metadata WHERE metadata_key='admission_state'").fetchone()[0] == "READY"
    recovered.close()
