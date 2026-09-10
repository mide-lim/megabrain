import type { Metadata } from "next";

import { AppShell } from "../../components/app-shell";
import { requireOwnerSession } from "../../lib/auth/session";

export const metadata: Metadata = {
  title: "Categorias | MegaBrain",
  description: "A futura área de organização por categorias do MegaBrain.",
};

export default async function CategoriesPage() {
  const owner = await requireOwnerSession();

  return (
    <AppShell owner={owner} pathname="/categories">
      <section aria-labelledby="categories-title" className="max-w-2xl rounded-2xl border border-border bg-surface px-6 py-10 shadow-[0_12px_30px_rgba(32,37,34,0.06)] sm:px-8 sm:py-12">
        <h1 className="text-4xl font-semibold tracking-tight text-foreground text-balance" id="categories-title">Categorias</h1>
        <p className="mt-5 max-w-xl text-base leading-7 text-muted sm:text-lg">
          A gestão de categorias será incorporada aqui quando a organização da Biblioteca migrar para esta experiência.
        </p>
        <p className="mt-8 border-t border-border pt-5 text-sm leading-6 text-muted">
          Até lá, as categorias existentes continuam disponíveis no detalhe de cada Reel.
        </p>
      </section>
    </AppShell>
  );
}
