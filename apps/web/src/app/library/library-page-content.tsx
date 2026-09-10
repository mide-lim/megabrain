import type { LibraryResponse, ReelLibraryItem } from "./library-api";
import { buildLibraryUrl } from "./library-api";

function displayDate(value: string | null): string | null {
  if (!value) {
    return null;
  }

  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) {
    return null;
  }

  return new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "medium",
    timeZone: "UTC",
  }).format(date);
}

function displayDuration(value: number | null): string | null {
  if (value === null || !Number.isFinite(value)) {
    return null;
  }

  return new Intl.NumberFormat("pt-BR", {
    maximumFractionDigits: 1,
  }).format(value) + " s";
}

function ReelCard({ item }: { item: ReelLibraryItem }) {
  const title = item.title?.trim() || "Reel sem título";
  const receivedAt = displayDate(item.received_at);
  const duration = displayDuration(item.duration_seconds);

  return (
    <article className="flex min-w-0 flex-col rounded-2xl border border-border bg-surface p-5 shadow-[0_12px_30px_rgba(32,37,34,0.06)] sm:p-6">
      <p className="min-w-0 break-words text-sm font-semibold text-primary">
        {item.creator?.trim() || "Criador não informado"}
      </p>
      <h2 className="mt-3 text-xl font-semibold tracking-tight text-foreground">
        {/* FastAPI/Jinja owns the existing Reel detail route. */}
        <a
          className="rounded-sm underline decoration-primary/25 decoration-2 underline-offset-4 hover:decoration-primary"
          href={`/reels/${item.id}`}
        >
          {title}
        </a>
      </h2>
      {item.caption?.trim() ? (
        <p className="mt-3 line-clamp-3 break-words text-sm leading-6 text-muted">
          {item.caption}
        </p>
      ) : (
        <p className="mt-3 text-sm leading-6 text-muted">Sem legenda disponível.</p>
      )}
      {item.categories.length > 0 ? (
        <ul aria-label="Categorias" className="mt-5 flex flex-wrap gap-2">
          {item.categories.map((category) => (
            <li
              className="max-w-full break-words rounded-full bg-accent px-3 py-1 text-xs font-semibold text-primary"
              key={category}
            >
              {category}
            </li>
          ))}
        </ul>
      ) : null}
      <div className="mt-5 flex flex-wrap gap-x-4 gap-y-2 border-t border-border pt-4 text-sm text-muted">
        {receivedAt ? <span>Recebido em {receivedAt}</span> : null}
        {duration ? <span>{duration}</span> : null}
        {item.has_transcript ? <span className="font-medium text-primary">Transcrição disponível</span> : null}
      </div>
    </article>
  );
}

function UnavailableState() {
  return (
    <section aria-live="polite" className="rounded-2xl border border-border bg-surface px-6 py-10 sm:px-8" role="status">
      <h2 className="text-xl font-semibold tracking-tight text-foreground">Biblioteca temporariamente indisponível</h2>
      <p className="mt-3 max-w-xl text-sm leading-6 text-muted">
        Não foi possível carregar os Reels agora. Tente novamente em alguns instantes.
      </p>
    </section>
  );
}

