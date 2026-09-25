import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { JSDOM } from "jsdom";
import { act, createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { AppRouterContext, type AppRouterInstance } from "next/dist/shared/lib/app-router-context.shared-runtime";

import { ReelTranscriptionControls } from "../src/app/reels/[reelId]/reel-transcription-controls";
import { requestReelTranscription } from "../src/lib/reel-transcription-api";
import type { ReelLifecycleProjection } from "../src/lib/reel-lifecycle";

const downloadedNotRequested: ReelLifecycleProjection = {
  id: 42,
  download_status: "downloaded",
  curation_status: "organized",
  transcription_status: "not_requested",
};

const transcript = {
  available: true,
  text: "Texto canônico da transcrição",
  language: "pt-BR",
  completed_at: "2026-09-01T00:00:00Z",
};

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), { status, headers: { "Content-Type": "application/json" } });
}

function lifecycle(status: ReelLifecycleProjection["transcription_status"]): ReelLifecycleProjection {
  return { ...downloadedNotRequested, transcription_status: status };
}

function deferred<T>() {
  let resolve: (value: T) => void;
  let reject: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve: resolve!, reject: reject! };
}

function router(refresh: () => void = () => undefined): AppRouterInstance {
  return {
    back: () => undefined,
    bfcacheId: "test-router",
    forward: () => undefined,
    prefetch: () => undefined,
    push: () => undefined,
    refresh,
    replace: () => undefined,
  };
}

function markup(value: ReelLifecycleProjection): string {
  return renderToStaticMarkup(
    createElement(
      AppRouterContext.Provider,
      { value: router() },
      createElement(ReelTranscriptionControls, { lifecycle: value, transcript }),
    ),
  );
}

test("transcription request bootstraps CSRF and posts exactly an empty JSON object", async () => {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  const request = (async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(input), init });
    if (String(input) === "/api/auth/csrf") {
      return jsonResponse({ csrf_token: "csrf-token" });
    }
    return jsonResponse(lifecycle("queued"), 202);
  }) as typeof fetch;

  assert.deepEqual(await requestReelTranscription(42, request), lifecycle("queued"));
  assert.equal(calls.length, 2);
  assert.equal(calls[0]?.url, "/api/auth/csrf");
  assert.equal(calls[0]?.init?.credentials, "same-origin");
  assert.equal(calls[1]?.url, "/api/reels/42/transcription");
  assert.equal(calls[1]?.init?.method, "POST");
  assert.equal(calls[1]?.init?.credentials, "same-origin");
  assert.equal(new Headers(calls[1]?.init?.headers).get("content-type"), "application/json");
  assert.equal(new Headers(calls[1]?.init?.headers).get("x-csrf-token"), "csrf-token");
  assert.equal(calls[1]?.init?.body, "{}");
});

test("transcription helper accepts only 200 or 202 valid lifecycle responses for the requested Reel", async () => {
  const valid200 = (async (input: RequestInfo | URL) => {
    if (String(input) === "/api/auth/csrf") return jsonResponse({ csrf_token: "csrf-token" });
    return jsonResponse(lifecycle("completed"), 200);
  }) as typeof fetch;
  assert.deepEqual(await requestReelTranscription(42, valid200), lifecycle("completed"));

  const malformed = (async (input: RequestInfo | URL) => {
    if (String(input) === "/api/auth/csrf") return jsonResponse({ csrf_token: "csrf-token" });
    return jsonResponse({ id: 42, transcription_status: "queued" }, 202);
  }) as typeof fetch;
  assert.equal(await requestReelTranscription(42, malformed), null);

  const wrongReel = (async (input: RequestInfo | URL) => {
    if (String(input) === "/api/auth/csrf") return jsonResponse({ csrf_token: "csrf-token" });
    return jsonResponse({ ...lifecycle("queued"), id: 43 }, 202);
  }) as typeof fetch;
  assert.equal(await requestReelTranscription(42, wrongReel), null);
});

