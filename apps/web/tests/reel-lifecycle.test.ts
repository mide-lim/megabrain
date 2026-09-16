import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import {
  curationStatusPresentation,
  downloadStatusPresentation,
  ReelLifecycle,
  transcriptionStatusPresentation,
} from "../src/components/reel-lifecycle";
import {
  performCurationMutation,
  reconcileLifecycleProjection,
} from "../src/lib/reel-curation-api";
import {
  lifecycleKey,
  type ReelLifecycleProjection,
} from "../src/lib/reel-lifecycle";

const lifecycle: ReelLifecycleProjection = {
  id: 42,
  download_status: "downloaded",
  curation_status: "inbox",
  transcription_status: "completed",
};

function renderLifecycle(projection: ReelLifecycleProjection = lifecycle, compact = false): string {
  return renderToStaticMarkup(createElement(ReelLifecycle, { compact, lifecycle: projection, reelId: projection.id }));
}

test("lifecycle key changes only when the server-confirmed projection changes", () => {
  assert.equal(lifecycleKey(lifecycle), "42:downloaded:inbox:completed");
  assert.equal(lifecycleKey({ ...lifecycle }), lifecycleKey(lifecycle));
  assert.notEqual(lifecycleKey({ ...lifecycle, transcription_status: "processing" }), lifecycleKey(lifecycle));
});

test("central lifecycle presentation maps every approved status to readable safe labels", () => {
  assert.deepEqual(downloadStatusPresentation("received"), { label: "Recebido", description: "Aguardando download", tone: "muted" });
  assert.deepEqual(downloadStatusPresentation("downloading"), { label: "Baixando", description: "Download em andamento", tone: "warning" });
  assert.deepEqual(downloadStatusPresentation("downloaded"), { label: "Disponível", description: "Mídia disponível", tone: "success" });
  assert.deepEqual(downloadStatusPresentation("failed"), { label: "Falhou", description: "Problema no download", tone: "danger" });

  assert.deepEqual(transcriptionStatusPresentation("not_requested"), { label: "Não solicitada", description: "Ainda não entrou em processamento", tone: "muted" });
  assert.deepEqual(transcriptionStatusPresentation("queued"), { label: "Na fila", description: "Aguardando processamento", tone: "warning" });
  assert.deepEqual(transcriptionStatusPresentation("processing"), { label: "Em processamento", description: "Transcrição e enriquecimento em andamento", tone: "warning" });
  assert.deepEqual(transcriptionStatusPresentation("completed"), { label: "Concluída", description: "Processamento concluído", tone: "success" });
  assert.deepEqual(transcriptionStatusPresentation("failed"), { label: "Falhou", description: "Transcrição ou enriquecimento falhou", tone: "danger" });

  assert.deepEqual(curationStatusPresentation("inbox"), { label: "Inbox", description: "Aguardando organização", tone: "muted" });
  assert.deepEqual(curationStatusPresentation("organized"), { label: "Organizado", description: "Organizado por você", tone: "success" });
});

test("unknown lifecycle values fail safely without inventing a lifecycle state", () => {
  assert.deepEqual(downloadStatusPresentation("unexpected"), { label: "Desconhecido", description: "Estado não reconhecido", tone: "danger" });
  assert.deepEqual(transcriptionStatusPresentation("unexpected"), { label: "Desconhecido", description: "Estado não reconhecido", tone: "danger" });
  assert.deepEqual(curationStatusPresentation("unexpected"), { label: "Desconhecido", description: "Estado não reconhecido", tone: "danger" });
});

test("lifecycle UI separates system processing from user organization and supports both curation actions", () => {
  const inboxMarkup = renderLifecycle();
  const organizedMarkup = renderLifecycle({ ...lifecycle, curation_status: "organized" });

  assert.match(inboxMarkup, /Estado do sistema/);
  assert.match(inboxMarkup, /Download/);
  assert.match(inboxMarkup, /Transcrição/);
  assert.match(inboxMarkup, /Organização/);
  assert.match(inboxMarkup, /Inbox/);
  assert.match(inboxMarkup, /Organizar/);
  assert.match(inboxMarkup, /aria-label="Organizar Reel"/);
  assert.match(organizedMarkup, /Organizado/);
  assert.match(organizedMarkup, /Mover para Inbox/);
  assert.match(organizedMarkup, /aria-label="Mover Reel para Inbox"/);
  assert.match(inboxMarkup, /Processamento concluído/);
  assert.doesNotMatch(inboxMarkup, /texto da transcrição|transcript text/i);
});

test("compact lifecycle UI remains readable and source-independent", () => {
  const markup = renderLifecycle(lifecycle, true);

  assert.match(markup, /Download/);
  assert.match(markup, /Disponível/);
  assert.match(markup, /Transcrição/);
  assert.match(markup, /Concluída/);
  assert.match(markup, /Organização/);
  assert.match(markup, /Inbox/);
});

