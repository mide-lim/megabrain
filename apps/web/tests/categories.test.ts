import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import {
  buildCategoryUrl,
  fetchCategories,
  fetchCategoryDetail,
  type CategoriesResponse,
  type CategoryDetailFetchResult,
  type CategoryDetailResponse,
} from "../src/app/categories/categories-api";
import { performCategoryMutation } from "../src/app/categories/category-actions";
import { CategoriesPageContent } from "../src/app/categories/categories-page-content";
import { CategoryDetailPageContent } from "../src/app/categories/[categoryId]/category-detail-page-content";

const categories: CategoriesResponse = {
  items: [
    { id: 2, name: "Arduino", reel_count: 0 },
    { id: 7, name: "IoT", reel_count: 1 },
  ],
};

const detail: CategoryDetailResponse = {
  category: { id: 7, name: "IoT", reel_count: 1 },
  items: [
    {
      id: 42,
      title: "Build a useful thing",
      creator: "maker",
      shortcode: "abc123",
      caption: "caption",
      categories: ["IoT"],
      duration_seconds: 12.5,
      received_at: "2026-08-25T00:00:00Z",
      has_transcript: true,
      download_status: "downloaded",
      curation_status: "organized",
      transcription_status: "completed",
    },
  ],
  pagination: {
    page: 2,
    page_size: 12,
    has_previous: true,
    has_next: true,
  },
};

function renderCategories(value: CategoriesResponse | null = categories): string {
  return renderToStaticMarkup(
    createElement(CategoriesPageContent, { categories: value, createControl: null }),
  );
}

function renderDetail(result: CategoryDetailFetchResult = { kind: "ok", data: detail }): string {
  return renderToStaticMarkup(
    createElement(CategoryDetailPageContent, { result, actions: null }),
  );
}

test("categories authenticates before fetching data", async () => {
  const source = await readFile(
    new URL("../src/app/categories/page.tsx", import.meta.url),
    "utf8",
  );

  assert.ok(source.indexOf("await requireOwnerSession()") >= 0);
  assert.ok(source.indexOf("await fetchCategories()") > source.indexOf("await requireOwnerSession()"));
  assert.doesNotMatch(source, /["']use client["']/);
});

test("categories renders counts, navigation, empty and unavailable states", () => {
  const markup = renderCategories();

  assert.match(markup, /Categorias/);
  assert.match(markup, /Organize e navegue pelo seu conhecimento/);
  assert.match(markup, /href="\/categories\/2"/);
  assert.match(markup, /Arduino/);
  assert.match(markup, /0 itens/);
  assert.match(markup, /href="\/categories\/7"/);
  assert.match(markup, /1 item/);

  assert.match(renderCategories({ items: [] }), /Você ainda não criou nenhuma categoria/);
  assert.match(renderCategories(null), /Categorias temporariamente indisponíveis/);
});

test("category detail reuses Reel cards and keeps exact category pagination", () => {
  const markup = renderDetail();

  assert.match(markup, /IoT/);
  assert.match(markup, /1 item/);
  assert.match(markup, /href="\/reels\/42"/);
  assert.match(markup, /Build a useful thing/);
  assert.match(markup, /href="\/categories\/7"/);
  assert.match(markup, /href="\/categories\/7\?page=3"/);
  assert.equal(buildCategoryUrl(7, 1), "/categories/7");
  assert.equal(buildCategoryUrl(7, 3), "/categories/7?page=3");
});

test("category detail has distinct empty, missing and unavailable states", () => {
  const empty = renderDetail({
    kind: "ok",
    data: {
      ...detail,
      category: { ...detail.category, reel_count: 0 },
      items: [],
      pagination: { page: 1, page_size: 12, has_previous: false, has_next: false },
    },
  });

  assert.match(empty, /Esta categoria ainda não possui Reels/);
  assert.match(renderDetail({ kind: "not-found" }), /Categoria não encontrada/);
  assert.match(renderDetail({ kind: "unavailable" }), /Categoria temporariamente indisponível/);
});

test("categories server adapters use owner cookie, no-store and internal API", async () => {
  const calls: Array<{ url: string; options?: RequestInit }> = [];
  const request = (async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(input), options: init });
    if (String(input).includes("/api/categories/7")) {
      return new Response(JSON.stringify(detail), { status: 200 });
    }
    return new Response(JSON.stringify(categories), { status: 200 });
  }) as typeof fetch;

  const incomingHeaders = new Headers({ cookie: "__Host-mb_session=opaque" });
  assert.deepEqual(await fetchCategories(request, incomingHeaders), categories);
  assert.deepEqual(
    await fetchCategoryDetail(7, 2, request, incomingHeaders),
    { kind: "ok", data: detail },
  );

  assert.equal(calls[0].url, "http://web:8000/api/categories");
  assert.equal(calls[1].url, "http://web:8000/api/categories/7?page=2");
  for (const call of calls) {
    assert.equal(call.options?.cache, "no-store");
    assert.equal(new Headers(call.options?.headers).get("cookie"), "__Host-mb_session=opaque");
  }
});

test("category detail adapter distinguishes 404, failure and malformed payloads", async () => {
  const headers = new Headers();
  const missing = (async () => new Response("missing", { status: 404 })) as typeof fetch;
  const unavailable = (async () => new Response("no", { status: 503 })) as typeof fetch;
  const malformed = (async () => new Response(JSON.stringify({ category: {} }), { status: 200 })) as typeof fetch;

  assert.deepEqual(await fetchCategoryDetail(7, 1, missing, headers), { kind: "not-found" });
  assert.deepEqual(await fetchCategoryDetail(7, 1, unavailable, headers), { kind: "unavailable" });
  assert.deepEqual(await fetchCategoryDetail(7, 1, malformed, headers), { kind: "unavailable" });
});

test("category mutation helper uses CSRF and distinguishes name conflicts", async () => {
  const calls: Array<{ url: string; options?: RequestInit }> = [];
  const request = (async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(input), options: init });
    if (String(input) === "/api/auth/csrf") {
      return new Response(JSON.stringify({ csrf_token: "token" }), { status: 200 });
    }
    if (String(input) === "/api/categories/7") {
      return new Response(null, { status: 409 });
    }
    return new Response(JSON.stringify({ category: { id: 7, name: "IoT" } }), { status: 201 });
  }) as typeof fetch;

  assert.equal(
    await performCategoryMutation("/api/categories", "POST", { name: "IoT" }, request),
    "ok",
  );
  assert.equal(
    await performCategoryMutation("/api/categories/7", "PATCH", { name: "IoT" }, request),
    "conflict",
  );

  const mutations = calls.filter((call) => call.url !== "/api/auth/csrf");
  for (const call of mutations) {
    assert.equal(call.options?.credentials, "same-origin");
    assert.equal(new Headers(call.options?.headers).get("x-csrf-token"), "token");
  }
});
