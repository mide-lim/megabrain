export default function HomePage() {
  return (
    <main className="grid min-h-screen place-items-center bg-background p-6">
      <section className="w-full max-w-xl rounded-lg border border-border bg-surface p-8 shadow-sm">
        <p className="text-sm font-semibold tracking-wide text-primary">MegaBrain</p>
        <h1 className="mt-3 text-3xl font-bold text-foreground">
          Frontend Foundation
        </h1>
        <p className="mt-4 text-muted">Next.js + TypeScript</p>
        <p className="mt-8 inline-flex rounded-full border border-border bg-background px-3 py-1 text-sm font-medium text-success">
          Status: Ready
        </p>
      </section>
    </main>
  );
}
