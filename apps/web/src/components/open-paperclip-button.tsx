"use client";

import { useState } from "react";

import { fetchCsrfToken } from "../lib/csrf-client";

export function OpenPaperclipButton() {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function openPaperclip() {
    if (pending) return;

    setPending(true);
    setError(null);

    const csrfToken = await fetchCsrfToken();
    if (csrfToken === null) {
      setPending(false);
      setError("Não foi possível validar o acesso ao Paperclip. Atualize a página e tente novamente.");
      return;
    }

    const form = document.createElement("form");
    form.action = "/api/platform/paperclip/launch";
    form.method = "POST";

    const csrfInput = document.createElement("input");
    csrfInput.name = "csrf_token";
    csrfInput.type = "hidden";
    csrfInput.value = csrfToken;
    form.append(csrfInput);

    document.body.append(form);
    form.submit();
  }

  return (
    <div className="flex flex-col items-start gap-3">
      <button
        aria-busy={pending}
        className="inline-flex min-h-12 items-center justify-center gap-2 rounded-xl bg-primary px-5 py-3 text-sm font-semibold text-white hover:bg-[#1f452f] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:cursor-not-allowed disabled:opacity-60"
        disabled={pending}
        onClick={() => void openPaperclip()}
        type="button"
      >
        {pending ? <span aria-hidden="true" className="h-3 w-3 animate-spin rounded-full border-2 border-white border-t-transparent" /> : null}
        Abrir Paperclip
      </button>
      {error ? <p className="max-w-xl text-sm font-medium text-danger" role="alert">{error}</p> : null}
    </div>
  );
}
