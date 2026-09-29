from app.policy import DEFAULTS, allowed_transition


def test_frozen_policy_defaults_are_bounded_and_transitions_are_closed():
    assert DEFAULTS["max_workers_global"] == 1 and DEFAULTS["preview_bind_address"] == "127.0.0.1"
    assert DEFAULTS["heartbeat_miss_seconds"] == 90 and DEFAULTS["heartbeat_grace_seconds"] == 60
    assert DEFAULTS["quota_observation_min_seconds"] == 300 and DEFAULTS["quota_observation_max"] == 12
    assert allowed_transition("task", "READY", "RUNNING") and not allowed_transition("task", "TERMINAL", "RUNNING")
