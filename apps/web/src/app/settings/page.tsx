import type { Metadata } from "next";

import { AppShell } from "../../components/app-shell";
import { requireOwnerSession } from "../../lib/auth/session";

export const metadata: Metadata = {
  title: "Configurações | MegaBrain",
  description: "A área de configurações do MegaBrain.",
};

export default async function SettingsPage() {
  const owner = await requireOwnerSession();

  return (
    <AppShell owner={owner} pathname="/settings">
      <section aria-labelledby="settings-title" className="max-w-2xl rounded-2xl border border-border bg-surface px-6 py-10 shadow-[0_12px_30px_rgba(32,37,34,0.06)] sm:px-8 sm:py-12">
        <h1 className="text-4xl font-semibold tracking-tight text-foreground text-balance" id="settings-title">Configurações</h1>
        <p className="mt-5 text-base leading-7 text-muted sm:text-lg">Este espaço está preparado para as configurações do MegaBrain.</p>
        <dl className="mt-8 border-t border-border pt-5">
          <dt className="text-sm font-medium text-muted">Conta conectada</dt>
          <dd className="mt-1 break-words text-sm font-semibold text-foreground">{owner.email}</dd>
        </dl>
      </section>
    </AppShell>
  );
}
