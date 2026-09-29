from __future__ import annotations

import importlib
import importlib.util
import sys
import shutil
import tempfile
import threading
from pathlib import Path
from types import ModuleType


CONTROL_PLANE_ROOT = Path(__file__).resolve().parents[2] / "control_plane"
_ALIAS = "tc7a2_control_plane"
CORRELATION_ID = "corr_018f3d4a-7b8c-7c9d-8e1f-0123456789ab"


def _module(name: str):
    if _ALIAS not in sys.modules:
        root = ModuleType(_ALIAS)
        root.__path__ = [str(CONTROL_PLANE_ROOT)]
        sys.modules[_ALIAS] = root
    app_name = f"{_ALIAS}.app"
    if app_name not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            app_name,
            CONTROL_PLANE_ROOT / "app" / "__init__.py",
            submodule_search_locations=[str(CONTROL_PLANE_ROOT / "app")],
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[app_name] = module
        spec.loader.exec_module(module)
    return importlib.import_module(f"{_ALIAS}.app.{name}")


def _task_body() -> dict:
    policy = _module("policy").POLICY_VERSION
    return {
        "created_by": {"identity_type": "AGENT", "identity_id": "hermes"},
        "requested_by": {"identity_type": "HUMAN", "identity_id": "owner"},
        "allowed_operations": [{"operation": "worker.run", "target_scope": "task-worktree", "gate_requirement": "NONE", "policy_version": policy}],
        "resource_budget": {"workers": 1, "processes": 1, "previews": 0, "worktrees": 0, "temporary_bytes": 0, "artifact_bytes": 0, "runtime_seconds": 60},
        "prerequisite_status": {},
        "risk_class": "GREEN",
    }


class ControlPlaneFixture:
    def __init__(self, tmp_path: Path, provider_state: str = "AVAILABLE") -> None:
        auth = _module("auth")
        main = _module("main")
        service_module = _module("service")
        self.socket_dir = Path(tempfile.mkdtemp(prefix="cp-tc7a2-"))
        self.socket_dir.chmod(0o700)
        self.socket_path = self.socket_dir / "cp.sock"
        self.database_path = tmp_path / "control-plane.sqlite"
        self.issuer = auth.HermeticCapabilityIssuer()
        self.stop = threading.Event()
        self.ready = threading.Event()
        service = service_module.ControlPlaneService(self.database_path)
        hermes = {"role": "HERMES_COORDINATOR", "identity_id": "hermes"}
        created = service.create_task(hermes, "fixture-create", CORRELATION_ID, _task_body())
        self.task_id = created["task_id"]
        service.transition_task(hermes, "fixture-ready", CORRELATION_ID, self.task_id, 0, "READY")
        observer = {"role": "OBSERVABILITY_ADAPTER", "identity_id": "observer"}
        service.record_provider_observation(
            observer,
            "fixture-provider",
            CORRELATION_ID,
            "test-channel",
            provider_state,
            "2026-09-29T00:00:00.000Z",
            None,
            "hermetic-test",
            {},
        )
        service.close()
        self.thread = threading.Thread(
            target=main.serve,
            args=(self.socket_path, self.database_path),
            kwargs={"issuer": self.issuer, "stop_event": self.stop, "ready_event": self.ready},
            daemon=True,
        )
        self.thread.start()
        assert self.ready.wait(2)

    def capability(self, operations: list[str], *, expires_at: str = "2099-01-01T00:00:00.000Z") -> dict:
        return self.issuer.issue(
            "fixture-capability",
            "HERMES_COORDINATOR",
            "hermes",
            operations,
            expires_at,
            task_id=self.task_id,
        )

    def budget(self) -> dict:
        service = _module("service").ControlPlaneService(self.database_path)
        try:
            return service.get_execution_budget(self.task_id)
        finally:
            service.close()

    def consume_calls(self, count: int) -> None:
        service = _module("service").ControlPlaneService(self.database_path)
        try:
            caller = {"role": "HERMES_COORDINATOR", "identity_id": "hermes"}
            for index in range(count):
                assert service.admit_model_call(caller, f"fixture-consume-{index}", CORRELATION_ID, self.task_id, "COORDINATOR")["decision"] == "ADMIT"
        finally:
            service.close()

    def stop_server(self) -> None:
        self.stop.set()
        self.thread.join(2)

    def close(self) -> None:
        self.stop_server()
        shutil.rmtree(self.socket_dir, ignore_errors=True)
