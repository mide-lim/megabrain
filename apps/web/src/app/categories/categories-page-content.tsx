import type { ReactNode } from "react";

import type { CategoriesResponse } from "./categories-api";

function countLabel(count: number): string {
  return count === 1 ? "1 item" : count + " itens";
}

export function CategoriesPageContent({
  categories,
  createControl,
}: {
  categories: CategoriesResponse | null;
  createControl?: ReactNode;
}) {
  return (
    <div id="categories-content">
      <section aria-labelledby="categories-title" className="max-w-3xl">
        <h1 className="text-4xl font-semibold tracking-tight text-foreground text-balance sm:text-5xl" id="categories-title">Categorias</h1>
        <p className="mt-4 max-w-2xl text-base leading-7 text-muted sm:text-lg">Organize e navegue pelo seu conhecimento.</p>
      </section>

      {createControl}

      {!categories ? (
        <section aria-live="polite" className="mt-10 rounded-2xl border border-border bg-surface px-6 py-10 sm:px-8" role="status">
          <h2 className="text-xl font-semibold tracking-tight text-foreground">Categorias temporariamente indisponíveis</h2>
          <p className="mt-3 max-w-xl text-sm leading-6 text-muted">Não foi possível carregar as categorias agora. Tente novamente em alguns instantes.</p>
        </section>
      ) : categories.items.length === 0 ? (
        <section className="mt-10 rounded-2xl border border-border bg-surface px-6 py-10 sm:px-8">
          <h2 className="text-xl font-semibold tracking-tight text-foreground">Você ainda não criou nenhuma categoria</h2>
          <p className="mt-3 max-w-xl text-sm leading-6 text-muted">Crie uma categoria para começar a organizar sua biblioteca.</p>
        </section>
      ) : (
        <section aria-label="Todas as categorias" className="mt-10">
          <div className="flex items-baseline justify-between gap-4 border-b border-border pb-4">
            <h2 className="text-lg font-semibold text-foreground">Todas as categorias</h2>
            <p className="text-sm text-muted">{categories.items.length} {categories.items.length === 1 ? "categoria" : "categorias"}</p>
          </div>
          <div className="mt-6 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {categories.items.map((category) => (
              <a className="rounded-2xl border border-border bg-surface p-5 shadow-[0_12px_30px_rgba(32,37,34,0.06)] transition-colors hover:bg-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary sm:p-6" href={"/categories/" + category.id} key={category.id}>
                <h3 className="break-words text-xl font-semibold tracking-tight text-foreground">{category.name}</h3>
                <p className="mt-3 text-sm font-medium text-muted">{countLabel(category.reel_count)}</p>
              </a>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
