"""Constrained read repository; callers never supply SQL."""
from __future__ import annotations
def get_task(con, task_id): return con.execute("SELECT * FROM tasks WHERE task_id=?",(task_id,)).fetchone()
def get_resource(con, resource_id): return con.execute("SELECT * FROM resource_leases WHERE resource_id=?",(resource_id,)).fetchone()
def task_resources(con, task_id): return con.execute("SELECT * FROM resource_leases WHERE task_id=? ORDER BY created_at",(task_id,)).fetchall()
def pending_gates(con, task_id): return con.execute("SELECT * FROM gates WHERE task_id=? AND status IN ('PENDING','APPROVED') ORDER BY requested_at",(task_id,)).fetchall()
