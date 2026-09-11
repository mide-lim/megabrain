# Task Contract — F1: Authentication Foundation

## Status

- Status: SPEC_READY
- Risk Level: YELLOW

Application implementation is Yellow: it adds a security-sensitive backend feature, endpoints,
a dependency, direct database SQL, and a material application contract. Migration creation and
review are Yellow, but the `infra/**` path is human-gated for F1. Production migration execution,
real secret provisioning, production database grants, production Caddy or Basic Auth changes, and
deployment are Red and require separate explicit human authorization.

## Objective

Implement a FastAPI-owned authentication foundation using Google OpenID Connect for one configured
owner, with PostgreSQL-backed local MegaBrain sessions.

F1 provides backend authentication primitives without changing public production routing or
removing Caddy Basic Auth.

## User / Product Context

Current MegaBrain Web is protected by Caddy Basic Auth. Next.js exists as the future UI and
rendering layer but is not currently publicly routed. F1 replaces neither Caddy nor Basic Auth in
production.

F1 establishes application-level identity and session infrastructure before F2 builds the visual
login experience. FastAPI remains the backend, domain, authentication, and authorization authority.

## Scope

### In

- `Authlib==1.8.0` behind a small FastAPI application adapter boundary.
- Google OpenID Connect Authorization Code Flow with `openid email` scopes.
- PKCE S256, required state, and required nonce.
- Explicit Google ID-token claim policy for issuer, audience, conditional `azp`, expiry, nonce,
  subject, email, and literal-boolean `email_verified`.
- Owner bootstrap through `AUTH_OWNER_EMAIL`.
- Durable validated Google `(provider_issuer, provider_subject)` binding.
- Database-backed, short-lived, one-time OIDC transactions.
- Opaque local MegaBrain sessions with SHA-256 session-token persistence only.
- Seven-day absolute session lifetime (604800 seconds).
- `GET /api/auth/session` introspection endpoint.
- Current-session logout with existing double-submit CSRF protection.
- Reusable safe local return-path validation.
- Callback secret-log protection with production Uvicorn `--no-access-log`.
- Additive authentication schema design and direct parameterized psycopg SQL.
- Least-privilege runtime database access contract.
- Hermetic tests with mocked provider interaction only.

### Out

- Login UI and F2 visual experience.
- Auth.js, NextAuth, or any Next.js authentication implementation.
- Google API access.
- Google access-token, refresh-token, ID-token, authorization-code, or provider-claim persistence.
- JWT application sessions.
- Authentication storage in localStorage or sessionStorage.
- Password authentication, invitations, multi-user management, or automated account recovery.
- Automatic owner rebinding; manual reset/rebinding is a future human-gated operator procedure.
- `hd`-based authorization.
- External authentication gateways.
- Caddy routing changes, Basic Auth removal, or public Next.js cutover.
- Production deployment, real Google OAuth credentials, production migration execution, or
  production grants.
- Session-row cleanup scheduler.
- `/api/health` to `/healthz` migration.

## Acceptance Criteria

F1 application implementation is ready only when all of the following have evidence:

- Google OIDC protocol behavior is hermetically tested with Authorization Code Flow, S256 PKCE,
  state, nonce, and no live Google calls.
- The explicit Google claim policy is tested for issuer, audience, conditional `azp`, expiry,
  nonce, subject, email, and literal `email_verified`.
- First-owner bootstrap is race-safe, durable issuer+subject identity is enforced, and a different
  subject cannot silently rebind through a current or previous email.
- Local sessions are database-backed, opaque, concurrent-session capable, and persist only a
  SHA-256 token hash.
- Provider tokens are not persisted; transaction verifier, state, nonce, raw session token, and
  callback secrets do not appear in browser storage, response bodies, or logs.
- Logout and existing curation CSRF tests pass; logout revokes only the presented local session.
- Callback access-log leakage is prevented, including evidence that the production Uvicorn command
  contains `--no-access-log`.
- The additive migration schema is reviewed and the runtime privilege contract remains
  least-privilege.
