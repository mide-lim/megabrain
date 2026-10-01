import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { DevelopmentPageContent } from "../src/app/development/development-page-content";
import { fetchPaperclipAvailability } from "../src/app/development/paperclip-status";

function render(paperclipAvailable: boolean): string {
  return renderToStaticMarkup(createElement(DevelopmentPageContent, { paperclipAvailable }));
}

test(
  "development status card renders online and unavailable states while preserving the launch action",
  () => {
    const online = render(true);
    const unavailable = render(false);

    assert.match(online, /Paperclip online/);
    assert.match(unavailable, /Indisponível/);
    assert.match(online, /Abrir Paperclip/);
    assert.match(unavailable, /Abrir Paperclip/);
    assert.match(online, /role="status"/);
    assert.match(unavailable, /role="status"/);
  },
);

test("Paperclip availability uses the authenticated backend status and fails closed", async () => {
  const incomingHeaders = new Headers({ cookie: "__Host-mb_session=owner-session" });
  let requestedUrl = "";
  let requestedOptions: RequestInit | undefined;
  const onlineRequest = (async (input: string | URL | Request, options?: RequestInit) => {
    requestedUrl = String(input);
    requestedOptions = options;
    return Response.json({ available: true });
  }) as typeof fetch;

  assert.equal(await fetchPaperclipAvailability(onlineRequest, incomingHeaders), true);
  assert.equal(requestedUrl, "http://web:8000/api/platform/paperclip/status");
  assert.equal(
    new Headers(requestedOptions?.headers).get("cookie"),
    "__Host-mb_session=owner-session",
  );
  assert.equal(requestedOptions?.cache, "no-store");

  const unavailableRequest = (async () => Response.json({ available: false })) as typeof fetch;
  const malformedRequest = (async () => Response.json({ available: "yes" })) as typeof fetch;
  const failedRequest = (async () => new Response("unavailable", { status: 503 })) as typeof fetch;
  const networkFailure = (async () => {
    throw new Error("offline");
  }) as typeof fetch;

  assert.equal(await fetchPaperclipAvailability(unavailableRequest, incomingHeaders), false);
  assert.equal(await fetchPaperclipAvailability(malformedRequest, incomingHeaders), false);
  assert.equal(await fetchPaperclipAvailability(failedRequest, incomingHeaders), false);
  assert.equal(await fetchPaperclipAvailability(networkFailure, incomingHeaders), false);
});

test("development authenticates before checking Paperclip availability", async () => {
  const source = await readFile(
    new URL("../src/app/development/page.tsx", import.meta.url),
    "utf8",
  );

  assert.ok(source.indexOf("await requireOwnerSession()") >= 0);
  assert.ok(
    source.indexOf("await fetchPaperclipAvailability()") >
      source.indexOf("await requireOwnerSession()"),
  );
});
