import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { fetchInboxPage, buildInboxUrl } from "../src/app/inbox/inbox-api";
import { InboxPageContent } from "../src/app/inbox/inbox-page-content";
import type { LibraryResponse } from "../src/app/library/library-api";

const inbox: LibraryResponse = {
  items: [
    {
      id: 42,
      title: "Novo Reel",
      creator: "maker",
      shortcode: "abc123",
      caption: "conteúdo novo",
      categories: ["code"],
      duration_seconds: 40,
      received_at: "2026-09-28T00:00:00Z",
      has_transcript: false,
      download_status: "downloaded",
      curation_status: "inbox",
      transcription_status: "not_requested",
    },
  ],
  query: { q: "" },
  pagination: {
    page: 2,
    page_size: 12,
    has_previous: true,
    has_next: true,
  },
};

function render(value: LibraryResponse | null = inbox): string {
  return renderToStaticMarkup(createElement(InboxPageContent, { inbox: value }));
}

test("inbox authenticates before fetching its filtered page", async () => {
  const source = await readFile(
    new URL("../src/app/inbox/page.tsx", import.meta.url),
    "utf8",
  );

  assert.ok(source.indexOf("await requireOwnerSession()") >= 0);
  assert.ok(source.indexOf("await fetchInboxPage(page)") > source.indexOf("await requireOwnerSession()"));
  assert.doesNotMatch(source, /["']use client["']/);
});

test("inbox lists only its supplied triage cards and supports pagination", () => {
  const markup = render();

  assert.match(markup, /Reels capturados que ainda precisam da sua triagem/);
  assert.match(markup, /Novo Reel/);
  assert.match(markup, /Inbox/);
  assert.match(markup, /Organizar/);
  assert.match(markup, /href="\/reels\/42"/);
  assert.match(markup, /href="\/inbox"/);
  assert.match(markup, /href="\/inbox\?page=3"/);
  assert.equal(buildInboxUrl(1), "/inbox");
  assert.equal(buildInboxUrl(3), "/inbox?page=3");
});

test("inbox has distinct empty and unavailable states", () => {
  const empty: LibraryResponse = {
    items: [],
    query: { q: "" },
    pagination: { page: 1, page_size: 12, has_previous: false, has_next: false },
  };

  assert.match(render(empty), /Inbox em dia/);
  assert.match(render(null), /Inbox temporariamente indisponível/);
});

test("inbox API helper requests the exact inbox curation filter", async () => {
  let requestedUrl = "";
  let requestOptions: RequestInit | undefined;
  const request = (async (input: RequestInfo | URL, init?: RequestInit) => {
    requestedUrl = String(input);
    requestOptions = init;
    return new Response(JSON.stringify(inbox), { status: 200 });
  }) as typeof fetch;

  const response = await fetchInboxPage(
    2,
    request,
    new Headers({ cookie: "__Host-mb_session=opaque" }),
  );

  assert.deepEqual(response, inbox);
  assert.equal(
    requestedUrl,
    "http://web:8000/api/reels?page=2&curation_status=inbox",
  );
  assert.equal(requestOptions?.cache, "no-store");
  assert.equal(
    new Headers(requestOptions?.headers).get("cookie"),
    "__Host-mb_session=opaque",
  );
});

test("inbox cards request a reload after successful curation changes", async () => {
  const cardSource = await readFile(
    new URL("../src/app/library/library-page-content.tsx", import.meta.url),
    "utf8",
  );
  const lifecycleSource = await readFile(
    new URL("../src/components/reel-lifecycle.tsx", import.meta.url),
    "utf8",
  );

  assert.match(cardSource, /reloadAfterCurationChange/);
  assert.match(lifecycleSource, /window\.location\.reload\(\)/);
});
