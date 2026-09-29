import pytest

from app.errors import ControlPlaneError
from app.models import canonical_json, require_canonical_json, require_semver, validate_timestamp
from app.service import ControlPlaneService
from helpers import CORR, HERMES, task_body


def test_schema_rejects_incomplete_budget_future_version_and_secret_payload(tmp_path):
    service = ControlPlaneService(tmp_path / "db.sqlite")
    bad = task_body(); bad["resource_budget"].pop("runtime_seconds")
    with pytest.raises(ControlPlaneError, match="INVALID_REQUEST"):
        service.create_task(HERMES, "bad-budget", CORR, bad)
    secret = task_body(); secret["capability_proof"] = "forbidden"
    with pytest.raises(ControlPlaneError, match="INVALID_REQUEST"):
        service.create_task(HERMES, "secret", CORR, secret)
    with pytest.raises(ControlPlaneError, match="UNSUPPORTED_SCHEMA"):
        require_semver("2.0.0")
    assert canonical_json({"b": 1, "a": [True]}) == '{"a":[true],"b":1}'
    with pytest.raises(ValueError): require_canonical_json('{"b":1,"a":2}')
    assert validate_timestamp("2026-09-29T12:34:56.789Z")
    service.close()
