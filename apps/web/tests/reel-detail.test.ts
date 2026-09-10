import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import {
  fetchReelDetail,
  type ReelDetail,
} from "../src/app/reels/[reelId]/reel-detail-api";
import { performCategoryMutation } from "../src/app/reels/[reelId]/reel-category-controls";
import { ReelDetailPageContent } from "../src/app/reels/[reelId]/reel-detail-page-content";

const reel: ReelDetail = {
  id: 42,
  title: "Build a useful thing",
  creator: "maker",
  shortcode: "abc123",
  original_url: "https://www.instagram.com/reel/abc123/",
  status: "downloaded",
  caption: "The original caption",
  duration_seconds: 12.5,
  received_at: "2026-08-25T00:00:00Z",
  downloaded_at: "2026-08-26T00:00:00Z",
  filename: "video.mp4",
  mime_type: "video/mp4",
  file_size_bytes: 2048,
  transcript: {
    available: true,
    text: "Accepted transcript text",
    language: "pt-BR",
    completed_at: "2026-08-27T00:00:00Z",
  },
  categories: {
    assigned: [{ id: 1, name: "Tecnologia" }],
    available: [{ id: 2, name: "Maker" }],
  },
  video: { available: true, src: "/api/reels/42/video" },
};

function render(detail: ReelDetail = reel): string {
  return renderToStaticMarkup(createElement(ReelDetailPageContent, { reel: detail, categoryControls: null }));
}

