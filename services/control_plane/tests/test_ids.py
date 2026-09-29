import pytest

from app.ids import generate_id, uuid7, validate_id


def test_ids_are_lowercase_uuidv7_and_never_accept_wrong_family_or_timestamp_only_entropy():
    identifier = generate_id("task", now_ms=1, random_bytes=lambda size: b"\x00" * size)
    assert identifier == "task_00000000-0001-7000-8000-000000000000"
    assert validate_id(identifier, "task") and not validate_id(identifier, "rsrc")
    with pytest.raises(ValueError):
        uuid7(-1)
    with pytest.raises(ValueError):
        generate_id("unknown")