- Existing Web tests and frontend lint, typecheck, tests, and build pass.
- Basic Auth remains, Caddy remains unchanged, no production action occurred, and no real
  credential or secret entered source control.

## Architecture / Technical Plan

### Authority and flow

```text
Google
  |
  | OIDC Authorization Code + PKCE
  v
FastAPI
  |
  +--> auth_transactions
  |
  +--> auth_users
  |
  +--> auth_sessions
            |
            v
     __Host-mb_session
            |
            v
         Browser
```

- Google is external identity provider only.
- FastAPI owns authentication, authorization, OIDC, identity binding, local sessions, and logout.
- PostgreSQL persists transactions, identities, and sessions.
- Next.js is UI/rendering only.
- Browser receives only the opaque local session token.
- Caddy remains unchanged during F1.

### Locked OIDC contract

- Library: `Authlib==1.8.0`.
- Flow: Authorization Code.
- Scopes: `openid email`.
- Required: state, nonce, PKCE S256.
- Google access token: transient only.
- Google refresh token: neither requested nor persisted.
- Google ID token: validated and discarded.
- Authorization code: transient only.
- Provider-token persistence: none.

The Authlib adapter constructs the authorization request, uses fixed Google discovery metadata,
exchanges the code with the server-side verifier, handles JWKS/ID-token parsing, and produces a
narrow validated-claims result. Application logic outside that adapter must not depend on
Authlib-specific objects. The adapter does not own MegaBrain transaction state, owner policy,
return paths, cookies, or local sessions.

### Callback request contract

`GET /auth/callback` accepts exactly one logical callback shape:

- SUCCESS: `code` and `state`.
- PROVIDER FAILURE: `error` and `state`.

It rejects `code` without `state`, `error` without `state`, `code` together with `error`, and a
request with neither `code` nor `error`.

Both valid shapes require the transaction cookie, valid transaction state, unexpired transaction,
and unconsumed transaction. The transaction is atomically consumed and its cookie is cleared in
both branches. A provider-error callback performs no token exchange, exposes only a generic
failure category, and ignores `error_description` and other provider details. A replay fails
without contacting Google.

For a success callback, consumption occurs before provider token exchange. The returned nonce and
PKCE verifier are used only for the one exchange and ID-token validation. A successful owner
binding creates a local session, clears `__Host-mb_oidc`, sets `__Host-mb_session`, and redirects
only to the validated local return path stored in the consumed transaction.

### Identity contract

The durable external identity key is `(provider_issuer, provider_subject)`, where
`provider_subject` is validated Google `sub`.

Bootstrap sequence:

1. Validate Google identity claims.
2. Require `email_verified is True` as a literal boolean.
3. Normalize the email with `email.strip().casefold()`.
4. Require normalized email equal to normalized `AUTH_OWNER_EMAIL`.
5. Atomically create the first owner binding.

After binding, issuer+subject is authoritative. A verified email change for the same
issuer+subject does not transfer identity. A different subject presenting the configured or a
previous email is denied. There is no automatic rebinding; manual owner reset/rebinding is a
future human-gated operator procedure. F1 does not use `hd`.

Application normalization is the sole normalization contract: trim whitespace and Unicode
casefold. Store both `email` and `email_normalized`. Database constraints require both values to
be non-empty and enforce the F1 uniqueness invariant, but must not assert
`email_normalized = lower(btrim(email))`, because PostgreSQL `lower()` and Python Unicode
`casefold()` are not equivalent.

### Session contract

Session tokens are cryptographically secure opaque values with at least 256 bits of entropy. The
browser receives the raw token; PostgreSQL stores only `SHA-256(raw_token)`.

`__Host-mb_session` has Secure, HttpOnly, SameSite=Lax, Path=/, omitted Domain, and
Max-Age=604800. Sessions have a 604800-second absolute lifetime, no idle extension, no
per-request rotation, no JWT, and no localStorage/sessionStorage. Concurrent sessions are
allowed. Logout revokes the current presented session only and is idempotent.

### OIDC transaction contract