test("transcription controls render only the approved action and status surfaces", () => {
  assert.match(markup(downloadedNotRequested), /Ainda não solicitada\./);
  assert.match(markup(downloadedNotRequested), />Transcrever</);

  const beforeDownload = markup({ ...downloadedNotRequested, download_status: "downloading" });
  assert.match(beforeDownload, /A transcrição ficará disponível após o download do Reel\./);
  assert.doesNotMatch(beforeDownload, />Transcrever</);

  const queued = markup(lifecycle("queued"));
  assert.match(queued, /Na fila para transcrição\./);
  assert.doesNotMatch(queued, />Transcrever</);

  const processing = markup(lifecycle("processing"));
  assert.match(processing, /Transcrevendo…/);
  assert.doesNotMatch(processing, />Transcrever</);

  const completed = markup(lifecycle("completed"));
  assert.match(completed, /Texto canônico da transcrição/);
  assert.match(completed, /Idioma: pt-BR/);
  assert.match(completed, /Concluída em/);
  assert.doesNotMatch(completed, /Transcrever novamente|Tentar novamente/);

  const failed = markup(lifecycle("failed"));
  assert.match(failed, /Não foi possível concluir a transcrição\./);
  assert.match(failed, />Tentar novamente</);
});

type BrowserGlobal = "window" | "document" | "navigator" | "Node" | "HTMLElement" | "Event" | "MouseEvent";
const browserGlobals: BrowserGlobal[] = ["window", "document", "navigator", "Node", "HTMLElement", "Event", "MouseEvent"];

type RenderedControls = {
  document: Document;
  refreshes: number[];
  timers: Map<number, () => void>;
  rerender: (nextLifecycle: ReelLifecycleProjection) => Promise<void>;
  cleanup: () => Promise<void>;
};

async function renderControls(initialLifecycle: ReelLifecycleProjection): Promise<RenderedControls> {
  const dom = new JSDOM("<!doctype html><html><body><div id=\"root\"></div></body></html>", { url: "http://localhost/" });
  const previousGlobals = new Map<BrowserGlobal, PropertyDescriptor | undefined>(browserGlobals.map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  const testGlobal = globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean };
  const previousActEnvironment = testGlobal.IS_REACT_ACT_ENVIRONMENT;
  for (const key of browserGlobals) {
    Object.defineProperty(globalThis, key, { configurable: true, writable: true, value: dom.window[key] });
  }
  testGlobal.IS_REACT_ACT_ENVIRONMENT = true;

  let nextTimerId = 1;
  const timers = new Map<number, () => void>();
  const originalSetTimeout = dom.window.setTimeout;
  const originalClearTimeout = dom.window.clearTimeout;
  dom.window.setTimeout = ((callback: TimerHandler) => {
    const timerId = nextTimerId++;
    timers.set(timerId, () => {
      if (typeof callback === "function") callback();
    });
    return timerId;
  }) as typeof dom.window.setTimeout;
  dom.window.clearTimeout = ((timerId?: number) => {
    if (timerId !== undefined) timers.delete(timerId);
  }) as typeof dom.window.clearTimeout;

  const refreshes: number[] = [];
  const rootElement = dom.window.document.querySelector("#root");
  assert.ok(rootElement);
  const { createRoot } = await import("react-dom/client");
  const root = createRoot(rootElement);
  const render = async (currentLifecycle: ReelLifecycleProjection) => {
    await act(async () => {
      root.render(createElement(
        AppRouterContext.Provider,
        { value: router(() => refreshes.push(Date.now())) },
        createElement(ReelTranscriptionControls, { key: `${currentLifecycle.id}:${currentLifecycle.transcription_status}`, lifecycle: currentLifecycle, transcript }),
      ));
    });
  };
  await render(initialLifecycle);

  return {
    document: dom.window.document,
    refreshes,
    timers,
    rerender: render,
    async cleanup() {
      await act(async () => {
        root.unmount();
      });
      dom.window.setTimeout = originalSetTimeout;
      dom.window.clearTimeout = originalClearTimeout;
      for (const key of browserGlobals) {
        const descriptor = previousGlobals.get(key);
        if (descriptor) Object.defineProperty(globalThis, key, descriptor);
        else delete (globalThis as Partial<Record<BrowserGlobal, unknown>>)[key];
      }
      testGlobal.IS_REACT_ACT_ENVIRONMENT = previousActEnvironment;
      dom.window.close();
    },
  };
}

function button(document: Document, label: string): HTMLButtonElement {
  const element = Array.from(document.querySelectorAll("button")).find((candidate) => candidate.textContent === label);
  assert.ok(element, `missing ${label} button`);
  return element;
}

async function click(element: Element): Promise<void> {
  await act(async () => {
    element.dispatchEvent(new window.MouseEvent("click", { bubbles: true, cancelable: true }));
    await Promise.resolve();
    await Promise.resolve();
  });
}

