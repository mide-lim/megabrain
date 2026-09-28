import type { LibraryResponse } from "../library/library-api";
import { ReelCard } from "../library/library-page-content";

export function buildInboxUrl(page: number): string {
  return page > 1 ? "/inbox?page=" + page : "/inbox";
}

export function InboxPageContent({ inbox }: { inbox: LibraryResponse | null }) {
  return (
    <div id="inbox-content">
      <section aria-labelledby="inbox-title" className="max-w-3xl">
        <h1 className="text-4xl font-semibold tracking-tight text-foreground text-balance sm:text-5xl" id="inbox-title">Inbox</h1>
        <p className="mt-4 max-w-2xl text-base leading-7 text-muted sm:text-lg">Conteúdos que ainda precisam ser organizados.</p>
      </section>

      {!inbox ? (
        <section aria-live="polite" className="mt-10 rounded-2xl border border-border bg-surface px-6 py-10 sm:px-8" role="status">
          <h2 className="text-xl font-semibold tracking-tight text-foreground">Inbox temporariamente indisponível</h2>
          <p className="mt-3 max-w-xl text-sm leading-6 text-muted">Não foi possível carregar os Reels agora. Tente novamente em alguns instantes.</p>
        </section>
      ) : inbox.items.length === 0 ? (
        <section className="mt-10 rounded-2xl border border-border bg-surface px-6 py-10 sm:px-8">
          <h2 className="text-xl font-semibold tracking-tight text-foreground">
            {inbox.pagination.has_previous ? "Nenhum Reel nesta página" : "Inbox vazia"}
          </h2>
          <p className="mt-3 max-w-xl text-sm leading-6 text-muted">
            {inbox.pagination.has_previous
              ? "Os Reels desta página já foram organizados."
              : "Você não tem Reels aguardando organização."}
          </p>
          {inbox.pagination.has_previous ? (
            <a className="mt-5 inline-flex min-h-11 items-center rounded-xl border border-border px-4 py-3 text-sm font-semibold text-primary hover:bg-accent" href={buildInboxUrl(inbox.pagination.page - 1)}>
              Voltar para a página anterior
            </a>
          ) : null}
        </section>
      ) : (
        <section aria-label="Reels aguardando organização" className="mt-10">
          <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2 border-b border-border pb-4">
            <p className="text-sm font-medium text-muted">Página {inbox.pagination.page}</p>
            <p className="text-sm text-muted">{inbox.items.length} {inbox.items.length === 1 ? "Reel" : "Reels"} nesta página</p>
          </div>
          <div className="mt-6 grid gap-4 md:grid-cols-2 lg:grid-cols-3 lg:gap-5">
            {inbox.items.map((item) => (
              <ReelCard item={item} key={item.id} refreshOnCuration />
            ))}
          </div>
          <nav aria-label="Páginas da Inbox" className="mt-8 flex items-center gap-3">
            {inbox.pagination.has_previous ? (
              <a className="inline-flex min-h-11 items-center rounded-xl border border-border px-4 py-3 text-sm font-semibold text-primary hover:bg-accent" href={buildInboxUrl(inbox.pagination.page - 1)}>Anterior</a>
            ) : null}
            <span aria-current="page" className="min-h-11 rounded-xl bg-accent px-4 py-3 text-sm font-semibold text-primary">Página {inbox.pagination.page}</span>
            {inbox.pagination.has_next ? (
              <a className="inline-flex min-h-11 items-center rounded-xl border border-border px-4 py-3 text-sm font-semibold text-primary hover:bg-accent" href={buildInboxUrl(inbox.pagination.page + 1)}>Próxima</a>
            ) : null}
          </nav>
        </section>
      )}
    </div>
  );
}