`__Host-mb_oidc` contains only an opaque random transaction identifier, with TTL 600 seconds.
The database stores SHA-256 hashes of transaction identifier and state, plus nonce, PKCE verifier,
validated local return path, created/expires timestamps, and consumption timestamp.

The PKCE verifier is stored directly in the short-lived server-side transaction row. No custom
encryption layer and no `AUTH_TRANSACTION_ENCRYPTION_KEY` are introduced. The verifier must never
appear in browser storage, cookie content, response body, or application logs.

Transaction consumption must be an atomic state transition from unconsumed to consumed, conditioned
on transaction-cookie hash, state hash, and unexpired timestamp. It occurs before provider token
exchange. A replay receives no transaction material and must not contact Google.

### Database contract

Planned additive schema:

```text
app.auth_users
  id
  provider
  provider_issuer
  provider_subject
  email
  email_normalized
  created_at
  updated_at
  last_login_at
  disabled_at

app.auth_sessions
  token_hash
  user_id
  created_at
  expires_at
  revoked_at

app.auth_transactions
  transaction_hash
  provider
  state_hash
  nonce
  pkce_verifier
  return_path
  created_at
  expires_at
  consumed_at
```

Required `app.auth_users` invariants are `provider = 'google'`,
`UNIQUE(provider_issuer, provider_subject)`, non-empty email fields, and database-enforced F1
single-owner uniqueness. `app.auth_sessions.token_hash` and transaction/state hashes are fixed
32-byte SHA-256 `BYTEA` values. Expiry and revocation/consumption timestamp ordering must be
checked by the schema.

The planned migration filename is `infra/postgres/migrations/003_f1_authentication_foundation.sql`.
It is not created by this Task Contract authoring task. Keep direct parameterized psycopg SQL; do
not introduce an ORM or asynchronous PostgreSQL migration.

The runtime database contract grants the configured Web role only schema usage; SELECT, INSERT, and
UPDATE on these auth tables; and sequence usage necessary for `auth_users` identity generation. It
does not grant DELETE, TRUNCATE, DDL, ownership, role-management, or broad database access.

### HTTP contracts

All auth responses use `Cache-Control: no-store, private`.

- `GET /auth/login`
  - optional `return_to`, accepted only by the local return-path validator;
  - creates transaction, sets `__Host-mb_oidc`, and returns 303 to Google;
  - requires no application CSRF token.
- `GET /auth/callback`
  - follows the success/provider-failure callback shapes above;
  - validates and consumes transaction; validates identity and creates local session only on success;
  - clears transaction cookie on terminal outcomes;
  - returns generic errors only and sets `Referrer-Policy: no-referrer`.
- `POST /auth/logout`
  - requires existing double-submit CSRF validation;
  - is idempotent, revokes presented session, clears `__Host-mb_session`, and returns 303 `/`.
- `GET /api/auth/session`
  - authenticated: `200 {"authenticated": true, "user": {"id": ..., "email": "..."}}`;
  - unauthenticated: `401 {"authenticated": false}`;
  - exposes no provider identity internals or token data;
  - additionally uses `Vary: Cookie`.

### Safe return paths

One reusable validator accepts only local pathnames such as `/`, `/library`, and `/reels/123`. It
rejects absolute URLs, scheme-relative URLs, backslash forms, control characters, `javascript:`
forms, encoded bypasses, and external origins. Callback-provided destinations are never trusted.
Only the validated path persisted in the consumed transaction may be used for a redirect.

### Logging security

The production Web Uvicorn command must include `--no-access-log` because callback query strings
may contain authorization code and state. Application logs must never contain callback query
strings, authorization code, client secret, access/refresh token, raw ID token, state, nonce, PKCE
verifier, raw local session token, database DSN, or email by default.

Permitted operational fields are event category, internal auth user ID after binding, bounded
failure category, and correlation identifier.

### Next.js boundary

F1 implements no Next login UI. Next.js must not execute Google OAuth, decode local tokens, access
auth tables, validate Google claims, or authorize an owner. Future Next Server Components may call
FastAPI `GET /api/auth/session` using the incoming server-side Cookie header.

