import assert from "node:assert/strict";
import test from "node:test";

import { getOwnerSession } from "../src/lib/auth/session";

test("server auth DAL forwards the incoming Cookie header without caching", async () => {
  let options: RequestInit | undefined;
  const request = (async (_input: RequestInfo | URL, init?: RequestInit) => {
    options = init;
    return new Response(
      JSON.stringify({ authenticated: true, user: { id: 12, email: "owner@example.com" } }),
      { status: 200 },
    );
  }) as typeof fetch;

  const owner = await getOwnerSession(new Headers({ cookie: "__Host-mb_session=opaque" }), request);

  assert.deepEqual(owner, { email: "owner@example.com" });
  assert.equal(options?.cache, "no-store");
  assert.equal(new Headers(options?.headers).get("cookie"), "__Host-mb_session=opaque");
  assert.equal(new Headers(options?.headers).get("accept"), "application/json");
});

test("server auth DAL treats expected 401 and malformed sessions as unauthenticated", async () => {
  const unauthorized = (async () => new Response(JSON.stringify({ authenticated: false }), { status: 401 })) as typeof fetch;
  const malformed = (async () => new Response(JSON.stringify({ authenticated: true, user: { email: 42 } }), { status: 200 })) as typeof fetch;

  assert.equal(await getOwnerSession(new Headers(), unauthorized), null);
  assert.equal(await getOwnerSession(new Headers(), malformed), null);
});
