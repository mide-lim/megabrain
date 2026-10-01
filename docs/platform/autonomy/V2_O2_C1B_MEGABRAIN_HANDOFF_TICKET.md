# V2-O2-C1B — MegaBrain Handoff Ticket Evidence

Status: implementation complete
Date: 2026-09-30
Verdict: `MEGABRAIN_HANDOFF_ISSUER_READY`

## Implemented

MegaBrain now has an isolated code path for issuing Paperclip handoff tickets.

New endpoint:

`POST /api/platform/paperclip/launch`

The endpoint:

- requires the existing owner session;
- requires the existing CSRF form token;
- loads a fixed HTTPS Paperclip cockpit origin from server configuration;
- creates a 90-second signed handoff ticket;
- returns HTTP 303 to the fixed Paperclip exchange route;
- emits `Cache-Control: no-store, private`;
- emits `Referrer-Policy: no-referrer`;
- returns a generic 503 if handoff configuration is unavailable.

## Configuration Contract

No production values were created or changed.

Future runtime variables:

- `PAPERCLIP_COCKPIT_PUBLIC_URL`
- `PAPERCLIP_HANDOFF_SECRET`

The public URL must be an HTTPS origin with no path/query/fragment.

The handoff secret must be at least 32 bytes.

## Ticket Contract

Header:

- `alg = HS256`
- `typ = MB-PC-HANDOFF`
- `v = 1`

Claims:

- `iss = megabrain`
- `aud = paperclip-cockpit`
- `sub = MegaBrain owner user id`
- normalized owner email
- exact configured Paperclip origin
- `iat`
- `exp = iat + 90`
- random `jti`
- fixed landing path `/`
- version `1`

Signing uses HMAC-SHA256 with a key derived using the domain separator:

`megabrain:paperclip-handoff:v1`

The ticket contains no MegaBrain browser session token, Google token, or model
credential.

## Files Changed

- `services/web/app/platform_access.py`
- `services/web/app/main.py`
- `services/web/tests/test_platform_access.py`
- this evidence document
- C1-B Task Contract

## Validation

Focused tests:

```text
24 passed
```

Coverage included:

- HTTPS origin validation;
- minimum signing secret length;
- ticket claims and 90-second TTL;
- independent signature recomputation;
- owner-session requirement;
- CSRF requirement;
- fixed Paperclip redirect target;
- no MegaBrain session token in redirect;
- generic configuration failure behavior;
- existing auth route tests;
- existing owner-boundary tests.

Full FastAPI service suite:

```text
345 passed
```

Only pre-existing dependency deprecation warnings were observed.

## Security Result

The existing MegaBrain authentication architecture was not altered.

`__Host-mb_session` remains unchanged and host-only.

No Paperclip runtime, public ingress, DNS, Caddy, Docker, provider credential or
production state was touched.

## Next Review Gate

C1-C should implement/prove the Paperclip-side exchange in an isolated
authenticated Paperclip instance, including:

- ticket signature/claim validation;
- exact destination binding;
- atomic jti consumption;
- replay rejection;
- mapped owner validation;
- Better Auth session creation;
- redirect that removes the ticket from normal navigation;
- ticket redaction in logs.

Do not expose Paperclip publicly during C1-C.
