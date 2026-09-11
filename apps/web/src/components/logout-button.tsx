"use client";

import { useState } from "react";

function isCsrfPayload(value: unknown): value is { csrf_token: string } {
  return typeof value === "object" && value !== null && typeof (value as { csrf_token?: unknown }).csrf_token === "string";
}

export function LogoutButton() {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function logout() {
    if (pending) return;

    setPending(true);
    setError(null);

    try {
      const csrfResponse = await fetch("/api/auth/csrf", {
        cache: "no-store",
        credentials: "same-origin",
      });
      const csrfPayload: unknown = await csrfResponse.json().catch(() => null);
      if (!csrfResponse.ok || !isCsrfPayload(csrfPayload)) {
        throw new Error("CSRF bootstrap failed");
      }

      const form = document.createElement("form");
      form.action = "/auth/logout";
      form.method = "POST";

      const csrfInput = document.createElement("input");
      csrfInput.name = "csrf_token";
      csrfInput.type = "hidden";
      csrfInput.value = csrfPayload.csrf_token;
      form.append(csrfInput);

      document.body.append(form);
      form.submit();
    } catch {
      setPending(false);
      setError("Não foi possível encerrar a sessão. Tente novamente.");
    }
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <button
        aria-busy={pending}
        className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border border-border bg-surface px-4 py-2 text-sm font-semibold text-primary hover:bg-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:cursor-not-allowed disabled:opacity-60"
        disabled={pending}
        onClick={() => void logout()}
        type="button"
      >
        {pending ? <span aria-hidden="true" className="h-3 w-3 animate-spin rounded-full border-2 border-primary border-t-transparent" /> : null}
        Sair
      </button>
      {error ? <p className="max-w-52 text-right text-xs font-medium text-danger" role="alert">{error}</p> : null}
    </div>
  );
}
