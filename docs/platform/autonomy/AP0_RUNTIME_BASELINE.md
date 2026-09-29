# AP0-TC0 — Runtime Foundation Baseline

Captured at: 2026-09-29T11:50:46Z
Scope: read-only discovery. No production mutation, cleanup, system-configuration change, process termination, Docker action, Git cleanup, deployment, push, PR, or merge was performed.

Evidence labels:

- VERIFIED: directly observed from the host process table, `/proc`, listeners, systemd metadata, Git metadata, filesystem metadata, or versioned repository configuration.
- INFERRED: a conclusion drawn from verified evidence; it is not a claim of runtime configuration or ownership.
- UNKNOWN: not established by the permitted read-only evidence.

## 1. Current topology

- VERIFIED — The canonical development repository is `/home/megabrain-hermes/workspace/megabrain`; its `origin` is `https://github.com/mide-lim/megabrain.git`.
- VERIFIED — At capture time the canonical worktree was on `agent/f5-1-inbox-functional`, HEAD `116c98372b49ac474545731ebdb956acb5e4f709`, clean, and `[ahead 1]` of `origin/dev`.
- VERIFIED — A Docker Engine daemon is active (PID 3553), systemd-enabled, and has container shims plus host TCP proxies for ports 80 and 443.
- VERIFIED — Caddy is running in a Docker cgroup and the host proxies TCP 80/443 to container address `172.18.0.4`.
- VERIFIED — PostgreSQL, n8n, three Uvicorn service instances, and one containerized Next server are present in Docker cgroups.
- INFERRED — Those processes correspond to the seven services declared by `infra/docker-compose.yml`: `postgres`, `n8n`, `caddy`, `downloader`, `enricher`, `web`, and `frontend`.
- VERIFIED — Two separate host-owned Next servers listen on TCP 3100 and TCP 37891 from the canonical `apps/web` worktree. They are development-preview candidates, not declared production containers.
- VERIFIED — A long-lived Hermes process, multiple detached Codex sandbox/test chains, source worktrees, cache trees, and backups coexist under the `megabrain-hermes` account.

## 2. Hermes runtime

### Runtime identity and process state

- VERIFIED — Effective discovery user: `uid=1001(megabrain-hermes)`, primary group `gid=1001(megabrain-hermes)`, supplementary groups `users` and `megabrain-git`.
- VERIFIED — The discovered persistent Hermes executable is PID 1610802, command `/home/megabrain-hermes/.hermes/hermes-agent/venv/bin/python /home/megabrain-hermes/.hermes/hermes-agent/hermes`.
- VERIFIED — Hermes PID 1610802 started on 2026-08-24 01:07:50 UTC; its PPID is 1, session ID is 1609411, process group is 1610802, and cgroup is `user.slice/user-0.slice/session-4633.scope`.
- VERIFIED — At capture time its Linux state was `T (stopped)`, with 9 threads, 1,632 KiB resident memory, and no direct children.
- VERIFIED — Its current working directory is the separate `megabrain-private-archive-20260902` workspace, not the canonical MegaBrain worktree.
- VERIFIED — The Hermes source checkout exists at `~/.hermes/hermes-agent`, is on `main...origin/main`, and is at commit `1b91b8eaa576b3c3dfe08e4592bdd698d1aca019`.
- VERIFIED — The process has `/dev/pts/1 (deleted)` for standard streams and holds `~/.hermes/logs/agent.log.2`, `~/.hermes/logs/errors.log`, `~/.hermes/state.db`, `state.db-wal`, and `state.db-shm` open.
- VERIFIED — The readable environment contains ordinary shell/session keys (`HOME`, `PATH`, `PWD`, `SHELL`, `TERM`, `USER`) and `SUDO_*` provenance keys. No `HERMES_HOME` key was present in that process environment.
- UNKNOWN — The original launcher command, the exact environment-file source, and the intended owner/task associated with the stopped Hermes process are not reconstructable from the permitted snapshot.

### Persistence, restart, and shutdown

