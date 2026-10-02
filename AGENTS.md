# MegaBrain Agent Instructions

## Project

MegaBrain is an automation and knowledge-processing project.

The current repository contains the infrastructure and services used by the
project.

## Roles

The accepted engineering direction is recorded in D022 in docs/DECISIONS.md.
Paperclip is the task planning and tracking surface. Runtime authority remains
with the existing native adapter or AP0 contract selected for that task; this
document does not migrate registry records or grant additional capabilities.

### Task owner / planner

One accountable owner prepares the Task Contract and its compact Task Packet,
resolves material ambiguities, selects the permitted executor, and links the
worktree, base commit, checkpoints, review, and release evidence to the task.
Paperclip is a platform, not the model that makes these planning decisions.

### Hermes

Hermes is the preferred executor for integrations, research, and automations
under the assigned task. Existing AP0 coordinator processes remain bounded
runtime components under their contracts until an explicit validated migration.
Hermes must not create a competing task queue or become the only durable store
of engineering context.

### Codex

Codex is the preferred implementation worker for scoped code changes. It reads
the task packet, applicable instructions and accepted decisions, verifies the
Git context, implements, validates, and records evidence and checkpoints.

### Reviewer

Review runs in a separate session and evaluates the original objective,
candidate revision, acceptance criteria and evidence. A summary from the author
is not sufficient review evidence. Design review compares against the accepted
visual reference. Automated tests do not establish visual product approval.

Initially only one implementation is active. Specialist skills are invoked
when scope or risk calls for them; do not create permanent agents for every role.
At most two distinct correction attempts are made for the same blocker before
checkpointing and escalating. A quota pause preserves state before resumption.

## Git Workflow

Stable branches:

- `main`: stable baseline.
- `dev`: integration and development baseline.

Agent work must use branches under:

`agent/*`

GitHub (`mide-lim/megabrain`) is the development source of truth.

Hermes may use the repository-scoped GitHub App to:

- push work only to `agent/*`;
- open pull requests from `agent/*`.

Agents must not:

- push directly to `dev`;
- push directly to `main`;
- merge into `dev`;
- merge into `main`;
- rebase protected branches;
- use owner-level GitHub credentials.

Commits may be created on `agent/*` as part of the active scoped task.

## Security Boundaries

Agents must not:

- use `sudo`;
- access production secrets;
- access `/home/megabrain/megabrain`;
- access `infra/.env`;
- control the Docker daemon;
- execute production deployments;
- modify persistent production data.

The production data directory `infra/data/` is not part of the development
workspace.

## Change Policy

Before modifying anything:

1. inspect the relevant files;
2. verify the active Git branch;
3. confirm the working tree state;
4. keep the requested scope minimal.

After modifications:

1. run relevant validations;
2. inspect `git status`;
3. inspect the diff;
4. report files changed;
5. report commands executed;
6. report known risks or limitations.

Do not introduce unrelated refactoring.

## Documentation

Project context is maintained under `docs/`.

Start context discovery with `docs/CONTEXT.md`; it maps current references,
known drift, accepted direction D022, and the task-packet/resumption workflow.
Distinguish chosen direction from deployed capability. It grants no new runtime
or production authority.

When available, consult:

- `docs/ARCHITECTURE.md`
- `docs/CURRENT_STATE.md`
- `docs/ROADMAP.md`
- `docs/DECISIONS.md`

These documents describe the project's architecture, current state, planned
work, and important technical decisions.
