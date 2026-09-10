import type { ReactNode } from "react";

import type { ReelCategory, ReelDetail } from "./reel-detail-api";
import { ReelCategoryControls } from "./reel-category-controls";

function readableDate(value: string | null): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return null;
  return new Intl.DateTimeFormat("pt-BR", { dateStyle: "medium", timeZone: "UTC" }).format(date);
}

function readableDuration(value: number | null): string | null {
  if (value === null || !Number.isFinite(value) || value < 0) return null;
  const minutes = Math.floor(value / 60);
  const seconds = value - (minutes * 60);
  const formattedSeconds = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 }).format(seconds);
  return minutes > 0 ? `${minutes} min ${formattedSeconds} s` : `${formattedSeconds} s`;
}

function readableFileSize(value: number | null): string | null {
  if (value === null || !Number.isFinite(value) || value < 0) return null;
  if (value < 1024) return `${value} B`;
  const units = ["KB", "MB", "GB"];
  let size = value / 1024;
  let unit = units[0];
  for (const nextUnit of units.slice(1)) {
    if (size < 1024) break;
    size /= 1024;
    unit = nextUnit;
  }
  return `${new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 }).format(size)} ${unit}`;
}

function detailTitle(reel: ReelDetail): string {
  return reel.title?.trim() || reel.shortcode?.trim() || `Reel ${reel.id}`;
}

function DetailValue({ label, value }: { label: string; value: string | null }) {
  return value ? <div className="min-w-0 border-t border-border pt-3"><dt className="text-xs font-semibold text-muted">{label}</dt><dd className="mt-1 break-words text-sm leading-6 text-foreground">{value}</dd></div> : null;
}

export function ReelNotFoundState() {
  return (
    <section className="max-w-2xl rounded-2xl border border-border bg-surface px-6 py-10 sm:px-8" role="status">
      <h1 className="text-2xl font-semibold tracking-tight text-foreground">Reel não encontrado</h1>
      <p className="mt-3 text-sm leading-6 text-muted">Este Reel não está disponível na sua Biblioteca.</p>
      <a className="mt-6 inline-flex min-h-11 items-center rounded-xl border border-border px-4 py-2 text-sm font-semibold text-primary hover:bg-accent" href="/library">Voltar para Biblioteca</a>
    </section>
  );
}

export function ReelUnavailableState() {
  return (
    <section className="max-w-2xl rounded-2xl border border-border bg-surface px-6 py-10 sm:px-8" role="status">
      <h1 className="text-2xl font-semibold tracking-tight text-foreground">Reel temporariamente indisponível</h1>
      <p className="mt-3 text-sm leading-6 text-muted">Não foi possível carregar este Reel agora. Tente novamente em alguns instantes.</p>
      <a className="mt-6 inline-flex min-h-11 items-center rounded-xl border border-border px-4 py-2 text-sm font-semibold text-primary hover:bg-accent" href="/library">Voltar para Biblioteca</a>
    </section>
  );
}

function AssignedCategorySummary({ categories }: { categories: ReelCategory[] }) {
  return (
    <section aria-labelledby="reel-categories-summary-title" className="rounded-2xl border border-border bg-surface p-5 shadow-[0_12px_30px_rgba(32,37,34,0.06)] sm:p-6">
      <h2 className="text-xl font-semibold tracking-tight text-foreground" id="reel-categories-summary-title">Categorias</h2>
      <h3 className="mt-5 text-sm font-semibold text-foreground">Categorias atribuídas</h3>
      {categories.length > 0 ? <ul aria-label="Categorias atribuídas" className="mt-3 flex flex-wrap gap-2">{categories.map((category) => <li className="max-w-full break-words rounded-full bg-accent px-3 py-1 text-sm font-semibold text-primary" key={category.id}>{category.name}</li>)}</ul> : <p className="mt-3 text-sm leading-6 text-muted">Nenhuma categoria atribuída.</p>}
    </section>
  );
}

