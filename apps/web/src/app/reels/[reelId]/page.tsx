import type { Metadata } from "next";

import { AppShell } from "../../../components/app-shell";
import { requireOwnerSession } from "../../../lib/auth/session";
import { fetchReelDetail } from "./reel-detail-api";
import { ReelDetailPageContent, ReelNotFoundState, ReelUnavailableState } from "./reel-detail-page-content";

export const metadata: Metadata = {
  title: "Detalhe do Reel | MegaBrain",
  description: "Consulte um Reel da sua biblioteca MegaBrain.",
};

type ReelDetailPageProps = {
  params: Promise<{ reelId: string }>;
};

function reelIdFromParam(value: string): number | null {
  const reelId = Number(value);
  return Number.isSafeInteger(reelId) && reelId > 0 ? reelId : null;
}

export default async function ReelDetailPage({ params }: ReelDetailPageProps) {
  const owner = await requireOwnerSession();
  const { reelId: reelIdParam } = await params;
  const reelId = reelIdFromParam(reelIdParam);
  const result = reelId === null ? { kind: "not-found" as const } : await fetchReelDetail(reelId);

  return (
    <AppShell owner={owner} pathname="/library">
      {result.kind === "ok" ? <ReelDetailPageContent reel={result.reel} /> : null}
      {result.kind === "not-found" ? <ReelNotFoundState /> : null}
      {result.kind === "unavailable" ? <ReelUnavailableState /> : null}
    </AppShell>
  );
}