- VERIFIED — `hermes.service` does not exist, and systemd returned zero installed or active unit files matching `hermes*`.
- VERIFIED — The current account has no crontab. No tmux session and no screen socket exist for `megabrain-hermes`.
- VERIFIED — User-systemd inspection from this session failed with `Failed to connect to bus: No medium found`; therefore it did not establish user-unit absence.
- INFERRED — PID 1610802 was launched from an interactive/detached user-session context and later reparented to PID 1; no managed restart owner was demonstrated.
- UNKNOWN — Restart behavior after Hermes exits or after host reboot.
- UNKNOWN — Graceful shutdown procedure, signal policy, session preservation policy, and whether another service/unit with a non-Hermes name owns this process.

### Other persistence mechanisms observed

- VERIFIED — `cron.service` is active/running and enabled. `/etc/cron.d` includes host-level Docker builder/image prune jobs, filesystem scrub, Monarx update, and sysstat schedules.
- VERIFIED — Docker is active/running and enabled.
- VERIFIED — The host has active systemd timers, including `systemd-tmpfiles-clean.timer`; these are generic host timers, not a demonstrated owner lifecycle for Hermes tasks.

## 3. Processes

Classification is intentionally limited to `ACTIVE_KNOWN`, `ACTIVE_UNKNOWN`, `STALE_CANDIDATE`, and `UNKNOWN`. “Stale candidate” is a review classification only; it is not an authorization to terminate anything.

### Hermes and production-runtime processes

| Classification | Process / evidence | Owner / task evidence |
|---|---|---|
| ACTIVE_UNKNOWN | Hermes PID 1610802 is stopped, PPID 1, in a user-session cgroup, with no direct children. | No service, task ID, or launcher record was demonstrated. |
| ACTIVE_KNOWN | Docker daemon PID 3553; Caddy PID 502279; PostgreSQL master PID 30805; n8n PID 1447747; three Uvicorn application instances; containerized Next server PID 2405911. | Docker/cgroup ownership is verified; exact service-to-container mapping and Compose project state require Docker API access. |
| ACTIVE_UNKNOWN | n8n PID 1447747 has been running about 2.88 days, RSS about 321 MiB; its task runner PID 1447862 is a child. | Versioned architecture declares n8n as the product orchestrator, but no production ownership metadata was read. |

### Codex and test-worker census

- VERIFIED — Fourteen detached `codex-linux-sandbox` parents and fourteen active pytest-related descendants existed immediately before the final capture. Every listed sandbox parent had PPID 1 and user `megabrain-hermes`.
- VERIFIED — Ten sandbox/test chains target `services/enricher`; their start times are 2026-08-25 or 2026-08-26, their process RSS is 8 KiB for each sandbox and 348 KiB for each Python pytest descendant, and they are in the old archive worktree at runtime.
- VERIFIED — Four sandbox/test chains target `services/web`; their start times are 2026-08-30, each parent has 8 KiB RSS, each Python pytest descendant has 3,608 KiB RSS, and they are in the old archive worktree at runtime.
- VERIFIED — The sandbox command lines declare canonical-worktree sandbox/command paths but `/proc/<pid>/cwd` resolves to `megabrain-private-archive-20260902`. This is a verified launch-context/runtime-CWD mismatch.
- VERIFIED — All fourteen test descendants are in sleeping states rather than terminated. Their commands are bounded pytest/compile/diff-check commands, not servers.
- VERIFIED — No task identifier, branch, timeout, heartbeat, TTL, supervisor, or cleanup record is embedded in the observed commands.
- INFERRED — The fourteen Codex/test chains are stale candidates: they are 29–34 days old for normally finite test commands, detached under PID 1, and execute against an archive worktree.
- UNKNOWN — Whether any chain is intentionally paused, blocked on an external resource, or still owned by a human/task record outside the inspected host state.

### Worker details by command family

