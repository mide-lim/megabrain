import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { AppShell } from "../src/components/app-shell";

function render(pathname: "/inbox" | "/library" | "/categories" | "/development" | "/settings" = "/inbox"): string {
  return renderToStaticMarkup(
    createElement(AppShell, { owner: { email: "very-long-owner-address@example.megabrain.test" }, pathname }, createElement("p", null, "Conteúdo")),
  );
}

test("authenticated app shell groups Reel navigation, preserves independent routes, and provides accessible add Reel actions", () => {
  const markup = render();

  for (const label of ["Inbox", "Biblioteca", "Categorias", "Desenvolvimento", "Configuração"]) {
    assert.match(markup, new RegExp(`>${label}<`));
  }
  assert.match(markup, /<section[^>]+aria-labelledby="reels-navigation-sidebar"[\s\S]*?<h2[^>]+id="reels-navigation-sidebar">Reels<\/h2>[\s\S]*?href="\/inbox"[\s\S]*?href="\/library"[\s\S]*?href="\/categories"[\s\S]*?>Adicionar Reel</);
  assert.match(markup, /<section[^>]+aria-labelledby="reels-navigation-mobile"[\s\S]*?<h2[^>]+id="reels-navigation-mobile">Reels<\/h2>[\s\S]*?href="\/inbox"[\s\S]*?href="\/library"[\s\S]*?href="\/categories"[\s\S]*?>Adicionar Reel</);
  assert.match(markup, /very-long-owner-address@example\.megabrain\.test/);
  assert.match(markup, /<a[^>]+aria-current="page"[^>]+href="\/inbox"/);
  assert.doesNotMatch(markup, /<a[^>]+aria-current="page"[^>]+href="\/(?:library|categories|development|settings)"/);
  assert.match(markup, />\+ Adicionar Reel</);
  assert.match(markup, />Adicionar Reel</);
  const dialogLabels = [...markup.matchAll(/<dialog[^>]+aria-labelledby="([^"]+)"/g)].map((match) => match[1]);
  assert.ok(dialogLabels.length >= 2);
  assert.equal(new Set(dialogLabels).size, dialogLabels.length);
  for (const dialogLabel of dialogLabels) {
    assert.match(markup, new RegExp(`<h2[^>]+id="${dialogLabel}">Adicionar Reel<`));
  }
  assert.match(markup, /Cole o link público de um Reel do Instagram/);
  assert.doesNotMatch(markup, /Em breve|add-reel-deferred/);
  assert.match(markup, />Sair</);
  assert.match(markup, /href="\/library"/);
  assert.match(markup, /href="\/categories"/);
  assert.match(markup, /href="\/development"/);
  assert.match(markup, /href="\/settings"/);
  assert.doesNotMatch(markup, /href="#"/);
});

test("Paperclip launch bootstraps CSRF then submits the existing handoff endpoint as a browser form", async () => {
  const source = await readFile(new URL("../src/components/open-paperclip-button.tsx", import.meta.url), "utf8");

  assert.match(source, /fetchCsrfToken\(\)/);
  assert.match(source, /form\.action = "\/api\/platform\/paperclip\/launch"/);
  assert.match(source, /form\.method = "POST"/);
  assert.match(source, /csrfInput\.name = "csrf_token"/);
  assert.match(source, /csrfInput\.value = csrfToken/);
  assert.match(source, /document\.body\.append\(form\)/);
  assert.match(source, /form\.submit\(\)/);
  assert.match(source, /Abrir Paperclip/);
  assert.match(source, /disabled=\{pending\}/);
  assert.match(source, /role="alert"/);
  assert.doesNotMatch(source, /document\.cookie|localStorage|sessionStorage|X-CSRF-Token/);
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
  const files = ["page.tsx", "inbox/page.tsx", "library/page.tsx", "categories/page.tsx", "development/page.tsx", "settings/page.tsx"];
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
