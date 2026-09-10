import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import {
  buildLibraryUrl,
  fetchLibraryPage,
  type LibraryResponse,
} from "../src/app/library/library-api";
import { LibraryPageContent } from "../src/app/library/library-page-content";

const result: LibraryResponse = {
  items: [
    {
      id: 42,
      title: "Build a useful thing",
      creator: "A very long creator name that must not break the card layout",
      shortcode: "abc123",
      caption: "A useful caption for the reel card.",
      categories: ["Hands-on", "Tech"],
      duration_seconds: 12.5,
      received_at: "2026-08-25T00:00:00Z",
      has_transcript: true,
    },
  ],
  query: { q: "maker" },
  pagination: {
    page: 2,
    page_size: 12,
    has_previous: true,
    has_next: true,
  },
};

function render(library: LibraryResponse | null = result): string {
  return renderToStaticMarkup(createElement(LibraryPageContent, { library }));
}

test("library page is a server-rendered Explore surface with accessible search", async () => {
  const source = await readFile(
    new URL("../src/app/library/page.tsx", import.meta.url),
    "utf8",
  );
  const markup = render();

  assert.doesNotMatch(source, /["']use client["']/);
  assert.match(markup, /Biblioteca de Reels/);
  assert.match(markup, /<form[^>]+action="\/library"[^>]+method="get"/);
  assert.match(markup, /<label[^>]*>Buscar por criador, legenda, transcrição ou categoria<\/label>/);
  assert.match(markup, /name="q"/);
  assert.match(markup, /value="maker"/);
  assert.doesNotMatch(markup, /href="\/login"/);
  assert.match(markup, /Página 2/);
  assert.match(markup, /1 Reel nesta página/);
});

test("library search and clear URLs reset pagination", () => {
  const markup = render();

  assert.equal(buildLibraryUrl({ page: 1, q: "maker" }), "/library?q=maker");
  assert.equal(buildLibraryUrl({ page: 2, q: "maker" }), "/library?page=2&q=maker");
  assert.match(markup, /<a[^>]+href="\/library"[^>]*>Limpar busca<\/a>/);
  assert.doesNotMatch(markup, /name="page"/);
});

test("library pagination preserves q and omits no unavailable controls", () => {
  const markup = render();

  assert.match(markup, /href="\/library\?q=maker"/);
  assert.match(markup, /href="\/library\?page=3&amp;q=maker"/);
  assert.match(markup, />Anterior</);
  assert.match(markup, />Próxima</);

  const firstPage = render({
    ...result,
    pagination: { ...result.pagination, page: 1, has_previous: false },
  });
  const finalPage = render({
    ...result,
    pagination: { ...result.pagination, has_next: false },
  });

  assert.doesNotMatch(firstPage, />Anterior</);
  assert.doesNotMatch(finalPage, />Próxima</);
});

test("library cards link across the FastAPI detail boundary and render public metadata", () => {
  const markup = render();

  assert.match(markup, /href="\/reels\/42"/);
  assert.match(markup, /Build a useful thing/);
  assert.match(markup, /Hands-on/);
  assert.match(markup, /Tech/);
  assert.match(markup, /Transcrição disponível/);
  assert.match(markup, /12,5 s/);
  assert.match(markup, /25 de ago\. de 2026/);
  assert.doesNotMatch(markup, /<img|<video|thumbnail|poster|shortcode|object_key|storage/i);
});

test("library cards use deterministic fallbacks without inventing titles", () => {
  const markup = render({
    ...result,
    items: [{ ...result.items[0], title: null, shortcode: "source-name" }],
  });

  assert.match(markup, /Reel sem título/);
  assert.doesNotMatch(markup, /source-name/);
});

test("library shows distinct empty, no-result, and unavailable states", () => {
  const empty = render({
    items: [],
    query: { q: "" },
    pagination: { page: 1, page_size: 12, has_previous: false, has_next: false },
  });
  const noResults = render({
    items: [],
    query: { q: "maker" },
    pagination: { page: 1, page_size: 12, has_previous: false, has_next: false },
  });
  const unavailable = render(null);

  assert.match(empty, /Sua biblioteca está vazia/);
  assert.match(noResults, /Nenhum Reel encontrado para “maker”/);
  assert.match(unavailable, /Biblioteca temporariamente indisponível/);
});

test("server-side API helper uses no-store and an internal non-public URL", async () => {
  let requestedUrl = "";
  let requestOptions: RequestInit | undefined;
  const request = (async (input: RequestInfo | URL, init?: RequestInit) => {
    requestedUrl = String(input);
    requestOptions = init;
    return new Response(JSON.stringify(result), { status: 200 });
  }) as typeof fetch;

  const response = await fetchLibraryPage(
    { page: 2, q: "maker" },
    request,
    new Headers({ cookie: "__Host-mb_session=opaque" }),
  );
  const source = await readFile(
    new URL("../src/app/library/library-api.ts", import.meta.url),
    "utf8",
  );

  assert.deepEqual(response, result);
  assert.equal(requestedUrl, "http://web:8000/api/reels?page=2&q=maker");
  assert.equal(requestOptions?.cache, "no-store");
  assert.equal(new Headers(requestOptions?.headers).get("cookie"), "__Host-mb_session=opaque");
  assert.match(source, /MEGABRAIN_API_INTERNAL_URL/);
  assert.doesNotMatch(source, /NEXT_PUBLIC_/);
});

test("server-side API helper converts API failures into the unavailable state", async () => {
  const request = (async () => new Response("unavailable", { status: 503 })) as typeof fetch;

  assert.equal(await fetchLibraryPage({ page: 1, q: "" }, request), null);
});

test("server-side API helper rejects malformed public projections", async () => {
  const request = (async () =>
    new Response(
      JSON.stringify({
        ...result,
        items: [{ id: 42, categories: "not-an-array" }],
      }),
      { status: 200 },
    )) as typeof fetch;

  assert.equal(await fetchLibraryPage({ page: 1, q: "" }, request), null);
});
