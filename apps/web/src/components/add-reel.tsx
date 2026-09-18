"use client";

import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";

import {
  performReelCreation,
  type ReelCreationErrorCode,
  type ReelCreationSuccess,
} from "../lib/reel-creation-api";

const errorMessages: Record<ReelCreationErrorCode, string> = {
  invalid_request: "Informe um link público válido de um Reel do Instagram.",
  identity_conflict: "O Reel entrou em conflito com um registro existente. Revise o link antes de tentar novamente.",
  registration_unavailable: "Não foi possível salvar o Reel agora. Tente novamente em alguns instantes.",
  dispatch_unavailable: "O Reel não pôde ser encaminhado para processamento agora. Tente novamente em alguns instantes.",
  session_unavailable: "Sua sessão não está disponível. Atualize a página e entre novamente se necessário.",
  csrf_unavailable: "Não foi possível validar esta ação com segurança. Atualize a página e tente novamente.",
  network_error: "Não foi possível falar com o MegaBrain agora. Verifique sua conexão e tente novamente.",
  invalid_response: "O MegaBrain retornou uma resposta inesperada. Tente novamente em alguns instantes.",
};

function successMessage(result: ReelCreationSuccess): string {
  if (result.reel.created) {
    if (result.dispatch.state === "accepted") {
      return "Reel adicionado. O processamento foi iniciado.";
    }
    return "Reel salvo. Ainda não foi possível confirmar o início do processamento.";
  }

  if (result.dispatch.state === "accepted") {
    return "Este Reel já existia e o processamento foi solicitado novamente.";
  }
  if (result.dispatch.state === "unconfirmed") {
    return "Este Reel já existe. Ainda não foi possível confirmar o processamento.";
  }
  return "Este Reel já existe no MegaBrain.";
}

export function AddReel() {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const [url, setUrl] = useState("");
  const [pending, setPending] = useState(false);
  const [success, setSuccess] = useState<ReelCreationSuccess | null>(null);
  const [error, setError] = useState<ReelCreationErrorCode | null>(null);

  useEffect(() => {
    if (error && !pending) {
      inputRef.current?.focus();
    }
  }, [error, pending]);

  function resetState() {
    if (pending) return;
    setUrl("");
    setSuccess(null);
    setError(null);
  }

  function openDialog() {
    resetState();
    dialogRef.current?.showModal();
  }

  function closeDialog() {
    if (pending) return;
    dialogRef.current?.close();
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;

    setPending(true);
    setSuccess(null);
    setError(null);

    try {
      const result = await performReelCreation(url);
      if (!result.ok) {
        setError(result.code);
        return;
      }
      setSuccess(result);
    } catch {
      setError("invalid_response");
    } finally {
      setPending(false);
    }
  }

  return (
    <>
      <button
        className="min-h-11 rounded-lg border border-border bg-surface px-4 py-2 text-sm font-semibold text-primary hover:bg-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
        onClick={openDialog}
        type="button"
      >
        + Adicionar Reel
      </button>

      <dialog
        aria-labelledby="add-reel-title"
        className="m-auto max-h-[calc(100dvh-2rem)] w-[min(34rem,calc(100%-2rem))] overflow-y-auto overscroll-contain rounded-2xl border border-border bg-surface p-0 text-foreground shadow-2xl backdrop:bg-black/30"
        onCancel={(event) => {
          if (pending) event.preventDefault();
        }}
        onClose={resetState}
        ref={dialogRef}
      >
        <div className="p-6 sm:p-7">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="text-2xl font-semibold tracking-tight" id="add-reel-title">Adicionar Reel</h2>
              <p className="mt-2 text-sm leading-6 text-muted" id="add-reel-help">
                Cole o link público de um Reel do Instagram.
              </p>
            </div>
            <button
              aria-label="Fechar"
              className="min-h-11 rounded-lg px-3 text-sm font-semibold text-muted hover:bg-accent hover:text-foreground disabled:cursor-not-allowed disabled:opacity-60"
              disabled={pending}
              onClick={closeDialog}
              type="button"
            >
              Fechar
            </button>
          </div>

          {success ? (
            <section aria-live="polite" className="mt-6 rounded-xl border border-border bg-accent p-4" role="status">
              <p className="font-semibold text-success">{successMessage(success)}</p>
              <p className="mt-2 text-sm leading-6 text-muted">
                O ciclo de vida continuará sendo atualizado pelo pipeline do MegaBrain.
              </p>
              <div className="mt-5 flex flex-wrap gap-3">
                <a
                  className="inline-flex min-h-11 items-center rounded-xl bg-primary px-4 py-2 text-sm font-semibold text-white hover:bg-[#1f452f]"
                  href={`/reels/${success.reel.id}`}
                >
                  Abrir Reel
                </a>
                <button
                  className="min-h-11 rounded-xl border border-border px-4 py-2 text-sm font-semibold text-primary hover:bg-surface"
                  onClick={closeDialog}
                  type="button"
                >
                  Fechar
                </button>
              </div>
            </section>
          ) : (
            <form aria-busy={pending} className="mt-6" onSubmit={(event) => void submit(event)}>
              <label className="block text-sm font-semibold" htmlFor="add-reel-url">URL do Reel</label>
              <input
                aria-describedby={error ? "add-reel-help add-reel-url-error" : "add-reel-help"}
                aria-invalid={error ? true : undefined}
                autoComplete="off"
                className="mt-2 min-h-12 w-full rounded-xl border border-border bg-surface px-4 text-base placeholder:text-muted disabled:cursor-not-allowed disabled:opacity-60"
                disabled={pending}
                id="add-reel-url"
                name="url"
                onChange={(event) => setUrl(event.target.value)}
                placeholder="https://www.instagram.com/reel/..."
                ref={inputRef}
                required
                type="url"
                value={url}
              />

              {pending ? (
                <p aria-live="polite" className="mt-3 text-sm font-medium text-muted" role="status">
                  Adicionando Reel…
                </p>
              ) : null}

              {error ? (
                <p className="mt-3 text-sm font-semibold text-danger" id="add-reel-url-error" role="alert">
                  {errorMessages[error]}
                </p>
              ) : null}

              <div className="mt-6 flex flex-wrap justify-end gap-3">
                <button
                  className="min-h-11 rounded-xl border border-border px-4 py-2 text-sm font-semibold text-primary hover:bg-accent disabled:cursor-not-allowed disabled:opacity-60"
                  disabled={pending}
                  onClick={closeDialog}
                  type="button"
                >
                  Cancelar
                </button>
                <button
                  className="min-h-11 rounded-xl bg-primary px-4 py-2 text-sm font-semibold text-white hover:bg-[#1f452f] disabled:cursor-not-allowed disabled:opacity-60"
                  disabled={pending}
                  type="submit"
                >
                  {pending ? "Adicionando…" : "Adicionar"}
                </button>
              </div>
            </form>
          )}
        </div>
      </dialog>
    </>
  );
}
