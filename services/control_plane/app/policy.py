"""Frozen AP0 v1 policy values and pure evaluators."""
from __future__ import annotations
POLICY_VERSION="1.0.0"
DEFAULTS={"policy_version":POLICY_VERSION,"max_workers_per_task":1,"max_workers_global":1,"max_processes_per_task":3,"max_previews_per_task":1,"max_worktrees_per_task":1,"default_worker_timeout_seconds":2700,"max_worker_timeout_seconds":7200,"heartbeat_interval_seconds":30,"heartbeat_miss_seconds":90,"heartbeat_grace_seconds":60,"preview_ttl_seconds":7200,"preview_bind_address":"127.0.0.1","preview_port_min":38000,"preview_port_max":38199,"retry_attempts":2,"retry_base_ms":250,"retry_cap_ms":2000,"quota_observation_min_seconds":300,"quota_observation_max":12,"model_calls_limit":40,"max_live_delegations":1,"reviewer_calls_limit":8,"provider_retry_limit":2,"context_soft_limit_tokens":80000,"context_hard_limit_tokens":120000}
def preview_allowed(metadata: dict) -> bool:
    return metadata.get("bind_address") == DEFAULTS["preview_bind_address"] and isinstance(metadata.get("port"),int) and DEFAULTS["preview_port_min"] <= metadata["port"] <= DEFAULTS["preview_port_max"] and metadata.get("launcher_capability_class") == "SOCKET_ACTIVATION"
def resource_limit(resource_type: str) -> str:
    return {"WORKER":"workers","PROCESS":"processes","PREVIEW":"previews","WORKTREE":"worktrees"}.get(resource_type, "")
def allowed_transition(family: str, old: str, new: str) -> bool:
    graph={"task":{"CREATED":{"READY","BLOCKED","TERMINAL"},"READY":{"RUNNING","PAUSED","BLOCKED","TERMINAL"},"RUNNING":{"VALIDATING","REVIEW","PAUSED","BLOCKED","TERMINAL"},"VALIDATING":{"REVIEW","PAUSED","BLOCKED","TERMINAL"},"REVIEW":{"PAUSED","BLOCKED","TERMINAL"},"PAUSED":{"READY","RUNNING","BLOCKED","TERMINAL"},"BLOCKED":{"READY","TERMINAL"}},"resource":{"ALLOCATED":{"ACTIVE","TERMINAL","STALE_CANDIDATE"},"ACTIVE":{"IDLE","TERMINAL","HEARTBEAT_MISSED","STALE_CANDIDATE"},"IDLE":{"ACTIVE","TERMINAL","HEARTBEAT_MISSED","STALE_CANDIDATE"},"HEARTBEAT_MISSED":{"ACTIVE","TERMINAL","STALE_CANDIDATE"},"STALE_CANDIDATE":{"ACTIVE","TERMINAL"}},"gate":{"PENDING":{"APPROVED","DENIED","EXPIRED"},"APPROVED":{"CONSUMED","EXPIRED"}}}
    return new in graph.get(family,{}).get(old,set())
