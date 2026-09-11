import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { AppShell } from "../src/components/app-shell";

function render(pathname: "/inbox" | "/library" | "/categories" | "/settings" = "/inbox"): string {
  return renderToStaticMarkup(
    createElement(AppShell, { owner: { email: "very-long-owner-address@example.megabrain.test" }, pathname }, createElement("p", null, "Conteúdo")),
  );
}

test("authenticated app shell provides navigation, safe owner presence, and a deferred add action", () => {
  const markup = render();

  for (const label of ["Inbox", "Biblioteca", "Categorias", "Configurações"]) {
    assert.match(markup, new RegExp(`>${label}<`));
  }
  assert.match(markup, /very-long-owner-address@example\.megabrain\.test/);
  assert.match(markup, /aria-current="page"/);
  assert.match(markup, /Adicionar Reel/);
  assert.match(markup, /Em breve/);
  assert.match(markup, /disabled=""/);
  assert.match(markup, />Sair</);
  assert.match(markup, /href="\/library"/);
  assert.doesNotMatch(markup, /href="#"/);
});

test("logout uses FastAPI's CSRF bootstrap and form redirect contract", async () => {
  const source = await readFile(new URL("../src/components/logout-button.tsx", import.meta.url), "utf8");

  assert.match(source, /fetch\("\/api\/auth\/csrf", \{[\s\S]*credentials: "same-origin"/);
  assert.match(source, /cache: "no-store"/);
  assert.match(source, /csrfResponse\.ok/);
  assert.match(source, /document\.createElement\("form"\)/);
  assert.match(source, /form\.action = "\/auth\/logout"/);
  assert.match(source, /form\.method = "POST"/);
  assert.match(source, /csrfInput\.name = "csrf_token"/);
  assert.match(source, /csrfInput\.value = csrfPayload\.csrf_token/);
  assert.match(source, /document\.body\.append\(form\)/);
  assert.match(source, /form\.submit\(\)/);
  assert.match(source, /disabled=\{pending\}/);
  assert.match(source, /role="alert"/);
  assert.doesNotMatch(source, /document\.cookie|localStorage|sessionStorage|X-CSRF-Token/);
});

test("all Next application entry pages require the server owner session", async () => {
  const files = ["page.tsx", "inbox/page.tsx", "library/page.tsx", "categories/page.tsx", "settings/page.tsx"];
  const source = await Promise.all(files.map((file) => readFile(new URL(`../src/app/${file}`, import.meta.url), "utf8")));

  for (const pageSource of source) {
    assert.match(pageSource, /requireOwnerSession/);
  }
  assert.match(source[0], /redirect\("\/inbox"\)/);
});

test("login is a server-rendered redirect boundary and preserves the FastAPI return target", async () => {
  const pageSource = await readFile(new URL("../src/app/login/page.tsx", import.meta.url), "utf8");
  const loginSource = await readFile(new URL("../src/app/login/login-session.tsx", import.meta.url), "utf8");

  assert.match(pageSource, /getOwnerSession/);
  assert.match(pageSource, /redirect\("\/inbox"\)/);
  assert.match(loginSource, /\/auth\/login\?return_to=\/inbox/);
  assert.doesNotMatch(loginSource, /useEffect|localStorage|sessionStorage|document\.cookie/);
});
