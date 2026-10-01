import type { Metadata } from "next";

import { AppShell } from "../../components/app-shell";
import { requireOwnerSession } from "../../lib/auth/session";
import { DevelopmentPageContent } from "./development-page-content";
import { fetchPaperclipAvailability } from "./paperclip-status";

export const metadata: Metadata = {
  title: "Desenvolvimento | MegaBrain",
  description: "Acesso ao ambiente de desenvolvimento do MegaBrain.",
};

export default async function DevelopmentPage() {
  const owner = await requireOwnerSession();
  const paperclipAvailable = await fetchPaperclipAvailability();

  return (
    <AppShell owner={owner} pathname="/development">
      <DevelopmentPageContent paperclipAvailable={paperclipAvailable} />
    </AppShell>
  );
}
