# Sprint 4 — Private Web Security

## Delivery 6A — Security foundation

The web curation POST routes use a CSRF double-submit token. A successful Reel
detail GET reuses the existing CSRF cookie when available; otherwise it creates
a cryptographically random token. The same token is placed in every curation
form as `csrf_token` and stored in an `HttpOnly`, `Secure`, `SameSite=Lax`,
host-only `__Host-` cookie with `Path=/`. POST handlers accept the submitted
token only from form data and compare it with the cookie in constant time before
any Reel lookup or mutation.

`SameSite=Lax` supports ordinary same-site navigation and form submissions
while withholding the cookie from cross-site POST requests. `Secure` prepares
the cookie for the HTTPS deployment in Delivery 6C, and `HttpOnly`
prevents client-side scripts from reading it. Local tests that exercise the
cookie must therefore use an HTTPS test origin.

The web process requires `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`,
`WEB_DB_USER`, and `WEB_DB_PASSWORD`. It does not fall back to the PostgreSQL
owner credentials.

## Least-privilege database grant template

The operator must replace `web_runtime_role` with the separately provisioned
runtime role. This template deliberately neither creates a role nor sets a
password.

```sql
GRANT USAGE ON SCHEMA app TO web_runtime_role;

GRANT SELECT ON TABLE
    app.reels,
    app.reel_enrichments,
    app.categories,
    app.reel_categories
TO web_runtime_role;

GRANT INSERT ON TABLE app.categories TO web_runtime_role;
GRANT USAGE ON SEQUENCE app.categories_id_seq TO web_runtime_role;

GRANT INSERT, DELETE ON TABLE app.reel_categories TO web_runtime_role;
```

These are the privileges used by the current queries: categories are inserted
and read, their identity sequence is consumed, and Reel/category associations
are inserted and deleted. No `UPDATE`, enrichment-attempt, administration, or
unrelated table privileges are granted.

## Delivery 6B — Private runtime preparation

The Web container has no published host port: Caddy is its only public ingress
and proxies the dedicated `WEB_HOST` HTTPS site to `web:8000`. Basic Auth covers
all Web paths, including `/health`, but does not replace the application's CSRF
protection. HTTPS is mandatory because CSRF relies on a Secure `__Host-` cookie.

The Web process connects to PostgreSQL with the dedicated least-privilege
`WEB_DB_USER` role, never the database owner credentials. R2 remains private;
the Web process receives the canonical R2 configuration and produces
short-lived signed video URLs without exposing credentials to the browser.

`WEB_BASIC_AUTH_HASH` must contain a Caddy-compatible password hash generated
operationally, never a plaintext password. Actual DNS, credentials, protected
production configuration, and deployment remain human/operator actions.

## Delivery 6C — Operator gates

The operator must complete every gate:

1. Choose `WEB_HOST`.
2. Point DNS for `WEB_HOST` to the VPS.
3. Generate the Basic Auth username and password.
4. Generate a Caddy-compatible password hash.
5. Place all runtime variables in protected production configuration.
6. Validate the Compose configuration.
7. Validate the Caddy configuration.
8. Start Web.
9. Reload or recreate Caddy safely.
10. Verify HTTPS.
11. Verify an unauthorized request receives HTTP 401.
12. Verify an authorized request receives HTTP 200.
13. Verify CSRF-protected curation through HTTPS.
14. Verify signed R2 video access.
15. Verify Web uses the least-privilege PostgreSQL role.
16. Verify existing n8n, downloader, and enricher services remain healthy.
