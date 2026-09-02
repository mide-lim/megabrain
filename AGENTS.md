# MegaBrain Agent Instructions

## Project

MegaBrain is an automation and knowledge-processing project.

The current repository contains the infrastructure and services used by the
project.

## Roles

### Hermes

Hermes acts as the coordinator.

Responsibilities:

- understand the requested objective;
- inspect the current project state;
- break work into small tasks;
- delegate implementation work to Codex when appropriate;
- review Codex output;
- verify Git status and diffs;
- report risks and results to the user.

Hermes should not silently replace Codex when a task was explicitly delegated
to Codex.

### Codex

Codex acts as the implementation worker.

Responsibilities:

- inspect the relevant code;
- implement the requested scoped change;
- run appropriate tests and validations;
- report files changed and commands executed.

## Git Workflow

Stable branches:

- `main`: stable baseline.
- `dev`: integration and development baseline.

Agent work must use branches under:

`agent/*`

Agents must not:

- push to the central repository;
- merge into `dev`;
- merge into `main`;
- rebase protected branches.

Commits may be created locally when explicitly requested.

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

When available, consult:

- `docs/ARCHITECTURE.md`
- `docs/CURRENT_STATE.md`
- `docs/ROADMAP.md`
- `docs/DECISIONS.md`

These documents describe the project's architecture, current state, planned
work, and important technical decisions.
