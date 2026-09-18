# F5.1 — Add Reel UX

## Status

Implementation candidate. No production deployment is authorized by this change.

## Goal

Turn the authenticated Next.js shell's deferred **+ Adicionar Reel** action into a real owner-facing entry point for the already production-proven Web ingestion contract.

F5.1 does not redesign ingestion. It connects the UI to the existing contract:

```text
Owner browser
  -> GET /api/auth/csrf
  -> POST /api/reels
  -> register_reel(..., telegram_metadata=None)
  -> MGB-015
  -> MGB-020
  -> MGB-030
```

## Scope

Frontend-only:

- replace the disabled "Em breve" control in the authenticated App Shell;
- add an accessible native dialog for Reel URL input;
- reuse the existing CSRF bootstrap helper;
- add a typed client boundary for `POST /api/reels`;
- show bounded loading, success, existing-Reel, unconfirmed-dispatch, and error states;
- offer an explicit `/reels/{id}` link after durable registration;
- add focused frontend tests.

No backend, workflow, schema, database grant, R2, Caddy, Compose, or production-runtime change is part of F5.1.

## Existing API contract

Request:

```http
POST /api/reels
Content-Type: application/json
X-CSRF-Token: <opaque token>

{"url":"https://www.instagram.com/reel/.../"}
```

The endpoint requires the owner session and API CSRF protection.

Successful responses remain durable even when dispatch cannot be confirmed:

- `201` + `created=true` for a newly registered Reel;
- `200` + `created=false` for an already registered Reel;
- dispatch state is `accepted`, `not_required`, or `unconfirmed`.

An existing Reel is therefore not a UI error.

## UX contract

### Default

The authenticated shell exposes **+ Adicionar Reel** as an enabled button.

Opening it presents a native `<dialog>` with:

- visible "URL do Reel" label;
- URL input;
- Cancel action;
- Add action.

### Pending

During submission:

- the input and close/cancel/submit controls are disabled;
- the submit label becomes "Adicionando…";
- a live status announces that the Reel is being added;
- duplicate submission is blocked.

### New Reel

For `created=true` + `accepted`:

> Reel adicionado. O processamento foi iniciado.

For `created=true` + `unconfirmed`:

> Reel salvo. Ainda não foi possível confirmar o início do processamento.

F5.1 does not redirect automatically. The user may explicitly open the newly registered Reel.

### Existing Reel

For `created=false` + `not_required`:

> Este Reel já existe no MegaBrain.

For `created=false` + `accepted`:

> Este Reel já existia e o processamento foi solicitado novamente.

For `created=false` + `unconfirmed`:

> Este Reel já existe. Ainda não foi possível confirmar o processamento.

### Errors

The client does not render arbitrary server error text. HTTP/domain responses are mapped to bounded UI codes:

| HTTP / condition | UI code |
| --- | --- |
| empty URL | `invalid_request` |
| CSRF bootstrap unavailable | `csrf_unavailable` |
| 401 | `session_unavailable` |
| 403 | `csrf_unavailable` |
| 409 | `identity_conflict` |
| 422 | `invalid_request` |
| 503 + `registration_unavailable` | `registration_unavailable` |
| 503 + `reel_dispatch_unavailable` | `dispatch_unavailable` |
| network exception | `network_error` |
| malformed/unexpected response | `invalid_response` |

## Security boundaries

F5.1 preserves the F4 security model:

- the browser never reads the owner session cookie;
- CSRF is obtained through `GET /api/auth/csrf`;
- the token is sent only in the required `X-CSRF-Token` header;
- no token or session value is written to localStorage/sessionStorage;
- the client does not accept lifecycle/source/Telegram metadata from the user;
- the backend remains the normalization, registration, deduplication, and dispatch authority.

## Non-goals

F5.1 deliberately does not include:

- automatic lifecycle polling;
- progress streaming;
- retry controls;
- shortcode search;
- observability dashboards;
- backend API changes;
- production deploy.

Those remain separate F5 stages so the first productization step stays bounded.

## Validation

Required frontend validation:

```bash
cd apps/web
npm test
npm run lint
npm run typecheck
npm run build
```

Focused coverage includes:

- functional App Shell action;
- CSRF-before-mutation ordering;
- strict JSON request shape;
- new/existing Reel success cases;
- all dispatch states;
- bounded 401/403/409/422/503 handling;
- network and malformed-response failure;
- native dialog semantics;
- loading/disabled/error/success UI states.

## Promotion boundary

This implementation may be committed to a dedicated branch and opened as a pull request against `dev`.

Merge and any production deployment remain outside this implementation authorization.