export function ReelDetailPageContent({ reel, categoryControls }: { reel: ReelDetail; categoryControls?: ReactNode }) {
  const title = detailTitle(reel);
  const creator = reel.creator?.trim() || "Criador não informado";
  const duration = readableDuration(reel.duration_seconds);
  const receivedAt = readableDate(reel.received_at);
  const downloadedAt = readableDate(reel.downloaded_at);
  const transcriptCompletedAt = readableDate(reel.transcript.completed_at);
  const fileSize = readableFileSize(reel.file_size_bytes);

  return (
    <div id="reel-detail-content">
      <a className="inline-flex min-h-11 items-center rounded-lg text-sm font-semibold text-primary underline decoration-primary/25 decoration-2 underline-offset-4 hover:decoration-primary" href="/library">← Voltar para Biblioteca</a>
      <header className="mt-6 max-w-3xl">
        <h1 className="break-words text-4xl font-semibold tracking-tight text-foreground text-balance sm:text-5xl">{title}</h1>
        <p className="mt-3 break-words text-lg font-medium text-primary">{creator}</p>
      </header>

      <div className="mt-8 grid gap-6 xl:grid-cols-[minmax(0,1fr)_22rem] xl:items-start">
        <section aria-label="Vídeo do Reel" className="overflow-hidden rounded-2xl border border-border bg-surface p-3 shadow-[0_12px_30px_rgba(32,37,34,0.06)] sm:p-4">
          <div className="mx-auto flex aspect-[9/16] max-h-[42rem] w-full max-w-[28rem] items-center justify-center overflow-hidden rounded-xl bg-foreground/5">
            {reel.video.available && reel.video.src ? <video className="h-full w-full object-contain" controls preload="metadata" src={reel.video.src}>Seu navegador não oferece suporte à reprodução de vídeo.</video> : <p className="px-6 text-center text-sm leading-6 text-muted">Vídeo temporariamente indisponível.</p>}
          </div>
        </section>
        <aside className="space-y-6">
          <AssignedCategorySummary categories={reel.categories.assigned} />
          {categoryControls === undefined ? <ReelCategoryControls assignedCategories={reel.categories.assigned} availableCategories={reel.categories.available} reelId={reel.id} /> : categoryControls}
          <section className="rounded-2xl border border-border bg-surface p-5 shadow-[0_12px_30px_rgba(32,37,34,0.06)] sm:p-6">
            <h2 className="text-xl font-semibold tracking-tight text-foreground">Detalhes</h2>
            <dl className="mt-5 space-y-3">
              <DetailValue label="Status" value={reel.status?.trim() || "Não informado"} />
              <DetailValue label="Shortcode" value={reel.shortcode?.trim() || null} />
              <DetailValue label="Duração" value={duration} />
              <DetailValue label="Recebido em" value={receivedAt} />
              <DetailValue label="Baixado em" value={downloadedAt} />
              <DetailValue label="Arquivo" value={reel.filename?.trim() || null} />
              <DetailValue label="Tipo MIME" value={reel.mime_type?.trim() || null} />
              <DetailValue label="Tamanho" value={fileSize} />
            </dl>
            {reel.original_url ? <a className="mt-5 inline-flex min-h-11 items-center rounded-lg text-sm font-semibold text-primary underline decoration-primary/25 decoration-2 underline-offset-4 hover:decoration-primary" href={reel.original_url} rel="noopener noreferrer" target="_blank">Abrir Reel original</a> : null}
          </section>
        </aside>
      </div>

      <section className="mt-8 max-w-4xl rounded-2xl border border-border bg-surface p-5 shadow-[0_12px_30px_rgba(32,37,34,0.06)] sm:p-6">
        <h2 className="text-2xl font-semibold tracking-tight text-foreground">Conteúdo</h2>
        <h3 className="mt-5 text-sm font-semibold text-muted">Legenda original</h3>
        {reel.caption?.trim() ? <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-7 text-foreground">{reel.caption}</p> : <p className="mt-2 text-sm leading-6 text-muted">Legenda original não disponível.</p>}
      </section>

      <section className="mt-6 max-w-4xl rounded-2xl border border-border bg-surface p-5 shadow-[0_12px_30px_rgba(32,37,34,0.06)] sm:p-6">
        <h2 className="text-2xl font-semibold tracking-tight text-foreground">Transcrição</h2>
        {reel.transcript.available && reel.transcript.text ? (
          <>
            <p className="mt-4 whitespace-pre-wrap break-words text-sm leading-7 text-foreground">{reel.transcript.text}</p>
            {reel.transcript.language || transcriptCompletedAt ? <p className="mt-4 text-sm leading-6 text-muted">{reel.transcript.language ? `Idioma: ${reel.transcript.language}` : null}{reel.transcript.language && transcriptCompletedAt ? " · " : null}{transcriptCompletedAt ? `Concluída em ${transcriptCompletedAt}` : null}</p> : null}
          </>
        ) : <p className="mt-4 text-sm leading-6 text-muted">Transcrição ainda não disponível.</p>}
      </section>
    </div>
  );
}
