import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { fetchLibraryPage, type LibraryResponse } from "../src/app/library/library-api";
import { buildInboxUrl, InboxPageContent } from "../src/app/inbox/inbox-page-content";

const inbox: LibraryResponse = {
  items: [{
    id: 42,
    title: "Novo Reel",
    creator: "maker",
    shortcode: "abc123",
    caption: "capturado agora",
    categories: [],
    duration_seconds: 10,
    received_at: "2026-09-28T00:00:00Z",
    has_transcript: false,
    download_status: "downloaded",
    curation_status: "inbox",
    transcription_status: "not_requested",
  }],
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

test("inbox authenticates before fetching filtered data", async () => {
  const source = await readFile(new URL("../src/app/inbox/page.tsx", import.meta.url), "utf8");
  assert.ok(source.indexOf("await requireOwnerSession()") >= 0);
  assert.ok(source.indexOf("await fetchLibraryPage") > source.indexOf("await requireOwnerSession()"));
  assert.match(source, /curationStatus: "inbox"/);
});

test("inbox renders real Reel cards and pagination", () => {
  const markup = render();
  assert.match(markup, /Novo Reel/);
  assert.match(markup, /href="\/reels\/42"/);
  assert.match(markup, /Inbox/);
  assert.match(markup, /Organizar/);
  assert.match(markup, /href="\/inbox"/);
  assert.match(markup, /href="\/inbox\?page=3"/);
  assert.equal(buildInboxUrl(1), "/inbox");
  assert.equal(buildInboxUrl(3), "/inbox?page=3");
});

test("inbox has distinct empty and unavailable states", () => {
  const empty = render({
    items: [],
    query: { q: "" },
    pagination: { page: 1, page_size: 12, has_previous: false, has_next: false },
  });
  assert.match(empty, /Inbox vazia/);
  assert.match(empty, /Você não tem Reels aguardando organização/);
  assert.match(render(null), /Inbox temporariamente indisponível/);
});

test("inbox API request uses exact curation filter", async () => {
  let requestedUrl = "";
  const request = (async (input: RequestInfo | URL) => {
    requestedUrl = String(input);
    return new Response(JSON.stringify(inbox), { status: 200 });
  }) as typeof fetch;

  const result = await fetchLibraryPage(
    { page: 2, q: "", curationStatus: "inbox" },
    request,
    new Headers({ cookie: "__Host-mb_session=opaque" }),
  );

  assert.deepEqual(result, inbox);
  assert.equal(requestedUrl, "http://web:8000/api/reels?page=2&curation_status=inbox");
});

test("inbox refresh is requested only after server-confirmed curation", async () => {
  const lifecycleSource = await readFile(new URL("../src/components/reel-lifecycle.tsx", import.meta.url), "utf8");
  const cardSource = await readFile(new URL("../src/app/library/library-page-content.tsx", import.meta.url), "utf8");
  const inboxSource = await readFile(new URL("../src/app/inbox/inbox-page-content.tsx", import.meta.url), "utf8");

  assert.ok(lifecycleSource.indexOf("const confirmed = await performCurationMutation") < lifecycleSource.indexOf("router.refresh()"));
  assert.match(lifecycleSource, /if \(refreshOnCuration\)/);
  assert.match(cardSource, /refreshOnCuration=\{refreshOnCuration\}/);
  assert.match(inboxSource, /refreshOnCuration/);
});
