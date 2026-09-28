import type { Metadata } from "next";

import { AppShell } from "../../components/app-shell";
import { requireOwnerSession } from "../../lib/auth/session";
import { CategoryCreateForm } from "./category-actions";
import { fetchCategories } from "./categories-api";
import { CategoriesPageContent } from "./categories-page-content";

export const metadata: Metadata = {
  title: "Categorias | MegaBrain",
  description: "Organize e navegue pelo conhecimento salvo no MegaBrain.",
};

export default async function CategoriesPage() {
  const owner = await requireOwnerSession();
  const categories = await fetchCategories();

  return (
    <AppShell owner={owner} pathname="/categories">
      <CategoriesPageContent categories={categories} createControl={<CategoryCreateForm />} />
    </AppShell>
  );
}
