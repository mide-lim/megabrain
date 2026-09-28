"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { fetchCsrfToken } from "../../lib/csrf-client";

type CategoryMutationResult = "ok" | "conflict" | "error";
type CategoryMutationMethod = "POST" | "PATCH" | "DELETE";

export async function performCategoryMutation(
  path: string,
  method: CategoryMutationMethod,
  body: Record<string, unknown> | undefined,
  request: typeof fetch = fetch,
): Promise<CategoryMutationResult> {
  const csrfToken = await fetchCsrfToken(request);
  if (csrfToken === null) return "error";

  const headers: Record<string, string> = { "X-CSRF-Token": csrfToken };
  if (body !== undefined) headers["Content-Type"] = "application/json";

  try {
    const response = await request(path, {
      method,
      credentials: "same-origin",
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (response.status === 409) return "conflict";
    return response.ok ? "ok" : "error";
  } catch {
    return "error";
  }
}

export function CategoryCreateForm() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;

    const normalizedName = name.trim();
    if (!normalizedName) {
      setError("Informe um nome para a categoria.");
      return;
    }

    setPending(true);
    setError(null);
    const result = await performCategoryMutation(
      "/api/categories",
      "POST",
      { name: normalizedName },
    );
    setPending(false);

    if (result === "conflict") {
      setError("Já existe uma categoria com esse nome.");
      return;
    }
    if (result !== "ok") {
      setError("Não foi possível criar a categoria.");
      return;
    }

    setName("");
    router.refresh();
  }

  return (
    <form className="mt-8 max-w-2xl rounded-2xl border border-border bg-surface p-5 shadow-[0_12px_30px_rgba(32,37,34,0.06)] sm:p-6" onSubmit={submit}>
      <label className="block text-sm font-semibold text-foreground" htmlFor="category-name">Nova categoria</label>
      <div className="mt-3 flex flex-col gap-3 sm:flex-row">
        <input
          className="min-h-12 min-w-0 flex-1 rounded-xl border border-border bg-surface px-4 text-base text-foreground"
          disabled={pending}
          id="category-name"
          name="name"
          onChange={(event) => setName(event.target.value)}
          placeholder="Ex.: Hardware"
          value={name}
        />
        <button className="min-h-12 rounded-xl bg-primary px-5 py-3 text-sm font-semibold text-white hover:bg-[#1f452f] disabled:cursor-not-allowed disabled:opacity-60" disabled={pending} type="submit">
          {pending ? "Criando…" : "Criar categoria"}
        </button>
      </div>
      {error ? <p className="mt-3 text-sm font-medium text-danger" role="alert">{error}</p> : null}
    </form>
  );
}

type CategoryDetailActionsProps = {
  categoryId: number;
  name: string;
  reelCount: number;
};

export function CategoryDetailActions({ categoryId, name, reelCount }: CategoryDetailActionsProps) {
  const router = useRouter();
  const [nextName, setNextName] = useState(name);
  const [pending, setPending] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function rename(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;

    const normalizedName = nextName.trim();
    if (!normalizedName) {
      setError("Informe um nome para a categoria.");
      return;
    }

    setPending(true);
    setError(null);
    const result = await performCategoryMutation(
      "/api/categories/" + categoryId,
      "PATCH",
      { name: normalizedName },
    );
    setPending(false);

    if (result === "conflict") {
      setError("Já existe uma categoria com esse nome.");
      return;
    }
    if (result !== "ok") {
      setError("Não foi possível renomear a categoria.");
      return;
    }

    setNextName(normalizedName);
    router.refresh();
  }

  async function remove() {
    if (pending) return;
    setPending(true);
    setError(null);
    const result = await performCategoryMutation(
      "/api/categories/" + categoryId,
      "DELETE",
      undefined,
    );
    setPending(false);

    if (result !== "ok") {
      setError("Não foi possível excluir a categoria.");
      return;
    }

    router.push("/categories");
    router.refresh();
  }

  return (
    <section aria-labelledby="category-actions-title" className="mt-8 rounded-2xl border border-border bg-surface p-5 shadow-[0_12px_30px_rgba(32,37,34,0.06)] sm:p-6">
      <h2 className="text-xl font-semibold tracking-tight text-foreground" id="category-actions-title">Gerenciar categoria</h2>
      {error ? <p className="mt-3 text-sm font-medium text-danger" role="alert">{error}</p> : null}

      <form className="mt-5" onSubmit={rename}>
        <label className="block text-sm font-semibold text-foreground" htmlFor="rename-category">Nome</label>
        <div className="mt-3 flex flex-col gap-3 sm:flex-row">
          <input
            className="min-h-11 min-w-0 flex-1 rounded-xl border border-border bg-surface px-3 text-base text-foreground"
            disabled={pending}
            id="rename-category"
            onChange={(event) => setNextName(event.target.value)}
            value={nextName}
          />
          <button className="min-h-11 rounded-xl border border-border px-4 py-2 text-sm font-semibold text-primary hover:bg-accent disabled:cursor-not-allowed disabled:opacity-60" disabled={pending} type="submit">
            {pending ? "Salvando…" : "Renomear"}
          </button>
        </div>
      </form>

      <div className="mt-6 border-t border-border pt-5">
        {!confirmDelete ? (
          <button className="min-h-11 rounded-xl border border-danger/40 px-4 py-2 text-sm font-semibold text-danger hover:bg-danger/5 disabled:cursor-not-allowed disabled:opacity-60" disabled={pending} onClick={() => setConfirmDelete(true)} type="button">
            Excluir categoria
          </button>
        ) : (
          <div>
            <p className="text-sm leading-6 text-muted">
              {reelCount === 0
                ? "Esta categoria não possui Reels."
                : "A categoria será removida de " + reelCount + " " + (reelCount === 1 ? "Reel" : "Reels") + ". Os Reels não serão excluídos."}
            </p>
            <div className="mt-4 flex flex-wrap gap-3">
              <button className="min-h-11 rounded-xl border border-border px-4 py-2 text-sm font-semibold text-primary hover:bg-accent" disabled={pending} onClick={() => setConfirmDelete(false)} type="button">Cancelar</button>
              <button className="min-h-11 rounded-xl bg-danger px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60" disabled={pending} onClick={() => void remove()} type="button">
                {pending ? "Excluindo…" : "Excluir categoria"}
              </button>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
