import type { Metadata } from "next";

import { AppShell } from "../../../components/app-shell";
import { requireOwnerSession } from "../../../lib/auth/session";
import { CategoryDetailActions } from "../category-actions";
import { fetchCategoryDetail, type CategoryDetailFetchResult } from "../categories-api";
import { CategoryDetailPageContent } from "./category-detail-page-content";

export const metadata: Metadata = {
  title: "Categoria | MegaBrain",
  description: "Navegue pelos Reels associados a uma categoria do MegaBrain.",
};

type CategoryPageProps = {
  params: Promise<{ categoryId: string }>;
  searchParams: Promise<{ page?: string | string[] }>;
};

function pageFromSearch(value: string | string[] | undefined): number {
  const raw = typeof value === "string" ? value : "";
  const page = Number(raw);
  return Number.isSafeInteger(page) && page >= 1 ? page : 1;
}

export default async function CategoryPage({ params, searchParams }: CategoryPageProps) {
  const owner = await requireOwnerSession();
  const route = await params;
  const query = await searchParams;
  const categoryId = Number(route.categoryId);
  const page = pageFromSearch(query.page);

  let result: CategoryDetailFetchResult;
  if (!Number.isSafeInteger(categoryId) || categoryId <= 0) {
    result = { kind: "not-found" };
  } else {
    result = await fetchCategoryDetail(categoryId, page);
  }

  const actions = result.kind === "ok" ? (
    <CategoryDetailActions
      categoryId={result.data.category.id}
      name={result.data.category.name}
      reelCount={result.data.category.reel_count}
    />
  ) : null;

  return (
    <AppShell owner={owner} pathname="/categories">
      <CategoryDetailPageContent actions={actions} result={result} />
    </AppShell>
  );
}