test("curation PATCH reuses same-origin CSRF and sends only the approved field", async () => {
  const calls: Array<{ url: string; options?: RequestInit }> = [];
  const confirmed: ReelLifecycleProjection = { ...lifecycle, curation_status: "organized" };
  const request = (async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(input), options: init });
    if (String(input) === "/api/auth/csrf") {
      return new Response(JSON.stringify({ csrf_token: "short-lived-token" }), { status: 200 });
    }
    return new Response(JSON.stringify(confirmed), { status: 200 });
  }) as typeof fetch;

  assert.deepEqual(await performCurationMutation(42, "organized", request), confirmed);
  assert.equal(calls.length, 2);
  assert.equal(calls[0].url, "/api/auth/csrf");
  assert.equal(calls[1].url, "/api/reels/42/curation");
  assert.equal(calls[1].options?.method, "PATCH");
  assert.equal(calls[1].options?.credentials, "same-origin");
  assert.equal(new Headers(calls[1].options?.headers).get("x-csrf-token"), "short-lived-token");
  assert.equal(new Headers(calls[1].options?.headers).get("content-type"), "application/json");
  assert.deepEqual(JSON.parse(String(calls[1].options?.body)), { curation_status: "organized" });
});

test("curation response is authoritative, idempotent, and failure keeps the confirmed state", async () => {
  const sameState = { ...lifecycle, curation_status: "inbox" as const };
  const request = (async (input: RequestInfo | URL) => {
    if (String(input) === "/api/auth/csrf") {
      return new Response(JSON.stringify({ csrf_token: "short-lived-token" }), { status: 200 });
    }
    return new Response(JSON.stringify(sameState), { status: 200 });
  }) as typeof fetch;
  const failedPatchRequest = (async (input: RequestInfo | URL) => {
    if (String(input) === "/api/auth/csrf") {
      return new Response(JSON.stringify({ csrf_token: "short-lived-token" }), { status: 200 });
    }
    return new Response("unavailable", { status: 503 });
  }) as typeof fetch;
  const malformedResponseRequest = (async (input: RequestInfo | URL) => {
    if (String(input) === "/api/auth/csrf") {
      return new Response(JSON.stringify({ csrf_token: "short-lived-token" }), { status: 200 });
    }
    return new Response(JSON.stringify({ ...sameState, transcription_status: "unexpected" }), { status: 200 });
  }) as typeof fetch;
  const mismatchedIdRequest = (async (input: RequestInfo | URL) => {
    if (String(input) === "/api/auth/csrf") {
      return new Response(JSON.stringify({ csrf_token: "short-lived-token" }), { status: 200 });
    }
    return new Response(JSON.stringify({ ...sameState, id: 999 }), { status: 200 });
  }) as typeof fetch;

  const response = await performCurationMutation(42, "inbox", request);
  assert.deepEqual(response, sameState);
  assert.deepEqual(reconcileLifecycleProjection(lifecycle, response), sameState);
  assert.equal(await performCurationMutation(42, "organized", failedPatchRequest), null);
  assert.equal(await performCurationMutation(42, "organized", malformedResponseRequest), null);
  assert.equal(await performCurationMutation(42, "organized", mismatchedIdRequest), null);
  assert.deepEqual(reconcileLifecycleProjection(lifecycle, null), lifecycle);
});

test("curation control has bounded loading, error feedback, and refresh-safe lifecycle state", async () => {
  const source = await readFile(new URL("../src/components/reel-lifecycle.tsx", import.meta.url), "utf8");
  const librarySource = await readFile(new URL("../src/app/library/library-page-content.tsx", import.meta.url), "utf8");
  const detailSource = await readFile(new URL("../src/app/reels/[reelId]/reel-detail-page-content.tsx", import.meta.url), "utf8");

  assert.match(source, /Atualizando…/);
  assert.match(source, /disabled=\{pending\}/);
  assert.match(source, /role="alert"/);
  assert.match(source, /aria-live="polite"/);
  assert.match(source, /setLifecycle\(confirmed\)/);
  assert.doesNotMatch(source, /useEffect/);
  assert.match(librarySource, /key=\{lifecycleKey\(item\)\}/);
  assert.match(detailSource, /key=\{lifecycleKey\(reel\)\}/);
  assert.doesNotMatch(source, /categor(?:y|ias)/i);
  assert.doesNotMatch(source, /telegram|source/i);
});

test("browser lifecycle authority remains restricted to curation", async () => {
  const mutationSource = await readFile(new URL("../src/lib/reel-curation-api.ts", import.meta.url), "utf8");
  const lifecycleSource = await readFile(new URL("../src/components/reel-lifecycle.tsx", import.meta.url), "utf8");
  const libraryApiSource = await readFile(new URL("../src/app/library/library-api.ts", import.meta.url), "utf8");
  const detailApiSource = await readFile(new URL("../src/app/reels/[reelId]/reel-detail-api.ts", import.meta.url), "utf8");

  assert.match(mutationSource, /\{ curation_status \}/);
  assert.doesNotMatch(mutationSource, /\{[^}]*download_status[^}]*\}/s);
  assert.doesNotMatch(mutationSource, /\{[^}]*transcription_status[^}]*\}/s);
  assert.doesNotMatch(mutationSource, /transcription_attempt_id/);
  assert.doesNotMatch(lifecycleSource, /download_status.*(?:PATCH|POST|PUT)|transcription_status.*(?:PATCH|POST|PUT)/s);
  assert.match(libraryApiSource, /download_status/);
  assert.match(libraryApiSource, /curation_status/);
  assert.match(libraryApiSource, /transcription_status/);
  assert.match(detailApiSource, /download_status/);
  assert.match(detailApiSource, /curation_status/);
  assert.match(detailApiSource, /transcription_status/);
  assert.doesNotMatch(libraryApiSource, /\bstatus\s*:/);
  assert.doesNotMatch(detailApiSource, /\bstatus\s*:/);
});
