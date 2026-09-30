import type { Metadata } from "next";

import { AppShell } from "../../components/app-shell";
import { OpenPaperclipButton } from "../../components/open-paperclip-button";
import { requireOwnerSession } from "../../lib/auth/session";

export const metadata: Metadata = {
  title: "Desenvolvimento | MegaBrain",
  description: "Acesso ao ambiente de desenvolvimento do MegaBrain.",
};

export default async function DevelopmentPage() {
  const owner = await requireOwnerSession();

  return (
    <AppShell owner={owner} pathname="/development">
      <section aria-labelledby="development-title" className="max-w-2xl rounded-2xl border border-border bg-surface px-6 py-10 shadow-[0_12px_30px_rgba(32,37,34,0.06)] sm:px-8 sm:py-12">
        <h1 className="text-4xl font-semibold tracking-tight text-foreground text-balance" id="development-title">Desenvolvimento</h1>
        <p className="mt-5 max-w-xl text-base leading-7 text-muted sm:text-lg">Abra o Paperclip para acompanhar o desenvolvimento do MegaBrain.</p>
        <div className="mt-8 border-t border-border pt-6">
          <OpenPaperclipButton />
        </div>
      </section>
    </AppShell>
  );
}