| Classification | PIDs | User | Age at capture | CWD | Command family | Task/branch evidence |
|---|---:|---|---|---|---|---|
| STALE_CANDIDATE | 2041266, 2041480, 2200086, 2200214, 2200538, 2205016, 2205128, 2205409, 2206457, 2207046 plus pytest descendants | megabrain-hermes | 33–34 days | archive `services/enricher` | Codex sandbox → pytest / compileall / diff check | No task ID; command declares canonical `services/enricher` but runtime CWD is archive. |
| STALE_CANDIDATE | 3445238, 3445408, 3445676, 3445769 plus pytest descendants | megabrain-hermes | about 29 days | archive `services/web` | Codex sandbox → pytest Web/CSRF/health selections | No task ID; command declares canonical `services/web` but runtime CWD is archive. |
| ACTIVE_UNKNOWN | 2761289→2761290 | megabrain-hermes | about 19.5 days | canonical `apps/web` | `next start` → Next 16.3.4 | No task ID or branch-at-launch record. |
| ACTIVE_UNKNOWN | 3106834→3106835 | megabrain-hermes | about 18.7 days | canonical `apps/web` | `next start -p 37891` → Next 16.3.4 | No task ID or branch-at-launch record. |

## 4. Previews

- VERIFIED — TCP 3100 listens on all interfaces and belongs to Next PID 2761290. Its parent command is `next start`; current CWD is canonical `apps/web`; it started on 2026-09-09 23:34:37 UTC.
- VERIFIED — TCP 37891 listens on all interfaces and belongs to Next PID 3106835. Its parent command is `next start -p 37891`; current CWD is canonical `apps/web`; it started on 2026-09-10 20:08:40 UTC.
- VERIFIED — Neither preview is a Docker container process; their cgroups are historical user-session scopes (`session-7641.scope` and `session-7772.scope`).
- INFERRED — Both are development-preview processes rather than production services because the versioned Compose file defines the production frontend inside Docker and exposes no host port for it.
- UNKNOWN — Which task created either preview, the branch/commit at launch time, intended TTL, health/heartbeat, caller-visible URL, and stop/cleanup owner.
- VERIFIED — No versioned preview lifecycle policy was located in the inspected repository documentation. Existing autonomous-lifecycle documents cover bounded GitHub/PR work, not host preview creation/destruction.

## 5. Git / worktrees

### Canonical repository

- VERIFIED — Canonical repository: `/home/megabrain-hermes/workspace/megabrain`.
- VERIFIED — Remote: `origin = https://github.com/mide-lim/megabrain.git`.
- VERIFIED — Branch/HEAD at capture: `agent/f5-1-inbox-functional` / `116c98372b49ac474545731ebdb956acb5e4f709`.
- VERIFIED — Canonical worktree was clean before this baseline document was created; no `.lock` files were found under its Git directory at that time.

### Registered worktrees

- VERIFIED — Sixteen worktrees are registered in the canonical repository: one canonical branch worktree, nine named `agent/*` branch worktrees, and six detached review/install worktrees.
- VERIFIED — The detached worktrees are `megabrain-r2b-10c7-install-source`, `r2b10c3-install-78fbe068`, and four worktrees under `workspace/reviews/`.
- VERIFIED — Every registered worktree had an empty Git short-status output and no directly checked `index.lock`, `HEAD.lock`, or `packed-refs.lock` at capture.
- VERIFIED — Branches materially behind `origin/dev` include `agent/context-continuity-foundation` (behind 27), `agent/r2b-10-p2-state-commit-fix` (behind 21), `agent/r2b-10-p2-state-commit-fix-refresh` (behind 20), and `agent/r2b-real-lifecycle-validation` (behind 21).
- INFERRED — Detached install/review worktrees and materially behind agent branches are stale-worktree candidates for later ownership review; staleness is not a deletion criterion.
- UNKNOWN — The task owner, retention policy, PR state, or external evidence reference for each registered worktree.

### Non-registered nearby workspaces

- VERIFIED — `workspace/megabrain-private-archive-20260902` and `workspace/megabrain-public-candidate` exist alongside the registered worktrees; the former is used as the live CWD of Hermes and all discovered Codex/test chains.
- UNKNOWN — Whether these nearby noncanonical directories have formal retention/ownership records.

## 6. Storage

All sizes are logical file sums observed at capture; they are not an authorization for cleanup.

