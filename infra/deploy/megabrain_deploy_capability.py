#!/usr/bin/env python3
import fcntl
import json
import os
import re
import subprocess
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BIND = "172.18.0.1"
PORT = 18750
PROD = Path("/home/megabrain/megabrain")
INFRA = PROD / "infra"
CANDIDATES = Path("/srv/megabrain/deploy-candidates")
STATE_DIR = Path("/var/lib/megabrain-deploy-capability")
STATE_FILE = STATE_DIR / "state.json"
LOCK_FILE = STATE_DIR / "lock"
ISSUE_RE = re.compile(r"^MEG-[1-9][0-9]*$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
FILE_RE = re.compile(r"^[A-Za-z0-9._-]{1,180}\.patch$")
PATCH_HEAD_RE = re.compile(rb"^From ([0-9a-f]{40}) Mon Sep 17 00:00:00 2001\n")
MAX_PATCH = 2 * 1024 * 1024

class DeployError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status

def run(args, cwd=None, timeout=180, check=True):
    p = subprocess.run(
        args, cwd=cwd, text=True, capture_output=True,
        timeout=timeout, check=False,
    )
    if check and p.returncode != 0:
        detail = (p.stderr or p.stdout or "").strip()[-2000:]
        raise DeployError(f"command failed: {args[0]}: {detail}", 500)
    return p

def load_state():
    if not STATE_FILE.exists():
        return {"approvals": {}}
    return json.loads(STATE_FILE.read_text())

def save_state(state):
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, STATE_FILE)

DEPLOY_GATE_KEY = "megabrain-production-deploy"

def gate_matches(candidate, issue, commit):
    if candidate.get("issue") != issue:
        return False
    if candidate.get("kind") != "request_confirmation":
        return False
    if candidate.get("status") != "accepted":
        return False
    if candidate.get("effectiveResolverPolicy") != "human_only":
        return False
    if not candidate.get("resolvedByUserId") or candidate.get("resolvedByAgentId"):
        return False

    result = candidate.get("result")
    if not isinstance(result, dict) or result.get("outcome") != "accepted":
        return False

    payload = candidate.get("payload")
    if not isinstance(payload, dict):
        return False
    target = payload.get("target")
    if not isinstance(target, dict):
        return False
    if target.get("type") != "custom":
        return False
    if target.get("key") != DEPLOY_GATE_KEY:
        return False
    if target.get("revisionId") != commit:
        return False
    if target.get("href") != f"/MEG/issues/{issue}":
        return False
    return True

def accepted_gate(issue, commit):
    sql = f"""
select json_build_object(
  'id', iti.id::text,
  'issue', i.identifier,
  'kind', iti.kind,
  'status', iti.status,
  'effectiveResolverPolicy', iti.effective_resolver_policy,
  'result', iti.result,
  'payload', iti.payload,
  'resolvedByUserId', iti.resolved_by_user_id,
  'resolvedByAgentId', iti.resolved_by_agent_id
)::text
from issue_thread_interactions iti
join issues i on i.id=iti.issue_id
where i.identifier='{issue}'
  and iti.status='accepted'
order by iti.resolved_at desc nulls last
limit 20;
"""
    q = subprocess.run(
        ["docker", "exec", "-i", "megabrain-postgres", "sh", "-lc",
         'PGPASSWORD="$POSTGRES_PASSWORD" psql -U "$POSTGRES_USER" -d paperclip_prod -At'],
        input=sql, text=True, capture_output=True, timeout=20, check=False
    )
    if q.returncode != 0:
        raise DeployError("could not validate Paperclip approval gate", 503)
    for line in q.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            candidate = json.loads(line)
        except json.JSONDecodeError:
            continue
        if gate_matches(candidate, issue, commit):
            return str(candidate["id"])
    return None

def public_status(url):
    p = run(["curl", "-sS", "-o", "/dev/null", "-w", "%{http_code}|%{redirect_url}", url],
            timeout=15, check=False)
    return p.stdout.strip()

def wait_healthy(name, timeout=90):
    deadline = time.time() + timeout
    while time.time() < deadline:
        p = run(["docker", "inspect", "-f", "{{.State.Health.Status}}", name],
                timeout=10, check=False)
        if p.returncode == 0 and p.stdout.strip() == "healthy":
            return True
        time.sleep(2)
    return False

def rebuild():
    run(["docker", "compose", "up", "-d", "--build", "web", "frontend"],
        cwd=INFRA, timeout=240)
    if not wait_healthy("megabrain-web") or not wait_healthy("megabrain-frontend"):
        raise DeployError("web/frontend did not become healthy", 500)