export function LibraryPageContent({ library }: { library: LibraryResponse | null }) {
  const query = library?.query.q ?? "";

  return (
    <main className="min-h-screen bg-background px-4 py-4 sm:px-6 sm:py-6">
      <a
        className="sr-only rounded-md bg-surface px-3 py-2 text-sm font-semibold text-primary focus:not-sr-only focus:absolute focus:left-4 focus:top-4"
        href="#library-content"
      >
        Pular para o conteúdo
      </a>
      <div className="mx-auto max-w-7xl">
        <header className="flex items-center justify-between gap-4 px-2 py-4 sm:px-4">
          <a className="inline-flex items-center gap-3 rounded-lg text-sm font-semibold text-foreground" href="/library" translate="no">
            <span aria-hidden="true" className="grid h-8 w-8 place-items-center rounded-lg bg-primary text-sm font-bold text-white">M</span>
            <span>MegaBrain</span>
            <span className="font-normal text-muted">Biblioteca</span>
          </a>
          <a className="min-h-11 rounded-lg px-4 py-3 text-sm font-semibold text-primary underline decoration-primary/25 underline-offset-4 hover:text-foreground hover:decoration-primary" href="/login">
            Entrar
          </a>
        </header>

        <div className="mt-5 rounded-3xl border border-border bg-surface px-5 py-8 shadow-[0_24px_60px_rgba(32,37,34,0.08)] sm:px-8 sm:py-10 lg:px-10" id="library-content">
          <section aria-labelledby="library-title" className="max-w-3xl">
            <h1 className="text-4xl font-semibold tracking-tight text-foreground text-balance sm:text-5xl" id="library-title">Biblioteca de Reels</h1>
            <p className="mt-4 max-w-2xl text-base leading-7 text-muted sm:text-lg">
              Reencontre ideias capturadas por criador, legenda, transcrição ou categoria.
            </p>
          </section>

          <form action="/library" className="mt-8 max-w-3xl" method="get" role="search">
            <label className="block text-sm font-semibold text-foreground" htmlFor="library-search">
              Buscar por criador, legenda, transcrição ou categoria
            </label>
            <div className="mt-3 flex flex-col gap-3 sm:flex-row">
              <input
                className="min-h-12 min-w-0 flex-1 rounded-xl border border-border bg-background px-4 text-base text-foreground placeholder:text-muted"
                defaultValue={query}
                id="library-search"
                name="q"
                placeholder="Ex.: maker, ferramentas ou tecnologia"
                type="search"
              />
              <button className="min-h-12 rounded-xl bg-primary px-5 py-3 text-sm font-semibold text-white shadow-sm hover:bg-[#1f452f]" type="submit">
                Buscar
              </button>
              {query ? (
                <a className="inline-flex min-h-12 items-center justify-center rounded-xl px-4 py-3 text-sm font-semibold text-primary underline decoration-primary/25 underline-offset-4 hover:text-foreground hover:decoration-primary" href="/library">
                  Limpar busca
                </a>
              ) : null}
            </div>
          </form>

          {!library ? <div className="mt-10"><UnavailableState /></div> : null}
          {library ? <LibraryResults library={library} /> : null}
        </div>
      </div>
    </main>
  );
}

function LibraryResults({ library }: { library: LibraryResponse }) {
  const { items, pagination, query } = library;

  if (items.length === 0) {
    const noResults = Boolean(query.q);
    return (
      <section className="mt-10 rounded-2xl border border-border bg-background px-6 py-10 sm:px-8">
        <h2 className="text-xl font-semibold tracking-tight text-foreground">
          {noResults ? `Nenhum Reel encontrado para “${query.q}”` : "Sua biblioteca está vazia"}
        </h2>
        <p className="mt-3 max-w-xl text-sm leading-6 text-muted">
          {noResults ? "Tente outros termos ou limpe a busca para ver todos os Reels." : "Os Reels capturados aparecerão aqui."}
        </p>
      </section>
    );
  }

  const previousHref = buildLibraryUrl({ page: pagination.page - 1, q: query.q });
  const nextHref = buildLibraryUrl({ page: pagination.page + 1, q: query.q });

  return (
    <section aria-label="Reels" className="mt-10">
      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2 border-b border-border pb-4">
        <p className="text-sm font-medium text-muted">Página {pagination.page}</p>
        <p className="text-sm text-muted">{items.length} {items.length === 1 ? "Reel" : "Reels"} nesta página</p>
      </div>
      <div className="mt-6 grid gap-4 md:grid-cols-2 lg:grid-cols-3 lg:gap-5">
        {items.map((item) => <ReelCard item={item} key={item.id} />)}
      </div>
      <nav aria-label="Páginas da Biblioteca" className="mt-8 flex items-center gap-3">
        {pagination.has_previous ? (
          <a className="inline-flex min-h-11 items-center rounded-xl border border-border px-4 py-3 text-sm font-semibold text-primary hover:bg-accent" href={previousHref}>
            Anterior
          </a>
        ) : null}
        <span aria-current="page" className="min-h-11 rounded-xl bg-accent px-4 py-3 text-sm font-semibold text-primary">Página {pagination.page}</span>
        {pagination.has_next ? (
          <a className="inline-flex min-h-11 items-center rounded-xl border border-border px-4 py-3 text-sm font-semibold text-primary hover:bg-accent" href={nextHref}>
            Próxima
          </a>
        ) : null}
      </nav>
    </section>
  );
}