| Classification | Location | Observed size / contents | Ownership evidence |
|---|---|---:|---|
| TEMPORARY | `/tmp` | 1,228,675,929 bytes; 60,960 files; oldest observed item from 2026-08-23 | No task ownership metadata was discovered. |
| RUNTIME_DATA | `~/.hermes/cache` | 719,083,554 bytes; 13,956 files; active `scratch`, terminal output, browser, delegation, and web cache subtrees | Hermes cache naming only; task-level ownership/TTL is unknown. |
| RUNTIME_DATA | `~/.hermes/state.db` family | Open by Hermes PID 1610802 | Persistent Hermes state artifact. |
| TOOL_CACHE | `~/.npm` | 1,712,725,927 bytes | Tool-cache location; no per-task mapping. |
| TOOL_CACHE | `~/.cache/pip` | 118,734,873 bytes | Tool-cache location; no per-task mapping. |
| TOOL_CACHE | `~/.cache/uv` | 3,302,442,303 bytes | Tool-cache location; no per-task mapping. |
| BUILD_CACHE | canonical `apps/web/.next` | 148,330,786 bytes | Associated with canonical frontend worktree, not a task ID. |
| TOOL_CACHE | canonical `apps/web/node_modules` | 461,943,264 bytes | Associated with canonical frontend worktree, not a task ID. |
| BACKUP | `~/.hermes/backups` | 476,010,300 bytes, 10 files | Backup-named directory; retention policy unknown. |
| BACKUP | `~/.hermes/.curator_backups` | 453,364 bytes, 87 files | Backup-named directory; retention policy unknown. |
| UNKNOWN | `workspace/evidence` | 127,326 bytes, 17 files | Evidence directory exists; task association not inspected. |
| UNKNOWN | `workspace/reviews` | 557,173,859 bytes, 25,325 files | Corresponds partly to detached review worktrees; each item’s owner/TTL unknown. |
| RUNTIME_DATA | Docker filesystem / socket | `/var/lib/docker` is root-only (`0710`); Docker socket is `0660 root:docker` | Docker data cannot be enumerated by this account. |

- VERIFIED — No `agent-browser` or `ms-playwright` cache directory was present in the probed user locations.
- VERIFIED — `~/.hermes/audio_cache` and `~/.hermes/image_cache` exist but were empty at capture.
- UNKNOWN — Docker image, volume, builder-cache, and release-artifact sizes, because Docker API access is denied and the Docker root is not readable.

## 7. Docker

### Verified host runtime

- VERIFIED — `docker.service` is active/running, enabled, and has main PID 3553.
- VERIFIED — Direct Docker API access is denied to `megabrain-hermes`: `permission denied while trying to connect to the Docker API at unix:///var/run/docker.sock`.
- VERIFIED — The current account is not in the Docker socket’s `docker` group; the socket is `0660 root:docker`.
- VERIFIED — Seven active `containerd-shim-runc-v2` processes were observed, consistent with a seven-container runtime.
- VERIFIED — Caddy runs as PID 502279 and Docker host proxies publish 80 and 443 on IPv4 and IPv6.
- VERIFIED — PostgreSQL runs as PID 30805 with standard checkpointer, background writer, WAL writer, autovacuum, and logical-replication children.
- VERIFIED — n8n runs as PID 1447747 with task runner PID 1447862.
- VERIFIED — Three application Uvicorn pairs run in separate Docker cgroups, all on container port 8000; one containerized Next server is also present.
- UNKNOWN — Live Docker container names, project name, network membership, mounts, actual restart policies, health status, image digests, and container labels, because the Docker API is inaccessible.

### Versioned declarative production topology

The following statements are VERIFIED as repository configuration, not as runtime inspection:

- VERIFIED — `infra/docker-compose.yml` declares the seven-service project described above on bridge network `megabrain-network`.
- VERIFIED — The file declares `restart: unless-stopped` for every service.
- VERIFIED — The file declares PostgreSQL data at `./data/postgres`, n8n data at `./data/n8n`, and Caddy data/config at `./data/caddy/data` and `./data/caddy/config`.
- VERIFIED — Caddy declares host port publication `80:80` and `443:443`; frontend only declares internal exposure `3000` and Web has no host `ports` entry.
- VERIFIED — PostgreSQL, downloader, enricher, Web, and frontend have healthcheck definitions in the Compose file; n8n and Caddy do not declare healthchecks there.
- VERIFIED — Enricher declares a read-only bind mount for a Google credential file and a `/tmp` tmpfs.
- VERIFIED — The Compose file references production secret variables for PostgreSQL, n8n encryption, R2, API keys, OIDC, and service-to-service dispatch. Values were not read.