test("request and retry use one POST while pending, adopt only confirmed lifecycle, and refresh", async () => {
  const previousFetch = globalThis.fetch;
  const post = deferred<Response>();
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(input), init });
    if (String(input) === "/api/auth/csrf") return jsonResponse({ csrf_token: "csrf-token" });
    return post.promise;
  }) as typeof fetch;

  const rendered = await renderControls(downloadedNotRequested);
  try {
    await click(button(rendered.document, "Transcrever"));
    assert.equal(button(rendered.document, "Solicitando…").disabled, true);
    await click(button(rendered.document, "Solicitando…"));
    assert.equal(calls.filter((call) => call.url === "/api/reels/42/transcription").length, 1);

    post.resolve(jsonResponse(lifecycle("queued"), 202));
    await act(async () => {
      await post.promise;
      await Promise.resolve();
      await Promise.resolve();
    });
    assert.match(rendered.document.body.textContent ?? "", /Na fila para transcrição\./);
    assert.equal(rendered.refreshes.length, 1);

    await rendered.rerender(lifecycle("failed"));
    await click(button(rendered.document, "Tentar novamente"));
    assert.equal(calls.filter((call) => call.url === "/api/reels/42/transcription").length, 2);
    assert.equal(calls.filter((call) => call.url === "/api/auth/csrf").length, 2);
    const retry = calls.at(-1);
    assert.equal(retry?.init?.body, "{}");
  } finally {
    globalThis.fetch = previousFetch;
    await rendered.cleanup();
  }
});

test("network and invalid successful responses retain the confirmed lifecycle with a bounded alert", async () => {
  const previousFetch = globalThis.fetch;
  const failureRequests: Array<typeof fetch> = [
    (async (input: RequestInfo | URL) => {
      if (String(input) === "/api/auth/csrf") return jsonResponse({ csrf_token: "csrf-token" });
      throw new Error("private provider error");
    }) as typeof fetch,
    (async (input: RequestInfo | URL) => {
      if (String(input) === "/api/auth/csrf") return jsonResponse({ csrf_token: "csrf-token" });
      return jsonResponse({ id: 42, transcription_status: "queued" }, 202);
    }) as typeof fetch,
  ];

  try {
    for (const request of failureRequests) {
      globalThis.fetch = request;
      const rendered = await renderControls(downloadedNotRequested);
      try {
        await click(button(rendered.document, "Transcrever"));
        const alert = rendered.document.querySelector("[role='alert']");
        assert.ok(alert, "missing bounded failure alert");
        assert.equal(alert.textContent, "Não foi possível solicitar a transcrição. Tente novamente.");
        assert.match(rendered.document.body.textContent ?? "", /Ainda não solicitada\./);
        assert.equal(rendered.refreshes.length, 0);
      } finally {
        await rendered.cleanup();
      }
    }
  } finally {
    globalThis.fetch = previousFetch;
  }
});

test("queued and processing poll once, stop at terminal state, and clear timers on unmount", async () => {
  const queued = await renderControls(lifecycle("queued"));
  try {
    assert.equal(queued.timers.size, 1);
    const scheduled = queued.timers.values().next().value;
    assert.ok(scheduled);
    scheduled();
    assert.equal(queued.refreshes.length, 1);

    await queued.rerender(lifecycle("completed"));
    assert.equal(queued.timers.size, 0);
  } finally {
    await queued.cleanup();
  }

  const processing = await renderControls(lifecycle("processing"));
  try {
    assert.equal(processing.timers.size, 1);
    await processing.cleanup();
    assert.equal(processing.timers.size, 0);
  } finally {
    if (processing.timers.size > 0) await processing.cleanup();
  }
});

test("TC3 browser code has no direct provider or pipeline integration", async () => {
  const sources = await Promise.all([
    readFile(new URL("../src/app/reels/[reelId]/reel-transcription-controls.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/lib/reel-transcription-api.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/app/reels/[reelId]/reel-detail-page-content.tsx", import.meta.url), "utf8"),
  ]);
  const browserSource = sources.join("\n");
  assert.doesNotMatch(browserSource, /n8n|Google STT|Google Cloud Storage|Cloudflare R2|provider_request_id|attempt_id|GCS|R2/i);
  assert.match(browserSource, /\/api\/reels\/\$\{reelId\}\/transcription/);
});
