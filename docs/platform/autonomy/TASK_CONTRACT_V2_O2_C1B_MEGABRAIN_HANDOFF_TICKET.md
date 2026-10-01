# Task Contract — V2-O2-C1B: MegaBrain Handoff Ticket

## Status

- Status: READY
- Risk Level: GREEN
- Parent: V2-O2-C1
- Production mutation: NONE
- Runtime mutation: NONE

## Objective

Implement the MegaBrain-side issuance of a short-lived Paperclip handoff ticket
behind the existing owner session and CSRF boundary.

## Scope

### In

- server-side Paperclip destination configuration;
- server-side handoff signing secret configuration;
- short-lived HMAC-SHA256 ticket issuance;
- fixed audience, issuer, destination origin, owner subject/email, expiry and jti;
- POST launch endpoint protected by owner session and existing CSRF;
- 303 redirect to a fixed Paperclip exchange path;
- tests and evidence.

### Out

- no Paperclip exchange implementation;
- no DNS/Caddy/Docker changes;
- no production secret creation;
- no UI button;
- no Paperclip public exposure;
- no agent/model execution.

## Security Requirements

- keep `__Host-mb_session` unchanged and host-only;
- never include MegaBrain session token or Google tokens in the handoff ticket;
- require HTTPS destination origin from server configuration;
- reject secrets shorter than 32 bytes;
- 90-second fixed TTL;
- HMAC key domain-separated for this handoff use;
- no caller-provided redirect origin;
- owner session and CSRF both required;
- launch response is `no-store, private` with `Referrer-Policy: no-referrer`;
- configuration failure is generic and does not leak details.

## Acceptance Criteria

- focused handoff/auth/owner tests pass;
- full FastAPI service test suite passes;
- no real secret values are added;
- no production configuration changes;
- `git diff --check` passes;
- only scoped files are committed.

## Human Gate

C1-C Paperclip exchange implementation requires review before proceeding.

## Verdict

Implementation evidence complete. Focused validation: 24 passed. Full FastAPI service suite: 345 passed. No production/runtime mutation occurred.

`MEGABRAIN_HANDOFF_ISSUER_READY`
