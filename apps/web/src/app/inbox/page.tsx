import type { Metadata } from "next";

import { AppShell } from "../../components/app-shell";
import { requireOwnerSession } from "../../lib/auth/session";
import { fetchInboxPage } from "./inbox-api";
import { InboxPageContent } from "./inbox-page-content";

export const metadata: Metadata = {
  title: "Inbox | MegaBrain",
  description: "O espaço de triagem de conteúdos capturados no MegaBrain.",
};

type InboxPageProps = {
  searchParams: Promise<{ page?: string | string[] }>;
};

function pageFromSearch(value: string | string[] | undefined): number {
  const raw = typeof value === "string" ? value : "";
  const page = Number(raw);
  return Number.isSafeInteger(page) && page >= 1 ? page : 1;
}

export default async function InboxPage({ searchParams }: InboxPageProps) {
  const owner = await requireOwnerSession();
  const params = await searchParams;
  const page = pageFromSearch(params.page);
  const inbox = await fetchInboxPage(page);

  return (
    <AppShell owner={owner} pathname="/inbox">
      <InboxPageContent inbox={inbox} />
    </AppShell>
  );
}
