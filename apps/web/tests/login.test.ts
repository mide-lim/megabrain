import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import {
  GOOGLE_LOGIN_TARGET,
  getSessionState,
  LoginSessionContent,
} from "../src/app/login/login-session";

function render(state: Parameters<typeof LoginSessionContent>[0]["state"]): string {
  return renderToStaticMarkup(createElement(LoginSessionContent, { state }));
}

test("an unauthenticated session offers the FastAPI Google login flow", async () => {
  let requestOptions: RequestInit | undefined;
  const request = (async (_input: RequestInfo | URL, init?: RequestInit) => {
    requestOptions = init;
    return new Response(JSON.stringify({ authenticated: false }), { status: 401 });
  }) as typeof fetch;

  const state = await getSessionState(request);
  const markup = render(state);

  assert.deepEqual(state, { kind: "unauthenticated" });
  assert.equal(requestOptions?.method, "GET");
  assert.match(markup, /Entre no seu espaço/);
  assert.ok(markup.includes(`href="${GOOGLE_LOGIN_TARGET}"`));
});

test("an authenticated session shows the active owner identity", async () => {
  const request = (async () =>
    new Response(
      JSON.stringify({
        authenticated: true,
        user: { id: "owner-1", email: "owner@example.com" },
      }),
      { status: 200 },
    )) as typeof fetch;

  const state = await getSessionState(request);
  const markup = render(state);

  assert.deepEqual(state, {
    kind: "authenticated",
    user: { id: "owner-1", email: "owner@example.com" },
  });
  assert.match(markup, /Sessão ativa/);
  assert.match(markup, /owner@example\.com/);
});

test("the login action keeps FastAPI as authority and links to the public library", () => {
  const markup = render({ kind: "unauthenticated" });

  assert.equal(GOOGLE_LOGIN_TARGET, "/auth/login?return_to=/login");
  assert.match(markup, /href="\/auth\/login\?return_to=\/login"/);
  assert.match(markup, /href="\/"/);
  assert.match(markup, /Biblioteca de Reels/);
});

test("the session component does not persist browser session data", async () => {
  const source = await readFile(
    new URL("../src/app/login/login-session.tsx", import.meta.url),
    "utf8",
  );

  assert.doesNotMatch(source, /\blocalStorage\b/);
  assert.doesNotMatch(source, /\bsessionStorage\b/);
  assert.doesNotMatch(source, /\bdocument\.cookie\b/);
});

test("a failed session check remains unauthenticated and offers a safe recovery", async () => {
  const request = (async () => {
    throw new Error("network unavailable");
  }) as typeof fetch;

  const state = await getSessionState(request);
  const markup = render(state);

  assert.deepEqual(state, { kind: "error" });
  assert.match(markup, /Não foi possível confirmar sua sessão/);
  assert.match(markup, /href="\/auth\/login\?return_to=\/login"/);
});
