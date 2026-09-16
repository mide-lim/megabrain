"use client";

import { useState } from "react";

import { performCurationMutation } from "../lib/reel-curation-api";
import type { CurationStatus, DownloadStatus, ReelLifecycleProjection, TranscriptionStatus } from "../lib/reel-lifecycle";

type LifecyclePresentation = {
  label: string;
  description: string;
  tone: "muted" | "warning" | "success" | "danger";
};

const unknownPresentation: LifecyclePresentation = {
  label: "Desconhecido",
  description: "Estado não reconhecido",
  tone: "danger",
};

const downloadPresentations: Record<DownloadStatus, LifecyclePresentation> = {
  received: { label: "Recebido", description: "Aguardando download", tone: "muted" },
  downloading: { label: "Baixando", description: "Download em andamento", tone: "warning" },
  downloaded: { label: "Disponível", description: "Mídia disponível", tone: "success" },
  failed: { label: "Falhou", description: "Problema no download", tone: "danger" },
};

const transcriptionPresentations: Record<TranscriptionStatus, LifecyclePresentation> = {
  not_requested: { label: "Não solicitada", description: "Ainda não entrou em processamento", tone: "muted" },
  queued: { label: "Na fila", description: "Aguardando processamento", tone: "warning" },
  processing: { label: "Em processamento", description: "Transcrição e enriquecimento em andamento", tone: "warning" },
  completed: { label: "Concluída", description: "Processamento concluído", tone: "success" },
  failed: { label: "Falhou", description: "Transcrição ou enriquecimento falhou", tone: "danger" },
};

const curationPresentations: Record<CurationStatus, LifecyclePresentation> = {
  inbox: { label: "Inbox", description: "Aguardando organização", tone: "muted" },
  organized: { label: "Organizado", description: "Organizado por você", tone: "success" },
};

export function downloadStatusPresentation(value: string): LifecyclePresentation {
  return downloadPresentations[value as DownloadStatus] ?? unknownPresentation;
}

export function transcriptionStatusPresentation(value: string): LifecyclePresentation {
  return transcriptionPresentations[value as TranscriptionStatus] ?? unknownPresentation;
}

export function curationStatusPresentation(value: string): LifecyclePresentation {
  return curationPresentations[value as CurationStatus] ?? unknownPresentation;
}

function toneClassName(tone: LifecyclePresentation["tone"]): string {
  if (tone === "success") return "bg-accent text-success";
  if (tone === "warning") return "bg-[#f7ecd9] text-warning";
  if (tone === "danger") return "bg-[#f8e4e4] text-danger";
  return "bg-accent text-muted";
}

function LifecycleItem({ label, presentation }: { label: string; presentation: LifecyclePresentation }) {
  return (
    <div className="flex min-w-0 items-center justify-between gap-3">
      <dt className="text-sm font-medium text-foreground">{label}</dt>
      <dd className={`shrink-0 rounded-full px-3 py-1 text-xs font-semibold ${toneClassName(presentation.tone)}`} title={presentation.description}>
        {presentation.label}
      </dd>
    </div>
  );
}

type ReelLifecycleProps = {
  compact?: boolean;
  lifecycle: ReelLifecycleProjection;
  reelId: number;
};

export function ReelLifecycle({ compact = false, lifecycle: initialLifecycle, reelId }: ReelLifecycleProps) {
  const [lifecycle, setLifecycle] = useState(initialLifecycle);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const target: CurationStatus = lifecycle.curation_status === "inbox" ? "organized" : "inbox";
  const actionLabel = target === "organized" ? "Organizar" : "Mover para Inbox";
  const actionAriaLabel = target === "organized" ? "Organizar Reel" : "Mover Reel para Inbox";

  async function updateCuration() {
    if (pending) return;
    setPending(true);
    setError(null);
    setSuccess(null);
    const confirmed = await performCurationMutation(reelId, target);
    setPending(false);
    if (confirmed === null) {
      setError("Não foi possível atualizar a organização. Tente novamente.");
      return;
    }
    setLifecycle(confirmed);
    setSuccess("Organização atualizada.");
  }

  return (
    <section aria-labelledby={`reel-lifecycle-${reelId}`} className={compact ? "mt-5 border-t border-border pt-4" : "rounded-2xl border border-border bg-surface p-5 shadow-[0_12px_30px_rgba(32,37,34,0.06)] sm:p-6"}>
      <h2 className={compact ? "sr-only" : "text-xl font-semibold tracking-tight text-foreground"} id={`reel-lifecycle-${reelId}`}>Ciclo de vida</h2>
      <section aria-labelledby={`reel-system-state-${reelId}`} className={compact ? "" : "mt-5"}>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted" id={`reel-system-state-${reelId}`}>Estado do sistema</h3>
        <dl className="mt-3 space-y-3">
          <LifecycleItem label="Download" presentation={downloadStatusPresentation(lifecycle.download_status)} />
          <LifecycleItem label="Transcrição" presentation={transcriptionStatusPresentation(lifecycle.transcription_status)} />
        </dl>
      </section>
      <section aria-labelledby={`reel-user-state-${reelId}`} className="mt-5 border-t border-border pt-4">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted" id={`reel-user-state-${reelId}`}>Organização</h3>
        <dl className="mt-3">
          <LifecycleItem label="Organização" presentation={curationStatusPresentation(lifecycle.curation_status)} />
        </dl>
        <button aria-label={actionAriaLabel} className="mt-4 min-h-11 rounded-xl border border-border px-4 py-2 text-sm font-semibold text-primary hover:bg-accent disabled:cursor-not-allowed disabled:opacity-60" disabled={pending} onClick={() => void updateCuration()} type="button">
          {actionLabel}
        </button>
        {pending ? <p aria-live="polite" className="mt-3 text-sm font-medium text-muted" role="status">Atualizando…</p> : null}
        {success ? <p aria-live="polite" className="mt-3 text-sm font-medium text-success" role="status">{success}</p> : null}
        {error ? <p className="mt-3 text-sm font-medium text-danger" role="alert">{error}</p> : null}
      </section>
    </section>
  );
}
