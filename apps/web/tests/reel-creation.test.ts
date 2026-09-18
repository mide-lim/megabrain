import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { AddReel } from "../src/components/add-reel";
import { performReelCreation } from "../src/lib/reel-creation-api";

const VALID_URL = "https://www.instagram.com/reel/abc_123/";

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function reelPayload({
  created = true,
  dispatch = "accepted",
}: {
  created?: boolean;
  dispatch?: "accepted" | "not_required" | "unconfirmed";
} = {}) {
  return {
    reel: {
      id: 42,
      shortcode: "abc_123",
      original_url: VALID_URL,
      download_status: "received",
      curation_status: "inbox",
      transcription_status: "not_requested",
      created,
    },
    dispatch: { state: dispatch },
  };
}

function successfulRequest(
  payload: unknown,
  status: number,
  calls: Array<{ url: string; init?: RequestInit }>,
): typeof fetch {
  return (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, init });
    if (url === "/api/auth/csrf") {
      return jsonResponse({ csrf_token: "csrf-token" });
    }
    assert.equal(url, "/api/reels");
    return jsonResponse(payload, status);
  }) as typeof fetch;
}

test("Reel creation bootstraps CSRF before posting the strict public API request", async () => {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  const result = await performReelCreation(
    `  ${VALID_URL}  `,
    successfulRequest(reelPayload(), 201, calls),
  );

  assert.equal(result.ok, true);
  assert.equal(calls.length, 2);
  assert.equal(calls[0]?.url, "/api/auth/csrf");
  assert.equal(calls[0]?.init?.cache, "no-store");
  assert.equal(calls[0]?.init?.credentials, "same-origin");

  assert.equal(calls[1]?.url, "/api/reels");
  assert.equal(calls[1]?.init?.method, "POST");
  assert.equal(calls[1]?.init?.credentials, "same-origin");

  const headers = new Headers(calls[1]?.init?.headers);
  assert.equal(headers.get("content-type"), "application/json");
  assert.equal(headers.get("x-csrf-token"), "csrf-token");
  assert.equal(headers.get("accept"), "application/json");
  assert.equal(calls[1]?.init?.body, JSON.stringify({ url: VALID_URL }));
});

test("new Reel accepts both confirmed and unconfirmed durable dispatch outcomes", async () => {
  for (const dispatch of ["accepted", "unconfirmed"] as const) {
    const result = await performReelCreation(
      VALID_URL,
      successfulRequest(reelPayload({ dispatch }), 201, []),
    );

    assert.equal(result.ok, true);
    if (result.ok) {
      assert.equal(result.reel.created, true);
      assert.equal(result.reel.id, 42);
      assert.equal(result.dispatch.state, dispatch);
    }
  }
});

test("existing Reel remains a successful idempotent response for all supported dispatch states", async () => {
  for (const dispatch of ["accepted", "not_required", "unconfirmed"] as const) {
    const result = await performReelCreation(
      VALID_URL,
      successfulRequest(reelPayload({ created: false, dispatch }), 200, []),
    );

    assert.equal(result.ok, true);
    if (result.ok) {
      assert.equal(result.reel.created, false);
      assert.equal(result.dispatch.state, dispatch);
    }
  }
});

test("public error statuses map to bounded UI codes without trusting server messages", async () => {
  const cases: Array<[number, unknown, string]> = [
    [401, { detail: "private" }, "session_unavailable"],
    [403, { detail: "private" }, "csrf_unavailable"],
    [409, { error: { code: "reel_identity_conflict", message: "private" } }, "identity_conflict"],
    [422, { error: { code: "invalid_request", message: "private" } }, "invalid_request"],
    [503, { error: { code: "registration_unavailable", message: "private" } }, "registration_unavailable"],
    [503, { error: { code: "reel_dispatch_unavailable", message: "private" } }, "dispatch_unavailable"],
  ];

  for (const [status, payload, expectedCode] of cases) {
    const result = await performReelCreation(
      VALID_URL,
      successfulRequest(payload, status, []),
    );

    assert.deepEqual(result, { ok: false, code: expectedCode });
  }
});

