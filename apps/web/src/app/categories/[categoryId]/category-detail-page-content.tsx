import Link from "next/link";
import type { ReactNode } from "react";

import { ReelCard } from "../../library/library-page-content";
import { buildCategoryUrl, type CategoryDetailFetchResult } from "../categories-api";

export function CategoryDetailPageContent({
  result,
  actions,
}: {
  result: CategoryDetailFetchResult;
  actions?: ReactNode;
}) {
  if (result.kind === "not-found") {
    return (
      <section className="rounded-2xl border border-border bg-surface px-6 py-10 sm:px-8">
        <h1 className="text-3xl font-semibold tracking-tight text-foreground">Categoria não encontrada</h1>
        <p className="mt-3 text-sm leading-6 text-muted">Esta categoria não existe ou foi removida.</p>
        <Link className="mt-6 inline-flex min-h-11 items-center text-sm font-semibold text-primary underline decoration-primary/25 underline-offset-4 hover:decoration-primary" href="/categories">Voltar para Categorias</Link>
      </section>
    );
  }

  if (result.kind === "unavailable") {
    return (
      <section aria-live="polite" className="rounded-2xl border border-border bg-surface px-6 py-10 sm:px-8" role="status">
        <h1 className="text-3xl font-semibold tracking-tight text-foreground">Categoria temporariamente indisponível</h1>
        <p className="mt-3 text-sm leading-6 text-muted">Não foi possível carregar esta categoria agora. Tente novamente em alguns instantes.</p>
        <Link className="mt-6 inline-flex min-h-11 items-center text-sm font-semibold text-primary underline decoration-primary/25 underline-offset-4 hover:decoration-primary" href="/categories">Voltar para Categorias</Link>
      </section>
    );
  }

  const { category, items, pagination } = result.data;
  const previousHref = buildCategoryUrl(category.id, pagination.page - 1);
  const nextHref = buildCategoryUrl(category.id, pagination.page + 1);

  return (
    <div id="category-detail-content">
      <section className="max-w-3xl">
        <Link className="text-sm font-semibold text-primary underline decoration-primary/25 underline-offset-4 hover:decoration-primary" href="/categories">Categorias</Link>
        <h1 className="mt-4 break-words text-4xl font-semibold tracking-tight text-foreground text-balance sm:text-5xl">{category.name}</h1>
        <p className="mt-4 text-base leading-7 text-muted">{category.reel_count} {category.reel_count === 1 ? "item" : "itens"}</p>
      </section>

      {actions}

      {items.length === 0 ? (
        <section className="mt-10 rounded-2xl border border-border bg-surface px-6 py-10 sm:px-8">
          <h2 className="text-xl font-semibold tracking-tight text-foreground">Esta categoria ainda não possui Reels</h2>
          <p className="mt-3 max-w-xl text-sm leading-6 text-muted">Adicione esta categoria pelo detalhe de um Reel para vê-lo aqui.</p>
        </section>
      ) : (
        <section aria-label="Reels da categoria" className="mt-10">
          <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2 border-b border-border pb-4">
            <h2 className="text-lg font-semibold text-foreground">Reels</h2>
            <p className="text-sm text-muted">Página {pagination.page}</p>
          </div>
          <div className="mt-6 grid gap-4 md:grid-cols-2 lg:grid-cols-3 lg:gap-5">
            {items.map((item) => <ReelCard item={item} key={item.id} />)}
          </div>
          <nav aria-label="Páginas da categoria" className="mt-8 flex items-center gap-3">
            {pagination.has_previous ? <a className="inline-flex min-h-11 items-center rounded-xl border border-border px-4 py-3 text-sm font-semibold text-primary hover:bg-accent" href={previousHref}>Anterior</a> : null}
            <span aria-current="page" className="min-h-11 rounded-xl bg-accent px-4 py-3 text-sm font-semibold text-primary">Página {pagination.page}</span>
            {pagination.has_next ? <a className="inline-flex min-h-11 items-center rounded-xl border border-border px-4 py-3 text-sm font-semibold text-primary hover:bg-accent" href={nextHref}>Próxima</a> : null}
          </nav>
        </section>
      )}
    </div>
  );
}
