"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import type { ReelCategory } from "./reel-detail-api";

type MutationMethod = "POST" | "DELETE";

export function reconcileSelectedCategoryId(selectedCategoryId: string, availableCategories: ReelCategory[]): string {
  if (availableCategories.some((category) => String(category.id) === selectedCategoryId)) {
    return selectedCategoryId;
  }
  return availableCategories[0] ? String(availableCategories[0].id) : "";
}

function isCsrfPayload(value: unknown): value is { csrf_token: string } {
  return typeof value === "object" && value !== null && typeof (value as { csrf_token?: unknown }).csrf_token === "string";
}

export async function performCategoryMutation(
  path: string,
  method: MutationMethod,
  body: Record<string, unknown> | undefined,
  request: typeof fetch = fetch,
): Promise<boolean> {
  try {
    const csrfResponse = await request("/api/auth/csrf", {
      cache: "no-store",
      credentials: "same-origin",
      headers: { accept: "application/json" },
    });
    const csrfPayload: unknown = await csrfResponse.json().catch(() => null);
    if (!csrfResponse.ok || !isCsrfPayload(csrfPayload)) {
      return false;
    }

    const headers: Record<string, string> = { "X-CSRF-Token": csrfPayload.csrf_token };
    if (body !== undefined) {
      headers["Content-Type"] = "application/json";
    }
    const response = await request(path, {
      method,
      credentials: "same-origin",
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    return response.status === 204;
  } catch {
    return false;
  }
}

type ReelCategoryControlsProps = {
  reelId: number;
  assignedCategories: ReelCategory[];
  availableCategories: ReelCategory[];
};

export function ReelCategoryControls({ reelId, assignedCategories, availableCategories }: ReelCategoryControlsProps) {
  const router = useRouter();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedCategoryId, setSelectedCategoryId] = useState(() => reconcileSelectedCategoryId("", availableCategories));
  const [newCategory, setNewCategory] = useState("");

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- Reconcile controlled selection after canonical server props refresh.
    setSelectedCategoryId((currentSelection) => reconcileSelectedCategoryId(currentSelection, availableCategories));
  }, [availableCategories]);

  async function runMutation(path: string, method: MutationMethod, body: Record<string, unknown> | undefined, failureMessage: string) {
    if (pending) return;
    setPending(true);
    setError(null);
    const succeeded = await performCategoryMutation(path, method, body);
    setPending(false);
    if (!succeeded) {
      setError(failureMessage);
      return;
    }
    setNewCategory("");
    router.refresh();
  }

  function assignExistingCategory(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const categoryId = Number(selectedCategoryId);
    if (!Number.isSafeInteger(categoryId) || categoryId <= 0) return;
    void runMutation(`/api/reels/${reelId}/categories`, "POST", { category_id: categoryId }, "Não foi possível atualizar as categorias.");
  }

  function createCategory(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const name = newCategory.trim();
    if (!name) {
      setError("Não foi possível criar a categoria.");
      return;
    }
    void runMutation(`/api/reels/${reelId}/categories/new`, "POST", { name }, "Não foi possível criar a categoria.");
  }

  return (
    <section aria-labelledby="reel-category-actions-title" className="rounded-2xl border border-border bg-surface p-5 shadow-[0_12px_30px_rgba(32,37,34,0.06)] sm:p-6">
      <h2 className="text-xl font-semibold tracking-tight text-foreground" id="reel-category-actions-title">Ações de categoria</h2>
      {error ? <p className="mt-3 text-sm font-medium text-danger" role="alert">{error}</p> : null}

      {assignedCategories.length > 0 ? (
        <div className="mt-5">
          <h3 className="text-sm font-semibold text-foreground">Remover categoria</h3>
          <ul className="mt-3 flex flex-wrap gap-2">
            {assignedCategories.map((category) => (
              <li key={category.id}>
                <button aria-label={`Remover categoria ${category.name}`} className="min-h-10 rounded-xl border border-border px-3 py-2 text-sm font-semibold text-primary hover:bg-accent disabled:cursor-not-allowed disabled:opacity-60" disabled={pending} onClick={() => void runMutation(`/api/reels/${reelId}/categories/${category.id}`, "DELETE", undefined, "Não foi possível atualizar as categorias.")} type="button">
                  Remover {category.name}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {availableCategories.length > 0 ? (
        <form className="mt-6 border-t border-border pt-5" onSubmit={assignExistingCategory}>
          <label className="block text-sm font-semibold text-foreground" htmlFor="existing-category">Adicionar categoria existente</label>
          <div className="mt-3 flex flex-col gap-3 sm:flex-row">
            <select className="min-h-11 min-w-0 flex-1 rounded-xl border border-border bg-surface px-3 text-base text-foreground" disabled={pending} id="existing-category" name="category_id" onChange={(event) => setSelectedCategoryId(event.target.value)} value={selectedCategoryId}>
              {availableCategories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}
            </select>
            <button className="min-h-11 rounded-xl border border-border px-4 py-2 text-sm font-semibold text-primary hover:bg-accent disabled:cursor-not-allowed disabled:opacity-60" disabled={pending} type="submit">{pending ? "Atualizando…" : "Adicionar categoria"}</button>
          </div>
        </form>
      ) : null}

      <form className="mt-6 border-t border-border pt-5" onSubmit={createCategory}>
        <label className="block text-sm font-semibold text-foreground" htmlFor="new-category">Criar categoria</label>
        <div className="mt-3 flex flex-col gap-3 sm:flex-row">
          <input className="min-h-11 min-w-0 flex-1 rounded-xl border border-border bg-surface px-3 text-base text-foreground" disabled={pending} id="new-category" name="name" onChange={(event) => setNewCategory(event.target.value)} value={newCategory} />
          <button className="min-h-11 rounded-xl bg-primary px-4 py-2 text-sm font-semibold text-white hover:bg-[#1f452f] disabled:cursor-not-allowed disabled:opacity-60" disabled={pending} type="submit">{pending ? "Criando…" : "Criar e adicionar"}</button>
        </div>
      </form>
    </section>
  );
}