def smoke():
    dev = public_status("https://megabrain.midelim.tech/development")
    status = public_status("https://megabrain.midelim.tech/api/platform/paperclip/status")
    paperclip = run(["curl", "-sS", "https://paperclip.midelim.tech/api/health"],
                    timeout=15).stdout
    try:
        pobj = json.loads(paperclip)
    except Exception:
        raise DeployError("Paperclip health returned invalid JSON", 500)
    if not dev.startswith("307|https://megabrain.midelim.tech/login"):
        raise DeployError(f"development auth smoke failed: {dev}", 500)
    if not status.startswith("401|"):
        raise DeployError(f"status auth smoke failed: {status}", 500)
    if pobj.get("status") != "ok":
        raise DeployError("Paperclip health smoke failed", 500)
    return {"development": dev, "statusUnauth": status, "paperclip": pobj.get("status")}

def deploy(issue, commit, patch_file):
    if not ISSUE_RE.fullmatch(issue):
        raise DeployError("invalid issue identifier")
    if not COMMIT_RE.fullmatch(commit):
        raise DeployError("commit must be a full 40-character SHA")
    if not FILE_RE.fullmatch(patch_file):
        raise DeployError("invalid patch filename")
    patch = CANDIDATES / patch_file
    if not patch.is_file():
        raise DeployError("candidate patch not found", 404)
    raw = patch.read_bytes()
    if len(raw) > MAX_PATCH:
        raise DeployError("candidate patch too large")
    m = PATCH_HEAD_RE.match(raw)
    if not m or m.group(1).decode() != commit:
        raise DeployError("patch header does not match requested commit")

    gate = accepted_gate(issue, commit)
    if not gate:
        raise DeployError("no accepted human-only deploy gate for this issue and commit", 403)

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    LOCK_FILE.touch(exist_ok=True)
    with LOCK_FILE.open("r+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = load_state()
        prior = state["approvals"].get(gate)
        if prior:
            if prior.get("status") == "succeeded":
                return prior
            raise DeployError("this approval was already consumed; create a new deploy gate", 409)

        status = run(["git", "status", "--porcelain"], cwd=PROD).stdout.strip()
        if status:
            raise DeployError("production checkout is not clean", 409)
        branch = run(["git", "branch", "--show-current"], cwd=PROD).stdout.strip()
        if not branch.startswith("deploy/"):
            raise DeployError("production checkout is not on a deploy/* branch", 409)

        rollback = run(["git", "rev-parse", "HEAD"], cwd=PROD).stdout.strip()
        run(["git", "apply", "--check", str(patch)], cwd=PROD)

        state["approvals"][gate] = {
            "status": "in_progress", "issue": issue, "commit": commit,
            "rollback": rollback, "startedAt": int(time.time())
        }
        save_state(state)

        try:
            run(["git", "am", str(patch)], cwd=PROD)
            deployed = run(["git", "rev-parse", "HEAD"], cwd=PROD).stdout.strip()
            rebuild()
            evidence = smoke()
            result = {
                "status": "succeeded", "issue": issue, "sourceCommit": commit,
                "deployedCommit": deployed, "rollback": rollback,
                "approvalInteractionId": gate, "evidence": evidence,
                "finishedAt": int(time.time())
            }
            state["approvals"][gate] = result
            save_state(state)
            return result
        except Exception as exc:
            run(["git", "am", "--abort"], cwd=PROD, check=False)
            run(["git", "reset", "--hard", rollback], cwd=PROD, check=False)
            try:
                rebuild()
                rb_smoke = smoke()
            except Exception as rb_exc:
                rb_smoke = {"rollbackSmokeError": str(rb_exc)}
            state["approvals"][gate] = {
                "status": "failed", "issue": issue, "commit": commit,
                "rollback": rollback, "error": str(exc),
                "rollbackEvidence": rb_smoke, "finishedAt": int(time.time())
            }
            save_state(state)
            raise DeployError(f"deploy failed and rollback attempted: {exc}", 500)

class Handler(BaseHTTPRequestHandler):
    server_version = "MegaBrainDeployCapability/1"
    def log_message(self, fmt, *args):
        print(fmt % args, flush=True)
    def send_json(self, code, obj):
        data = json.dumps(obj, separators=(",", ":")).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
    def do_GET(self):
        if self.path == "/health":
            return self.send_json(200, {"status": "ok"})
        self.send_json(404, {"error": "not_found"})
    def do_POST(self):
        if self.path != "/deploy":
            return self.send_json(404, {"error": "not_found"})
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size <= 0 or size > 65536:
                raise DeployError("invalid request size")
            body = json.loads(self.rfile.read(size))
            result = deploy(
                str(body.get("issue", "")),
                str(body.get("commit", "")),
                str(body.get("patchFile", "")),
            )
            self.send_json(200, result)
        except DeployError as exc:
            self.send_json(exc.status, {"error": str(exc)})
        except Exception as exc:
            self.send_json(500, {"error": "internal_error"})

if __name__ == "__main__":
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(STATE_DIR, 0o700)
    ThreadingHTTPServer((BIND, PORT), Handler).serve_forever()
