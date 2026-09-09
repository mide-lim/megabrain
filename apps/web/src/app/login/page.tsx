import type { Metadata } from "next";

import LoginSession from "./login-session";

export const metadata: Metadata = {
  title: "Entrar | MegaBrain",
  description: "Acesse seu espaço pessoal de conhecimento e IA no MegaBrain.",
};

export default function LoginPage() {
  return (
    <main className="min-h-screen bg-background px-4 py-4 sm:px-6 sm:py-6">
      <a
        className="sr-only rounded-md bg-surface px-3 py-2 text-sm font-semibold text-primary focus:not-sr-only focus:absolute focus:left-4 focus:top-4"
        href="#login-content"
      >
        Pular para o conteúdo
      </a>
      <div className="mx-auto flex min-h-[calc(100vh-2rem)] max-w-6xl flex-col sm:min-h-[calc(100vh-3rem)]">
        <header className="flex items-center justify-between px-2 py-4 sm:px-4">
          <a
            className="inline-flex items-center gap-3 rounded-lg text-sm font-semibold text-foreground focus-visible:outline-none"
            href="/login"
            translate="no"
          >
            <span aria-hidden="true" className="grid h-8 w-8 place-items-center rounded-lg bg-primary text-sm font-bold text-white">
              M
            </span>
            MegaBrain
          </a>
          <span className="text-sm text-muted">Espaço pessoal</span>
        </header>

        <section
          aria-labelledby="megabrain-login-title"
          className="grid flex-1 overflow-hidden rounded-3xl border border-border bg-surface shadow-[0_24px_60px_rgba(32,37,34,0.10)] lg:grid-cols-[0.92fr_1.08fr]"
        >
          <div className="flex flex-col justify-between bg-primary px-7 py-10 text-white sm:px-10 sm:py-12">
            <div>
              <p className="text-sm font-semibold text-white/75">MegaBrain</p>
              <h1
                className="mt-6 max-w-md text-4xl font-semibold tracking-tight text-balance sm:text-5xl"
                id="megabrain-login-title"
              >
                Um lugar para o que importa lembrar.
              </h1>
              <p className="mt-6 max-w-md text-base leading-7 text-white/80 sm:text-lg">
                Seu espaço pessoal para reunir conhecimento, manter contexto e trabalhar com IA de forma mais intencional.
              </p>
            </div>
            <p className="mt-12 max-w-sm border-t border-white/20 pt-5 text-sm leading-6 text-white/70">
              A Biblioteca de Reels continua disponível publicamente enquanto o acesso do proprietário evolui.
            </p>
          </div>

          <div className="px-7 py-10 sm:px-10 sm:py-12 lg:px-14" id="login-content">
            <LoginSession />
          </div>
        </section>
      </div>
    </main>
  );
}
