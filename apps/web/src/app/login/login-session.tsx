"use client";

import { useEffect, useState } from "react";

export const GOOGLE_LOGIN_TARGET = "/auth/login?return_to=/login";

type SessionUser = {
  id: string | number;
  email: string;
};

export type LoginSessionState =
  | { kind: "loading" }
  | { kind: "unauthenticated" }
  | { kind: "authenticated"; user: SessionUser }
  | { kind: "error" };

function isAuthenticatedSession(value: unknown): value is { authenticated: true; user: SessionUser } {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const session = value as Record<string, unknown>;
  if (session.authenticated !== true || typeof session.user !== "object" || session.user === null) {
    return false;
  }

  const user = session.user as Record<string, unknown>;
  return (
    (typeof user.id === "string" || typeof user.id === "number") &&
    typeof user.email === "string" &&
    user.email.length > 0
  );
}

export async function getSessionState(
  request: typeof fetch = fetch,
): Promise<LoginSessionState> {
  try {
    const response = await request("/api/auth/session", {
      cache: "no-store",
      credentials: "same-origin",
      headers: { accept: "application/json" },
      method: "GET",
    });

    if (response.status === 401) {
      return { kind: "unauthenticated" };
    }

    if (!response.ok) {
      return { kind: "error" };
    }

    const payload: unknown = await response.json();
    if (!isAuthenticatedSession(payload)) {
      return { kind: "error" };
    }

    return { kind: "authenticated", user: payload.user };
  } catch {
    return { kind: "error" };
  }
}

function GoogleMark() {
  return (
    <svg aria-hidden="true" className="h-5 w-5 shrink-0" viewBox="0 0 24 24">
      <path
        d="M21.8 12.2c0-.7-.1-1.4-.2-2H12v3.8h5.5a4.7 4.7 0 0 1-2 3.1v2.5h3.2c1.9-1.8 3.1-4.3 3.1-7.4Z"
        fill="#4285F4"
      />
      <path
        d="M12 22c2.7 0 5-.9 6.7-2.4l-3.2-2.5c-.9.6-2 .9-3.5.9-2.7 0-5-1.8-5.8-4.3H2.9v2.6A10 10 0 0 0 12 22Z"
        fill="#34A853"
      />
      <path
        d="M6.2 13.7A6 6 0 0 1 5.9 12c0-.6.1-1.2.3-1.7V7.7H2.9A10 10 0 0 0 2 12c0 1.6.4 3.1.9 4.3l3.3-2.6Z"
        fill="#FBBC05"
      />
      <path
        d="M12 5.9c1.5 0 2.9.5 3.9 1.5l2.9-2.9C17 2.9 14.7 2 12 2a10 10 0 0 0-9.1 5.7l3.3 2.6C7 7.7 9.3 5.9 12 5.9Z"
        fill="#EA4335"
      />
    </svg>
  );
}

function GoogleLoginLink() {
  return (
    <a
      className="inline-flex min-h-11 w-full items-center justify-center gap-3 rounded-xl bg-primary px-5 py-3 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-[#1f452f] focus-visible:outline-none"
      href={GOOGLE_LOGIN_TARGET}
    >
      <GoogleMark />
      Entrar com Google
    </a>
  );
}

function LibraryLink({ label = "Voltar para a Biblioteca de Reels" }: { label?: string }) {
  return (
    // The public library is served by FastAPI via Caddy, not the Next.js router.
    // eslint-disable-next-line @next/next/no-html-link-for-pages
    <a
      className="inline-flex min-h-11 items-center justify-center rounded-xl px-4 py-3 text-sm font-semibold text-primary underline decoration-primary/30 underline-offset-4 transition-colors hover:text-foreground hover:decoration-primary focus-visible:outline-none"
      href="/"
    >
      {label}
    </a>
  );
}

export function LoginSessionContent({ state }: { state: LoginSessionState }) {
  if (state.kind === "loading") {
    return (
      <div
        aria-live="polite"
        className="flex min-h-[19rem] flex-col justify-center border-l-2 border-accent pl-5"
        role="status"
      >
        <p className="text-sm font-medium text-muted">Verificando sua sessão…</p>
        <p className="mt-2 max-w-sm text-sm leading-6 text-muted">
          Conferindo o acesso ao seu espaço MegaBrain.
        </p>
      </div>
    );
  }

  if (state.kind === "authenticated") {
    return (
      <div aria-live="polite" className="flex min-h-[19rem] flex-col justify-center">
        <p className="inline-flex w-fit items-center gap-2 rounded-full bg-accent px-3 py-1 text-sm font-semibold text-success">
          <span aria-hidden="true" className="h-2 w-2 rounded-full bg-success" />
          Sessão ativa
        </p>
        <h2 className="mt-6 text-3xl font-semibold tracking-tight text-foreground">
          Você já está no MegaBrain.
        </h2>
        <p className="mt-4 max-w-md text-base leading-7 text-muted">
          A sessão do proprietário está ativa para esta conta.
        </p>
        <p className="mt-5 break-words rounded-xl border border-border bg-background px-4 py-3 text-sm font-medium text-foreground">
          {state.user.email}
        </p>
        <div className="mt-8">
          <LibraryLink label="Abrir a Biblioteca de Reels" />
        </div>
      </div>
    );
  }

  const isError = state.kind === "error";

  return (
    <div className="flex min-h-[19rem] flex-col justify-center">
      <p className="text-sm font-semibold text-primary">Acesso do proprietário</p>
      <h2 className="mt-4 text-3xl font-semibold tracking-tight text-foreground">
        Entre no seu espaço.
      </h2>
      <p className="mt-4 max-w-md text-base leading-7 text-muted">
        Use a conta Google autorizada para acessar o seu ambiente pessoal de conhecimento e IA.
      </p>
      {isError ? (
        <p aria-live="polite" className="mt-4 text-sm leading-6 text-danger" role="status">
          Não foi possível confirmar sua sessão agora. Você pode entrar novamente com Google.
        </p>
      ) : null}
      <div className="mt-8 space-y-3">
        <GoogleLoginLink />
        <LibraryLink />
      </div>
    </div>
  );
}

export default function LoginSession() {
  const [state, setState] = useState<LoginSessionState>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;

    void getSessionState().then((nextState) => {
      if (!cancelled) {
        setState(nextState);
      }
    });

    return () => {
      cancelled = true;
    };
  }, []);

  return <LoginSessionContent state={state} />;
}
