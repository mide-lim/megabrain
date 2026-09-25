"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { requestReelTranscription } from "../../../lib/reel-transcription-api";
import type { ReelLifecycleProjection } from "../../../lib/reel-lifecycle";

type Transcript = {
  available: boolean;
  text: string | null;
  language: string | null;
  completed_at: string | null;
};

type ReelTranscriptionControlsProps = {
  lifecycle: ReelLifecycleProjection;
  transcript: Transcript;
};

function readableDate(value: string | null): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return null;
  return new Intl.DateTimeFormat("pt-BR", { dateStyle: "medium", timeZone: "UTC" }).format(date);
}

export function ReelTranscriptionControls({ lifecycle: initialLifecycle, transcript }: ReelTranscriptionControlsProps) {
  const router = useRouter();
  const [lifecycle, setLifecycle] = useState(initialLifecycle);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isPollable = lifecycle.transcription_status === "queued" || lifecycle.transcription_status === "processing";
  const completedAt = readableDate(transcript.completed_at);

  useEffect(() => {
    if (!isPollable || pending) return;
    const timer = window.setTimeout(() => router.refresh(), 5000);
    return () => window.clearTimeout(timer);
  }, [isPollable, pending, router]);

  async function requestTranscription() {
    if (pending) return;
    setPending(true);
    setError(null);
    const confirmed = await requestReelTranscription(lifecycle.id);
    setPending(false);
    if (confirmed === null) {
      setError("Não foi possível solicitar a transcrição. Tente novamente.");
      return;
    }
    setLifecycle(confirmed);
    router.refresh();
  }

  function renderContent() {
    switch (lifecycle.transcription_status) {
      case "not_requested":
        if (lifecycle.download_status !== "downloaded") {
          return <p className="mt-4 text-sm leading-6 text-muted">A transcrição ficará disponível após o download do Reel.</p>;
        }
        return <>
          <p className="mt-4 text-sm leading-6 text-muted">Ainda não solicitada.</p>
          <button className="mt-4 min-h-11 rounded-xl bg-primary px-4 py-2 text-sm font-semibold text-white hover:bg-[#1f452f] disabled:cursor-not-allowed disabled:opacity-60" disabled={pending} onClick={() => void requestTranscription()} type="button">{pending ? "Solicitando…" : "Transcrever"}</button>
        </>;
      case "queued":
        return <p className="mt-4 text-sm leading-6 text-muted">Na fila para transcrição.</p>;
      case "processing":
        return <p className="mt-4 text-sm leading-6 text-muted">Transcrevendo…</p>;
      case "completed":
        if (!transcript.available || !transcript.text) {
          return <p className="mt-4 text-sm leading-6 text-muted">Transcrição ainda não disponível.</p>;
        }
        return <>
          <p className="mt-4 whitespace-pre-wrap break-words text-sm leading-7 text-foreground">{transcript.text}</p>
          {transcript.language || completedAt ? <p className="mt-4 text-sm leading-6 text-muted">{transcript.language ? `Idioma: ${transcript.language}` : null}{transcript.language && completedAt ? " · " : null}{completedAt ? `Concluída em ${completedAt}` : null}</p> : null}
        </>;
      case "failed":
        return <>
          <p className="mt-4 text-sm leading-6 text-muted">Não foi possível concluir a transcrição.</p>
          <button className="mt-4 min-h-11 rounded-xl border border-border px-4 py-2 text-sm font-semibold text-primary hover:bg-accent disabled:cursor-not-allowed disabled:opacity-60" disabled={pending} onClick={() => void requestTranscription()} type="button">{pending ? "Solicitando…" : "Tentar novamente"}</button>
        </>;
    }
  }

  return (
    <section aria-labelledby={`reel-transcription-${lifecycle.id}`} className="mt-6 max-w-4xl rounded-2xl border border-border bg-surface p-5 shadow-[0_12px_30px_rgba(32,37,34,0.06)] sm:p-6">
      <h2 className="text-2xl font-semibold tracking-tight text-foreground" id={`reel-transcription-${lifecycle.id}`}>Transcrição</h2>
      <div aria-live="polite">{renderContent()}</div>
      {error ? <p className="mt-3 text-sm font-medium text-danger" role="alert">{error}</p> : null}
    </section>
  );
}