## 8. Production boundary

- VERIFIED — Versioned architecture and Compose configuration designate Caddy as external HTTPS/routing ingress; frontend and Web are internal Docker-network services.
- VERIFIED — Host evidence confirms only 80/443 are Docker-published for the observed Caddy runtime.
- VERIFIED — The Caddyfile routes presentation paths to `frontend:3000`, default application paths to `web:8000`, and protects named internal n8n-dispatch webhook paths with 404 responses.
- VERIFIED — Repository policy (`AGENTS.md`) explicitly forbids agents from sudo, production secrets, the production workspace, `infra/.env`, Docker control, deployments, and persistent production-data mutation.
- VERIFIED — The discovery account lacks Docker API access; this is an enforced boundary at the Docker socket.
- INFERRED — A future autonomous development worker should be made to inherit the same absence of production PostgreSQL credentials, Docker socket access, root shell, production secrets, unrestricted n8n access, and unrestricted cloud credentials.
- UNKNOWN — Whether other users, groups, mounted credentials, service accounts, or external/cloud identities grant a future worker any of the prohibited capabilities.

## 9. Security baseline

- VERIFIED — SSH is active/running (MainPID 3742444) while its unit file state is `disabled`; an active `ssh.socket` was also listed by systemd.
- VERIFIED — TCP 22 listens on IPv4 and IPv6. TCP 80 and 443 listen on IPv4 and IPv6 through Docker proxies.
- VERIFIED — TCP 3100 and 37891 listen on all interfaces for host Next preview candidates.
- VERIFIED — TCP 65529 listens only on loopback; process ownership was not available from the unprivileged socket snapshot.
- VERIFIED — UFW’s unit is enabled and reports active/exited.
- UNKNOWN — Effective firewall policy/rules, because `ufw status verbose` requires root from this account.
- VERIFIED — Fail2ban has no loaded unit (`LoadState=not-found`) and reports inactive/dead.
- UNKNOWN — SSH `PermitRootLogin`, password authentication, public-key authentication, and other effective SSH modes. `sshd -T` could not read root-owned `/etc/ssh/sshd_config.d/50-cloud-init.conf`.
- VERIFIED — SSH configuration metadata: `/etc/ssh/sshd_config` is `0644 root:root`; its include directory is `0755 root:root`; the cloud-init include is `0600 root:root`.
- UNKNOWN — Full Docker published-port inventory from container metadata. The host process evidence confirms 80/443 only; it does not substitute for Docker inspect.

## 10. Risks

- VERIFIED — A stopped, PPID-1 Hermes process remains associated with an archived worktree and an unavailable deleted terminal. No restart/shutdown owner was demonstrated.
- VERIFIED — Fourteen detached finite Codex/pytest chains have survived for roughly one month, run in an archive CWD, lack task IDs/TTLs/heartbeats, and remain attached to PID 1.
- VERIFIED — Two host Next preview listeners are publicly bound on all interfaces and have no discovered lifecycle/owner metadata.
- VERIFIED — The workspace contains numerous historical agent/review worktrees and archive directories without a demonstrated retention or task-ownership registry.
- VERIFIED — Generic host cron performs Docker builder/image pruning outside a demonstrated MegaBrain task ownership model.
- INFERRED — These conditions make resource leakage and accidental cross-task interference likely if unattended autonomy is expanded without an explicit finite-task/resource contract.
- UNKNOWN — Whether the observed stale candidates are protected by an external operating procedure; no such record was read.

## 11. Stale candidates

No candidate was changed.