Current Next `/api/health` conflicts with future `/api/*` FastAPI routing. Its future migration to
`/healthz` is a routing-cutover prerequisite and remains out of F1.

### Implementation slices

- F1A — Authentication Core: configuration, token/hash primitives, cookie policy, owner email
  normalization, and return-path validator.
- F1B — Google OIDC Transaction + Callback: Authlib adapter, transaction persistence, PKCE/state/
  nonce, claims validation, owner binding, and callback HTTP behavior.
- F1C — Local Session HTTP Contract: session creation/lookup, `/api/auth/session`, logout, and CSRF
  extraction without regression to existing curation.
- F1D — Database / Configuration Integration: migration content, runtime configuration wiring,
  direct psycopg integration, and least-privilege grant documentation.
- F1E — Security / Regression Closure: access-log leakage prevention, non-persistence evidence,
  complete Web regression, and frontend regression.

## UX Specification Reference

N/A. F1 deliberately supplies backend authentication primitives only. F2 owns the visual login and
other authentication user experience.

## Contracts Changed

Planned new application contracts are `GET /auth/login`, `GET /auth/callback`, `POST /auth/logout`,
and `GET /api/auth/session`, the opaque host-only cookie contracts, the OIDC transaction contract,
and the local-session/identity persistence contract.

F1 does not change Caddy routing, Basic Auth, public Next.js routing, current Jinja behavior, or the
existing curation CSRF contract.

## Data / Migration Impact

F1 plans additive auth tables under `app.*` via
`infra/postgres/migrations/003_f1_authentication_foundation.sql`. Migration creation/review is
Yellow, but the required `infra/**` path is human-gated. Production migration execution and runtime
grants are Red. The authoring task creates no migration and accesses no database.

## Security Impact

F1 adds an application authentication boundary and therefore requires strict test evidence for
provider claims, owner binding, opaque session hashing, atomic replay prevention, safe redirects,
CSRF, cache controls, cookies, and logging. Google is identity provider only. Caddy Basic Auth
remains an independent existing access layer.

No real secret, OAuth client, production role, database, Docker daemon, production service, or
credential is accessed or modified by this Task Contract authoring task.

## Expected Files / Components

### New application and test files

- `services/web/app/auth/__init__.py`
- `services/web/app/auth/config.py`
- `services/web/app/auth/oidc.py`
- `services/web/app/auth/repository.py`
- `services/web/app/auth/routes.py`
- `services/web/app/csrf.py`
- `services/web/tests/test_auth_config.py`
- `services/web/tests/test_auth_return_paths.py`
- `services/web/tests/test_auth_oidc.py`
- `services/web/tests/test_auth_repository.py`
- `services/web/tests/test_auth_routes.py`
- `services/web/tests/test_auth_sessions.py`
- `services/web/tests/test_auth_migration_contract.py`
- `services/web/tests/test_auth_logging.py`

The package initializer is exactly `services/web/app/auth/__init__.py`. Consolidation is permitted
only when it clearly reduces complexity while retaining these responsibilities and testability. Do not create generic service or repository
abstractions beyond F1 needs.

### Existing application, documentation, and test files

- `services/web/app/main.py`
- `services/web/app/database.py`
- `services/web/requirements.txt`
- `services/web/Dockerfile`
- `services/web/tests/test_web.py`
- `docs/ACTIVE_TASK.md`
- `docs/CURRENT_STATE.md`
- `docs/ARCHITECTURE.md`

### Human-gated or control-plane files

- `docs/TASK_CONTRACT_F1_AUTHENTICATION_FOUNDATION.md`
- `infra/postgres/migrations/003_f1_authentication_foundation.sql`
- `infra/.env.example`
- `infra/docker-compose.yml`
- `docs/DECISIONS.md`, only if a durable decision is separately approved

`infra/Caddyfile` remains unchanged. Frontend implementation remains unchanged.

## Required Tests

The implementation must add hermetic tests for:

- configuration validation, exact TTL, and owner-email Unicode normalization;
- safe return-path acceptance and attack rejection;
- CSPRNG token generation and session-hashing persistence boundary;
- PKCE verifier/challenge and S256-only behavior;
- transaction state mismatch, transaction-cookie mismatch, expiry, atomic one-time consumption,
  replay, and provider-error callback behavior;
- provider exchange failure;
- issuer, audience, `azp`, expiry, nonce, subject, email, and `email_verified` validation;
- owner bootstrap, concurrent owner binding, different-subject denial, later email change, and
  disabled owner;
- valid, expired, revoked, and concurrent sessions;
- current-session idempotent logout and CSRF enforcement;
- cookie flags, cache headers, redirects, and safe error bodies;
- provider-token non-persistence and callback secret-log prevention;
- existing Web regression and frontend lint/typecheck/test/build.

No live Google, production PostgreSQL, or Docker daemon is required for normal unit and regression
validation.

## Required Evidence

Eventual implementation evidence must include:

- `services/web`: `python -m pytest -q`.
- `apps/web`: `npm ci`, `npm run lint`, `npm run typecheck`, `npm test`, and `npm run build`.
- Repository: `git diff --check` and `git status --short`.
- Exact `Authlib==1.8.0` pin.
- Test evidence for no provider-token persistence and no committed secrets.
- Production Uvicorn command evidence containing `--no-access-log`.
- Migration contract static tests and existing curation CSRF regression.
- Review evidence that Basic Auth and Caddy are unchanged.

## Staging Requirements

N/A for F1 contract completion. No approved application staging environment exists, and this
contract must not invent staging evidence.

## Production Impact

F1 implementation and local/CI validation do not authorize production. Separate Red human gates
are required for:

- Google OAuth client creation and redirect registration;
- real `GOOGLE_OIDC_CLIENT_SECRET` and `AUTH_OWNER_EMAIL` provisioning;
- production migration execution;
- production runtime grants;
- deployment;
- Caddy changes;
- Basic Auth changes or removal;
- production verification.

## Rollback / Recovery

Before production, use normal Git rollback or forward repair for unpromoted application changes.

After any future production migration, do not execute destructive rollback automatically. Stop
promotion, retain auth data for diagnosis, and use a human-reviewed forward repair or restore
procedure. Owner rebinding/reset is never automatic.

## Human Gates

- G1 — Human approval of this Task Contract before implementation.
- G2 — Human review of human-gated migration and configuration content.
- G3 — Human publication of the F1 candidate because B4.2 v1 cannot publish required new files and
  `infra/**` paths.
- G4 — Human merge into `dev` after CI and review.
- G5 — Separate Red authorization for any production migration, grant, deployment, or configuration.
- G6 — Separate human authorization for any future owner reset or rebinding.

No gate implies or authorizes the next gate.

## Dependencies

- Approved F1 Authentication Discovery and F1 Authentication SDD.
- Existing FastAPI/Jinja and direct psycopg Web application style.
- Authlib 1.8.0, added only during implementation after G1.
- Future human-owned Google OAuth client configuration and Web database-role grant binding for
  production use; neither is an implementation prerequisite for hermetic local tests.

B4.2 is not the remote publication path for F1 because F1 necessarily creates new files and touches
`infra/**`. Do not modify B4.2, create exceptions, invoke publication, or create an operational
B4.2 lifecycle contract for F1. Local Hermes/Codex implementation is allowed only after G1; remote
publication remains human-gated.

## Open Questions

The following are NON-BLOCKING FOR LOCAL F1 IMPLEMENTATION:

- Exact production Google OAuth client registration and redirect URI ownership.
- Exact production runtime-role binding for the documented grants.
- Future cleanup policy for expired session and consumed transaction rows.
- Future owner reset/recovery runbook.
- Future `/healthz` routing-cutover migration.

No implementation-blocking architecture question remains.

## Final Evidence Summary

- Discovery completed.
- SDD completed.
- Task Contract authored.
- No implementation evidence exists yet.
- No dependency installed.
- No migration created.
- No production action occurred.
