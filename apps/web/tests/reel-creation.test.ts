import assert from "node:assert/strict";
import test from "node:test";

import { JSDOM } from "jsdom";
import { act, createElement } from "react";

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
  downloadStatus = "received",
  curationStatus = "inbox",
  transcriptionStatus = "not_requested",
}: {
  created?: boolean;
  dispatch?: "accepted" | "not_required" | "unconfirmed";
  downloadStatus?: string;
  curationStatus?: string;
  transcriptionStatus?: string;
} = {}) {
  return {
    reel: {
      id: 42,
      shortcode: "abc_123",
      original_url: VALID_URL,
      download_status: downloadStatus,
      curation_status: curationStatus,
      transcription_status: transcriptionStatus,
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

function deferred<T>() {
  let resolve: (value: T) => void;
  let reject: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve: resolve!, reject: reject! };
}

type BrowserGlobal =
  | "window"
  | "document"
  | "navigator"
  | "Node"
  | "HTMLElement"
  | "HTMLDialogElement"
  | "HTMLInputElement"
  | "Event"
  | "MouseEvent"
  | "KeyboardEvent";

const browserGlobals: BrowserGlobal[] = [
  "window",
  "document",
  "navigator",
  "Node",
  "HTMLElement",
  "HTMLDialogElement",
  "HTMLInputElement",
  "Event",
  "MouseEvent",
  "KeyboardEvent",
];

type RenderedDialog = {
  document: Document;
  cleanup: () => Promise<void>;
};

async function renderDialog(): Promise<RenderedDialog> {
  const dom = new JSDOM("<!doctype html><html><body><div id=\"root\"></div></body></html>", {
    url: "http://localhost/",
  });
  const previousGlobals = new Map<BrowserGlobal, PropertyDescriptor | undefined>(
    browserGlobals.map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]),
  );
  const testGlobal = globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean };
  const previousActEnvironment = testGlobal.IS_REACT_ACT_ENVIRONMENT;
  const dialogPrototype = dom.window.HTMLDialogElement.prototype;
  const showModal = Object.getOwnPropertyDescriptor(dialogPrototype, "showModal");
  const close = Object.getOwnPropertyDescriptor(dialogPrototype, "close");

  const browserValues: Record<BrowserGlobal, unknown> = {
    window: dom.window,
    document: dom.window.document,
    navigator: dom.window.navigator,
    Node: dom.window.Node,
    HTMLElement: dom.window.HTMLElement,
    HTMLDialogElement: dom.window.HTMLDialogElement,
    HTMLInputElement: dom.window.HTMLInputElement,
    Event: dom.window.Event,
    MouseEvent: dom.window.MouseEvent,
    KeyboardEvent: dom.window.KeyboardEvent,
  };
  for (const key of browserGlobals) {
    Object.defineProperty(globalThis, key, {
      configurable: true,
      writable: true,
      value: browserValues[key],
    });
  }
  testGlobal.IS_REACT_ACT_ENVIRONMENT = true;

  Object.defineProperties(dialogPrototype, {
    showModal: {
      configurable: true,
      value(this: HTMLDialogElement) {
        this.setAttribute("open", "");
      },
    },
    close: {
      configurable: true,
      value(this: HTMLDialogElement) {
        this.removeAttribute("open");
        this.dispatchEvent(new dom.window.Event("close"));
      },
    },
  });

  const rootElement = dom.window.document.querySelector("#root");
  assert.ok(rootElement);
  const { createRoot } = await import("react-dom/client");
  const root = createRoot(rootElement);
  await act(async () => {
    root.render(createElement(AddReel));
  });

  return {
    document: dom.window.document,
    async cleanup() {
      await act(async () => {
        root.unmount();
      });
      if (showModal) Object.defineProperty(dialogPrototype, "showModal", showModal);
      else delete (dialogPrototype as { showModal?: unknown }).showModal;
      if (close) Object.defineProperty(dialogPrototype, "close", close);
      else delete (dialogPrototype as { close?: unknown }).close;
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

function button(document: Document, name: string): HTMLButtonElement {
  const element = Array.from(document.querySelectorAll("button")).find((candidate) => candidate.textContent === name);
  assert.ok(element, `missing ${name} button`);
  return element;
}

function input(document: Document): HTMLInputElement {
  const element = document.querySelector<HTMLInputElement>("#add-reel-url");
  assert.ok(element, "missing URL input");
  return element;
}

function dialog(document: Document): HTMLDialogElement {
  const element = document.querySelector<HTMLDialogElement>("dialog");
  assert.ok(element, "missing dialog");
  return element;
}

async function click(element: Element): Promise<void> {
  await act(async () => {
    element.dispatchEvent(new window.MouseEvent("click", { bubbles: true, cancelable: true }));
  });
}

async function setInputValue(element: HTMLInputElement, value: string): Promise<void> {
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set;
  assert.ok(setter, "missing input value setter");
  await act(async () => {
    setter.call(element, value);
    element.dispatchEvent(new window.Event("input", { bubbles: true }));
  });
}

async function submit(document: Document): Promise<void> {
  const form = document.querySelector("form");
  assert.ok(form, "missing form");
  await act(async () => {
    form.dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
    await Promise.resolve();
    await Promise.resolve();
  });
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

test("new Reel accepts only its valid created response shape and lifecycle", async () => {
  for (const dispatch of ["accepted", "unconfirmed"] as const) {
    const result = await performReelCreation(
      VALID_URL,
      successfulRequest(reelPayload({ dispatch }), 201, []),
    );
    assert.equal(result.ok, true);
  }

  const invalidNewResponses = [
    reelPayload({ dispatch: "not_required" }),
    reelPayload({ downloadStatus: "downloading" }),
    { ...reelPayload(), extra: true },
    { ...reelPayload(), reel: { ...reelPayload().reel, extra: true } },
    { ...reelPayload(), dispatch: { state: "accepted", extra: true } },
  ];

  for (const payload of invalidNewResponses) {
    assert.deepEqual(
      await performReelCreation(VALID_URL, successfulRequest(payload, 201, [])),
      { ok: false, code: "invalid_response" },
    );
  }
});

test("existing Reel accepts every known lifecycle and dispatch state only with 200", async () => {
  for (const dispatch of ["accepted", "not_required", "unconfirmed"] as const) {
    for (const downloadStatus of ["received", "downloading", "downloaded", "failed"]) {
      for (const curationStatus of ["inbox", "organized"]) {
        for (const transcriptionStatus of ["not_requested", "queued", "processing", "completed", "failed"]) {
          const result = await performReelCreation(
            VALID_URL,
            successfulRequest(
              reelPayload({ created: false, dispatch, downloadStatus, curationStatus, transcriptionStatus }),
              200,
              [],
            ),
          );
          assert.equal(result.ok, true);
        }
      }
    }
  }

  assert.deepEqual(
    await performReelCreation(VALID_URL, successfulRequest(reelPayload({ created: false }), 201, [])),
    { ok: false, code: "invalid_response" },
  );
  assert.deepEqual(
    await performReelCreation(
      VALID_URL,
      successfulRequest(reelPayload({ created: false, dispatch: "accepted", transcriptionStatus: "unknown" }), 200, []),
    ),
    { ok: false, code: "invalid_response" },
  );
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
  const request = (async (requestInput: RequestInfo | URL) => {
    if (String(requestInput) === "/api/auth/csrf") {
      return jsonResponse({ csrf_token: "csrf-token" });
    }
    throw new Error("private network detail");
  }) as typeof fetch;

  assert.deepEqual(
    await performReelCreation(VALID_URL, request),
    { ok: false, code: "network_error" },
  );
});

test("Add Reel opens, posts once while pending, and blocks cancellation until success", async () => {
  const previousFetch = globalThis.fetch;
  const creation = deferred<Response>();
  let postCalls = 0;
  globalThis.fetch = (async (requestInput: RequestInfo | URL) => {
    if (String(requestInput) === "/api/auth/csrf") {
      return jsonResponse({ csrf_token: "csrf-token" });
    }
    postCalls += 1;
    return creation.promise;
  }) as typeof fetch;

  const rendered = await renderDialog();
  try {
    await click(button(rendered.document, "+ Adicionar Reel"));
    assert.equal(dialog(rendered.document).open, true);

    await setInputValue(input(rendered.document), VALID_URL);
    await submit(rendered.document);

    assert.equal(postCalls, 1);
    assert.equal(input(rendered.document).disabled, true);
    assert.equal(button(rendered.document, "Fechar").disabled, true);
    assert.equal(button(rendered.document, "Cancelar").disabled, true);
    assert.equal(button(rendered.document, "Adicionando…").disabled, true);

    await submit(rendered.document);
    assert.equal(postCalls, 1);

    const cancel = new window.Event("cancel", { bubbles: true, cancelable: true });
    dialog(rendered.document).dispatchEvent(cancel);
    assert.equal(cancel.defaultPrevented, true);
    assert.equal(dialog(rendered.document).open, true);

    creation.resolve(jsonResponse(reelPayload(), 201));
    await act(async () => {
      await creation.promise;
      await Promise.resolve();
    });

    assert.match(rendered.document.body.textContent ?? "", /Reel adicionado\. O processamento foi iniciado\./);
    const link = rendered.document.querySelector<HTMLAnchorElement>("a[href='/reels/42']");
    assert.ok(link, "missing successful Reel link");
  } finally {
    globalThis.fetch = previousFetch;
    await rendered.cleanup();
  }
});

test("Add Reel shows an accessible error, restores focus, and resets after close", async () => {
  const previousFetch = globalThis.fetch;
  globalThis.fetch = (async (requestInput: RequestInfo | URL) => {
    if (String(requestInput) === "/api/auth/csrf") {
      return jsonResponse({ csrf_token: "csrf-token" });
    }
    return jsonResponse({ error: { code: "invalid_request" } }, 422);
  }) as typeof fetch;

  const rendered = await renderDialog();
  try {
    await click(button(rendered.document, "+ Adicionar Reel"));
    await setInputValue(input(rendered.document), VALID_URL);
    await submit(rendered.document);

    const urlInput = input(rendered.document);
    const error = rendered.document.querySelector("#add-reel-url-error[role='alert']");
    assert.ok(error, "missing stable error alert");
    assert.equal(urlInput.getAttribute("aria-invalid"), "true");
    assert.equal(urlInput.getAttribute("aria-describedby"), "add-reel-help add-reel-url-error");
    assert.equal(rendered.document.activeElement, urlInput);

    await click(button(rendered.document, "Cancelar"));
    assert.equal(dialog(rendered.document).open, false);
    await click(button(rendered.document, "+ Adicionar Reel"));
    assert.equal(input(rendered.document).value, "");
    assert.equal(input(rendered.document).getAttribute("aria-invalid"), null);
    assert.equal(input(rendered.document).getAttribute("aria-describedby"), "add-reel-help");
    assert.equal(rendered.document.querySelector("#add-reel-url-error"), null);
  } finally {
    globalThis.fetch = previousFetch;
    await rendered.cleanup();
  }
});

test("Add Reel reports an existing Reel as success", async () => {
  const previousFetch = globalThis.fetch;
  globalThis.fetch = (async (requestInput: RequestInfo | URL) => {
    if (String(requestInput) === "/api/auth/csrf") {
      return jsonResponse({ csrf_token: "csrf-token" });
    }
    return jsonResponse(reelPayload({ created: false, dispatch: "not_required", downloadStatus: "downloaded" }), 200);
  }) as typeof fetch;

  const rendered = await renderDialog();
  try {
    await click(button(rendered.document, "+ Adicionar Reel"));
    await setInputValue(input(rendered.document), VALID_URL);
    await submit(rendered.document);
    assert.match(rendered.document.body.textContent ?? "", /Este Reel já existe no MegaBrain\./);
  } finally {
    globalThis.fetch = previousFetch;
    await rendered.cleanup();
  }
});
