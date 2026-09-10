import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import LoginSession, { GOOGLE_LOGIN_TARGET } from "../src/app/login/login-session";

test("unauthenticated login renders the FastAPI Google login action for the inbox", () => {
  const markup = renderToStaticMarkup(createElement(LoginSession));

  assert.equal(GOOGLE_LOGIN_TARGET, "/auth/login?return_to=/inbox");
  assert.match(markup, /Entrar com Google/);
  assert.match(markup, /href="\/auth\/login\?return_to=\/inbox"/);
});

test("login has no client session authority or browser persistence", async () => {
  const source = await readFile(new URL("../src/app/login/login-session.tsx", import.meta.url), "utf8");
  const page = await readFile(new URL("../src/app/login/page.tsx", import.meta.url), "utf8");

  assert.doesNotMatch(source, /["']use client["']|useEffect|localStorage|sessionStorage|document\.cookie/);
  assert.match(page, /getOwnerSession/);
  assert.match(page, /redirect\("\/inbox"\)/);
  assert.doesNotMatch(page, /focus-visible:outline-none/);
});