test("reel page authenticates before its detail fetch and adds no protected loading boundary", async () => {
  const pageSource = await readFile(new URL("../src/app/reels/[reelId]/page.tsx", import.meta.url), "utf8");

  assert.ok(pageSource.indexOf("await requireOwnerSession()") >= 0);
  assert.ok(pageSource.indexOf("await fetchReelDetail") > pageSource.indexOf("await requireOwnerSession()"));
  assert.doesNotMatch(pageSource, /["']use client["']/);
  await assert.rejects(
    readFile(new URL("../src/app/reels/loading.tsx", import.meta.url), "utf8"),
    { code: "ENOENT" },
  );
  await assert.rejects(
    readFile(new URL("../src/app/reels/[reelId]/loading.tsx", import.meta.url), "utf8"),
    { code: "ENOENT" },
  );
});

test("server detail adapter forwards only cookie with no-store and validates successful data", async () => {
  let requestedUrl = "";
  let options: RequestInit | undefined;
  const request = (async (input: RequestInfo | URL, init?: RequestInit) => {
    requestedUrl = String(input);
    options = init;
    return new Response(JSON.stringify(reel), { status: 200 });
  }) as typeof fetch;

  const result = await fetchReelDetail(42, request, new Headers({ cookie: "__Host-mb_session=opaque" }));

  assert.deepEqual(result, { kind: "ok", reel });
  assert.equal(requestedUrl, "http://web:8000/api/reels/42");
  assert.equal(options?.cache, "no-store");
  assert.equal(new Headers(options?.headers).get("accept"), "application/json");
  assert.equal(new Headers(options?.headers).get("cookie"), "__Host-mb_session=opaque");
  assert.equal(new Headers(options?.headers).get("authorization"), null);
});

test("server detail adapter distinguishes missing data from temporary or malformed responses", async () => {
  const missing = (async () => new Response(JSON.stringify({ detail: "Reel not found" }), { status: 404 })) as typeof fetch;
  const unavailable = (async () => new Response("unavailable", { status: 503 })) as typeof fetch;
  const malformed = (async () => new Response(JSON.stringify({ id: 42, video: {} }), { status: 200 })) as typeof fetch;
  const unexpectedVideoUrl = (async () => new Response(JSON.stringify({ ...reel, video: { available: true, src: "https://signed.example/video.mp4" } }), { status: 200 })) as typeof fetch;

  const incomingHeaders = new Headers();
  assert.deepEqual(await fetchReelDetail(42, missing, incomingHeaders), { kind: "not-found" });
  assert.deepEqual(await fetchReelDetail(42, unavailable, incomingHeaders), { kind: "unavailable" });
  assert.deepEqual(await fetchReelDetail(42, malformed, incomingHeaders), { kind: "unavailable" });
  assert.deepEqual(await fetchReelDetail(42, unexpectedVideoUrl, incomingHeaders), { kind: "unavailable" });
});

test("detail presentation renders parity content through the protected same-origin video contract", async () => {
  const markup = render();

  assert.match(markup, /href="\/library"/);
  assert.match(markup, /Voltar para Biblioteca/);
  assert.match(markup, /Build a useful thing/);
  assert.match(markup, /maker/);
  assert.match(markup, /<video[^>]+controls=""[^>]+preload="metadata"[^>]+src="\/api\/reels\/42\/video"/);
  assert.match(markup, /The original caption/);
  assert.match(markup, /Accepted transcript text/);
  assert.match(markup, /Tecnologia/);
  const controlsSource = await readFile(new URL("../src/app/reels/[reelId]/reel-category-controls.tsx", import.meta.url), "utf8");
  assert.match(controlsSource, /availableCategories\.map/);
  assert.match(markup, /Abrir Reel original/);
  assert.match(markup, /rel="noopener noreferrer"/);
  assert.doesNotMatch(markup, /storage_bucket|object_key|signed\.example|R2_ACCESS_KEY/i);
});

test("detail presentation uses explicit pt-BR fallbacks and unavailable states", () => {
  const markup = render({
    ...reel,
    title: null,
    creator: null,
    caption: null,
    duration_seconds: null,
    file_size_bytes: null,
    transcript: { available: false, text: null, language: null, completed_at: null },
    video: { available: false, src: null },
  });

  assert.match(markup, /abc123/);
  assert.match(markup, /Criador não informado/);
  assert.match(markup, /Legenda original não disponível\./);
  assert.match(markup, /Transcrição ainda não disponível\./);
  assert.match(markup, /Vídeo temporariamente indisponível\./);
  assert.match(markup, /Status/);
  assert.match(markup, /Shortcode/);
  assert.doesNotMatch(markup, /NaN|undefined/);
});

test("category mutation helper uses C3 JSON APIs with same-origin CSRF bootstrap", async () => {
  const calls: Array<{ url: string; options?: RequestInit }> = [];
  const request = (async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(input), options: init });
    if (String(input) === "/api/auth/csrf") {
      return new Response(JSON.stringify({ csrf_token: "short-lived-token" }), { status: 200 });
    }
    return new Response(null, { status: 204 });
  }) as typeof fetch;

  assert.equal(await performCategoryMutation("/api/reels/42/categories", "POST", { category_id: 2 }, request), true);
  assert.equal(await performCategoryMutation("/api/reels/42/categories/new", "POST", { name: "Maker" }, request), true);
  assert.equal(await performCategoryMutation("/api/reels/42/categories/1", "DELETE", undefined, request), true);

  assert.equal(calls.filter((call) => call.url === "/api/auth/csrf").length, 3);
  const mutations = calls.filter((call) => call.url !== "/api/auth/csrf");
  assert.deepEqual(mutations.map((call) => [call.url, call.options?.method]), [
    ["/api/reels/42/categories", "POST"],
    ["/api/reels/42/categories/new", "POST"],
    ["/api/reels/42/categories/1", "DELETE"],
  ]);
  for (const call of calls) {
    assert.equal(call.options?.credentials, "same-origin");
  }
  for (const call of mutations) {
    assert.equal(new Headers(call.options?.headers).get("x-csrf-token"), "short-lived-token");
  }
  assert.equal(new Headers(mutations[0].options?.headers).get("content-type"), "application/json");
  assert.equal(new Headers(mutations[2].options?.headers).get("content-type"), null);
});

test("category controls keep interaction state local, accessible, and refresh canonical server state", async () => {
  const source = await readFile(new URL("../src/app/reels/[reelId]/reel-category-controls.tsx", import.meta.url), "utf8");

  assert.match(source, /router\.refresh\(\)/);
  assert.match(source, /role="alert"/);
  assert.match(source, /disabled=\{pending/);
  assert.match(source, /Remover categoria/);
  assert.match(source, /htmlFor="existing-category"/);
  assert.match(source, /htmlFor="new-category"/);
  assert.doesNotMatch(source, /localStorage|sessionStorage|console\.log|document\.cookie/);
});
