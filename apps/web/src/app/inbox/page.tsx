import type { Metadata } from "next";

import { AppShell } from "../../components/app-shell";
import { requireOwnerSession } from "../../lib/auth/session";

export const metadata: Metadata = {
  title: "Inbox | MegaBrain",
  description: "O espaço de triagem de conteúdos capturados no MegaBrain.",
};

export default async function InboxPage() {
  const owner = await requireOwnerSession();

  return (
    <AppShell owner={owner} pathname="/inbox">
      <section aria-labelledby="inbox-title" className="max-w-2xl rounded-2xl border border-border bg-surface px-6 py-10 shadow-[0_12px_30px_rgba(32,37,34,0.06)] sm:px-8 sm:py-12">
        <h1 className="text-4xl font-semibold tracking-tight text-foreground text-balance" id="inbox-title">Inbox</h1>
        <p className="mt-5 max-w-xl text-base leading-7 text-muted sm:text-lg">
          Conteúdos que precisam da sua atenção aparecerão aqui.
        </p>
        <p className="mt-8 border-t border-border pt-5 text-sm leading-6 text-muted">
          A triagem de conteúdos recém-adicionados, em processamento e para organizar será introduzida com o modelo de ciclo de vida.
        </p>
      </section>
    </AppShell>
  );
}