| Candidate | Classification | Evidence | Missing ownership/lifecycle fields |
|---|---|---|---|
| Hermes PID 1610802 | UNKNOWN | Stopped since the 2026-08-24 session, PPID 1, archive CWD, no Hermes unit found | launcher, owner, task ID, restart/shutdown policy, heartbeat |
| 14 Codex sandbox parents + 14 pytest descendants | STALE_CANDIDATE | finite test commands; 29–34 days old; PPID 1 parents; archive CWD; no task IDs | owner, task ID, creation record, TTL, heartbeat, completion/cleanup result |
| Next preview PID 2761290 / port 3100 | ACTIVE_UNKNOWN | listening, canonical CWD, user-session cgroup, about 19.5 days old | task ID, branch/commit at launch, TTL, health, stop owner |
| Next preview PID 3106835 / port 37891 | ACTIVE_UNKNOWN | listening, canonical CWD, user-session cgroup, about 18.7 days old | task ID, branch/commit at launch, TTL, health, stop owner |
| Detached review/install worktrees | STALE_CANDIDATE | six detached registered worktrees; no locks; no task retention evidence | owner, PR/evidence relation, expiry, cleanup policy |
| Behind agent worktrees | STALE_CANDIDATE | four named agent branches are 20–27 commits behind `origin/dev` | owner, intended baseline, task completion/retention policy |
| `/tmp`, Hermes cache, review tree, tool caches | UNKNOWN | sizeable persistent content and old entries; no task records | owner, task ID, creation time, TTL, cleanup policy |

## 12. Unknowns

- UNKNOWN — The authoritative owner and lifecycle contract for the persistent Hermes process.
- UNKNOWN — The authoritative task ledger linking process PIDs, worktrees, previews, artifacts, and cache entries to task IDs.
- UNKNOWN — Docker project metadata, container labels, exact live mounts, network, healthchecks, restart policies, image digests, and volume/image/cache inventory.
- UNKNOWN — The exact production Compose deployment path and whether the versioned Compose file is byte-identical to the live deployment.
- UNKNOWN — Effective SSH authentication policy and UFW rules.
- UNKNOWN — Whether 3100 and 37891 are reachable beyond the observed host listeners.
- UNKNOWN — Release-artifact ownership/retention policy.
- UNKNOWN — Whether generic host cron/prune activity is sanctioned as part of an autonomous-runtime cleanup model.

## 13. Recommended AP0-TC1 scope

AP0-TC1 should be a separately authorized, still read-only control-plane discovery/definition task. It should not terminate, prune, restart, deploy, or modify configuration.

1. Define the canonical finite-task record: immutable `task_id`, human/agent owner, creation time, intended worktree/branch/base/commit, permitted tools, resource budget, state, heartbeat, expiry, and terminal result.
2. Define a resource registry keyed by task ID for workers, sandboxes, preview ports, worktrees, temporary directories, evidence artifacts, and delegated runs. Each entry must identify owner, creation time, state, heartbeat where applicable, TTL, and deterministic cleanup policy.
3. Define an admission/termination state machine: `CREATED`, `RUNNING`, `HEARTBEAT_MISSED`, `TERMINAL`, `EXPIRED_PENDING_REVIEW`, and `CLEANED`, with explicit human authorization boundaries for any destructive action.
4. Specify a preview lease protocol: allocated port, bound interface, process PID/process group, branch/commit, health endpoint, TTL, one task owner, and deterministic teardown only after an authorized future cleanup contract.
5. Specify a worktree lease protocol: canonical worktree versus task worktree, task owner, branch/base/HEAD, dirty/lock state, evidence/PR linkage, expiry, and retention classification. Detached reviews/install sources need explicit retention semantics.
6. Specify a sanitized read-only Docker-observability mechanism that exposes container identity, labels, network, mounts, restart policy, health, and published ports without granting development workers unrestricted Docker control.
7. Specify a security-observability evidence channel for effective SSH modes and firewall rules that remains read-only and does not expose secrets.
8. Establish a single audit-safe discovery snapshot format so a future TC can compare PIDs, listeners, worktrees, cache locations, and ownership state without relying on heuristic process names.

## Final verdict

AP0_TC0_BLOCKED

Reason: the baseline documents meaningful host evidence and identifies high-confidence stale candidates, but it cannot canonically establish Docker runtime metadata, effective SSH/firewall policy, or task ownership/lifecycle for the persistent Hermes process, detached Codex chains, previews, worktrees, and temporary artifacts. No remediation was performed or authorized.
