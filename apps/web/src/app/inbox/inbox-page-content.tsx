import Link from "next/link";

import { ReelCard } from "../library/library-page-content";
import type { LibraryResponse } from "../library/library-api";
import { buildInboxUrl } from "./inbox-api";

function UnavailableState() {
  return (
    <section aria-live="polite" className="rounded-2xl border border-border bg-surface px-6 py-10 sm:px-8" role="status">
      <h2 className="text-xl font-semibold tracking-tight text-foreground">Inbox temporariamente indisponível</h2>
      <p className="mt-3 max-w-xl text-sm leading-6 text-muted">Não foi possível carregar os conteúdos para triagem agora. Tente novamente em alguns instantes.</p>
    </section>
  );
}

export function InboxPageContent({ inbox }: { inbox: LibraryResponse | null }) {
  return (
    <div id="inbox-content">
      <section aria-labelledby="inbox-title" className="max-w-3xl">
        <h1 className="text-4xl font-semibold tracking-tight text-foreground text-balance sm:text-5xl" id="inbox-title">Inbox</h1>
        <p className="mt-4 max-w-2xl text-base leading-7 text-muted sm:text-lg">
          Reels capturados que ainda precisam da sua triagem e organização.
        </p>
      </section>

      {!inbox ? <div className="mt-10"><UnavailableState /></div> : <InboxResults inbox={inbox} />}
    </div>
  );
}

function InboxResults({ inbox }: { inbox: LibraryResponse }) {
  const { items, pagination } = inbox;

  if (items.length === 0) {
    return (
      <section className="mt-10 rounded-2xl border border-border bg-surface px-6 py-10 sm:px-8">
        <h2 className="text-xl font-semibold tracking-tight text-foreground">Inbox em dia</h2>
        <p className="mt-3 max-w-xl text-sm leading-6 text-muted">Não há Reels aguardando organização.</p>
      </section>
    );
  }

  const previousHref = buildInboxUrl(pagination.page - 1);
  const nextHref = buildInboxUrl(pagination.page + 1);

  return (
    <section aria-label="Reels aguardando organização" className="mt-10">
      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2 border-b border-border pb-4">
        <p className="text-sm font-medium text-muted">Página {pagination.page}</p>
        <p className="text-sm text-muted">{items.length} {items.length === 1 ? "Reel" : "Reels"} para organizar</p>
      </div>

      <div className="mt-6 grid gap-4 md:grid-cols-2 lg:grid-cols-3 lg:gap-5">
        {items.map((item) => (
          <ReelCard item={item} key={item.id} reloadAfterCurationChange />
        ))}
      </div>

      <nav aria-label="Páginas do Inbox" className="mt-8 flex items-center gap-3">
        {pagination.has_previous ? (
          <Link className="inline-flex min-h-11 items-center rounded-xl border border-border px-4 py-3 text-sm font-semibold text-primary hover:bg-accent" href={previousHref}>Anterior</Link>
        ) : null}
        <span aria-current="page" className="min-h-11 rounded-xl bg-accent px-4 py-3 text-sm font-semibold text-primary">Página {pagination.page}</span>
        {pagination.has_next ? (
          <Link className="inline-flex min-h-11 items-center rounded-xl border border-border px-4 py-3 text-sm font-semibold text-primary hover:bg-accent" href={nextHref}>Próxima</Link>
        ) : null}
      </nav>
    </section>
  );
}