test("missing CSRF fails closed before the Reel mutation", async () => {
  const calls: string[] = [];
  const request = (async (input: RequestInfo | URL) => {
    calls.push(String(input));
    return jsonResponse({ detail: "Authentication required" }, 401);
  }) as typeof fetch;

  assert.deepEqual(
    await performReelCreation(VALID_URL, request),
    { ok: false, code: "csrf_unavailable" },
  );
  assert.deepEqual(calls, ["/api/auth/csrf"]);
});

test("empty input fails locally without touching CSRF or the creation endpoint", async () => {
  const request = (async () => {
    throw new Error("request must not run");
  }) as typeof fetch;

  assert.deepEqual(
    await performReelCreation("   ", request),
    { ok: false, code: "invalid_request" },
  );
});

test("network failure after CSRF is bounded", async () => {
  const request = (async (input: RequestInfo | URL) => {
    if (String(input) === "/api/auth/csrf") {
      return jsonResponse({ csrf_token: "csrf-token" });
    }
    throw new Error("private network detail");
  }) as typeof fetch;

  assert.deepEqual(
    await performReelCreation(VALID_URL, request),
    { ok: false, code: "network_error" },
  );
});

test("malformed or lifecycle-inconsistent success payloads fail closed", async () => {
  const malformed = await performReelCreation(
    VALID_URL,
    successfulRequest({ reel: { id: 42 }, dispatch: { state: "accepted" } }, 201, []),
  );
  const unknownLifecycle = await performReelCreation(
    VALID_URL,
    successfulRequest(
      {
        ...reelPayload(),
        reel: { ...reelPayload().reel, download_status: "mystery" },
      },
      201,
      [],
    ),
  );
  const wrongStatusForCreated = await performReelCreation(
    VALID_URL,
    successfulRequest(reelPayload({ created: true }), 200, []),
  );

  assert.deepEqual(malformed, { ok: false, code: "invalid_response" });
  assert.deepEqual(unknownLifecycle, { ok: false, code: "invalid_response" });
  assert.deepEqual(wrongStatusForCreated, { ok: false, code: "invalid_response" });
});

test("Add Reel renders an accessible native dialog and safe default form", () => {
  const markup = renderToStaticMarkup(createElement(AddReel));

  assert.match(markup, />\+ Adicionar Reel</);
  assert.match(markup, /<dialog[^>]+aria-labelledby="add-reel-title"/);
  assert.match(markup, /<label[^>]+for="add-reel-url"[^>]*>URL do Reel<\/label>/);
  assert.match(markup, /id="add-reel-url"/);
  assert.match(markup, /type="url"/);
  assert.match(markup, /required=""/);
  assert.match(markup, />Cancelar</);
  assert.match(markup, />Adicionar</);
  assert.doesNotMatch(markup, /Em breve/);
});

test("Add Reel source exposes bounded loading, success, duplicate, unconfirmed, and error states", async () => {
  const source = await readFile(new URL("../src/components/add-reel.tsx", import.meta.url), "utf8");

  assert.match(source, /"use client"/);
  assert.match(source, /showModal\(\)/);
  assert.match(source, /disabled=\{pending\}/);
  assert.match(source, /aria-busy=\{pending\}/);
  assert.match(source, /Adicionando Reel/);
  assert.match(source, /Reel adicionado\. O processamento foi iniciado\./);
  assert.match(source, /Este Reel já existe no MegaBrain\./);
  assert.match(source, /Ainda não foi possível confirmar/);
  assert.match(source, /role="alert"/);
  assert.match(source, /role="status"/);
  assert.match(source, /href=\{\`\/reels\/\$\{success\.reel\.id\}\`\}/);
  assert.doesNotMatch(source, /localStorage|sessionStorage|document\.cookie/);
});
