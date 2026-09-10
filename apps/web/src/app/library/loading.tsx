export default function LibraryLoading() {
  return (
    <main aria-busy="true" aria-live="polite" className="min-h-screen bg-background px-4 py-4 sm:px-6 sm:py-6">
      <div className="mx-auto max-w-7xl rounded-3xl border border-border bg-surface px-5 py-8 shadow-[0_24px_60px_rgba(32,37,34,0.08)] sm:px-8 sm:py-10 lg:px-10">
        <p className="text-sm font-semibold text-primary">MegaBrain · Biblioteca</p>
        <h1 className="mt-5 text-3xl font-semibold tracking-tight text-foreground">Carregando Biblioteca…</h1>
        <p className="mt-4 text-sm leading-6 text-muted" role="status">Buscando os Reels mais recentes.</p>
      </div>
    </main>
  );
}
