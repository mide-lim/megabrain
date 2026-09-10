import type { ReactNode } from "react";

import type { OwnerSession } from "../lib/auth/session";

type AppPath = "/inbox" | "/library" | "/categories" | "/settings";

type AppShellProps = {
  children?: ReactNode;
  owner: OwnerSession;
  pathname: AppPath;
};

const navigation: ReadonlyArray<{ href: AppPath; label: string }> = [
  { href: "/inbox", label: "Inbox" },
  { href: "/library", label: "Biblioteca" },
  { href: "/categories", label: "Categorias" },
  { href: "/settings", label: "Configurações" },
];

function Brand() {
  return (
    <a className="inline-flex min-h-11 items-center gap-3 rounded-lg font-semibold text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-primary" href="/inbox" translate="no">
      <span aria-hidden="true" className="grid h-8 w-8 place-items-center rounded-lg bg-primary text-sm font-bold text-white">M</span>
      <span>MegaBrain</span>
    </a>
  );
}

function Navigation({ pathname, compact = false }: { pathname: AppPath; compact?: boolean }) {
  return (
    <nav aria-label="Navegação principal" className={compact ? "flex gap-1 overflow-x-auto pb-1" : "space-y-1"}>
      {navigation.map((item) => {
        const active = pathname === item.href;
        return (
          <a
            aria-current={active ? "page" : undefined}
            className={`inline-flex min-h-11 items-center rounded-lg px-3 py-2 text-sm font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary ${compact ? "shrink-0" : "w-full"} ${active ? "bg-accent text-primary" : "text-muted hover:bg-accent hover:text-foreground"}`}
            href={item.href}
            key={item.href}
          >
            {item.label}
          </a>
        );
      })}
    </nav>
  );
}

function DeferredAddReel() {
  return (
    <div className="flex items-center gap-2">
      <button
        aria-describedby="add-reel-deferred"
        className="min-h-11 cursor-not-allowed rounded-lg border border-border bg-surface px-4 py-2 text-sm font-semibold text-muted disabled:opacity-80"
        disabled
        type="button"
      >
        + Adicionar Reel
      </button>
      <span className="text-xs font-medium text-muted" id="add-reel-deferred">Em breve</span>
    </div>
  );
}

export function AppShell({ children, owner, pathname }: AppShellProps) {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <a className="sr-only rounded-md bg-surface px-3 py-2 text-sm font-semibold text-primary focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-20" href="#app-content">
        Pular para o conteúdo
      </a>
      <header className="border-b border-border bg-surface px-4 py-3 sm:px-6 lg:px-8">
        <div className="mx-auto flex max-w-[90rem] items-center justify-between gap-4">
          <Brand />
          <DeferredAddReel />
        </div>
        <div className="mx-auto mt-2 max-w-[90rem] md:hidden">
          <Navigation compact pathname={pathname} />
        </div>
      </header>
      <div className="mx-auto grid max-w-[90rem] md:grid-cols-[13rem_minmax(0,1fr)]">
        <aside className="hidden min-h-[calc(100vh-4.25rem)] border-r border-border bg-surface px-3 py-6 md:flex md:flex-col" aria-label="Barra lateral">
          <Navigation pathname={pathname} />
          <div className="mt-auto min-w-0 border-t border-border px-3 pt-4">
            <p className="text-xs font-medium text-muted">Sessão do proprietário</p>
            <p className="mt-1 break-words text-sm font-medium text-foreground">{owner.email}</p>
          </div>
        </aside>
        <main className="min-w-0 px-4 py-8 sm:px-6 lg:px-10 lg:py-10" id="app-content">
          <div className="mx-auto max-w-6xl">{children}</div>
        </main>
      </div>
    </div>
  );
}
