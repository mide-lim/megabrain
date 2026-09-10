import type { Metadata } from "next";

import { fetchLibraryPage } from "./library-api";
import { LibraryPageContent } from "./library-page-content";

export const metadata: Metadata = {
  title: "Biblioteca de Reels | MegaBrain",
  description: "Explore a biblioteca pública de Reels do MegaBrain.",
};

type LibraryPageProps = {
  searchParams: Promise<{ page?: string | string[]; q?: string | string[] }>;
};

function firstSearchValue(value: string | string[] | undefined): string {
  return typeof value === "string" ? value : "";
}

function pageFromSearch(value: string | string[] | undefined): number {
  const page = Number(firstSearchValue(value));
  return Number.isSafeInteger(page) && page >= 1 ? page : 1;
}

export default async function LibraryPage({ searchParams }: LibraryPageProps) {
  const params = await searchParams;
  const q = firstSearchValue(params.q).trim();
  const page = pageFromSearch(params.page);
  const library = await fetchLibraryPage({ page, q });

  return <LibraryPageContent library={library} />;
}
