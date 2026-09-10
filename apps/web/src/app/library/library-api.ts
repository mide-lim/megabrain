import { headers } from "next/headers";

export type ReelLibraryItem = {
  id: number;
  title: string | null;
  creator: string | null;
  shortcode: string | null;
  caption: string | null;
  categories: string[];
  duration_seconds: number | null;
  received_at: string | null;
  has_transcript: boolean;
};

export type LibraryResponse = {
  items: ReelLibraryItem[];
  query: { q: string };
  pagination: {
    page: number;
    page_size: number;
    has_previous: boolean;
    has_next: boolean;
  };
};

type LibraryRequest = {
  page: number;
  q: string;
};

function apiBaseUrl(): string {
  return process.env.MEGABRAIN_API_INTERNAL_URL ?? "http://web:8000";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isNullableString(value: unknown): value is string | null {
  return typeof value === "string" || value === null;
}

function isNullableNumber(value: unknown): value is number | null {
  return (typeof value === "number" && Number.isFinite(value)) || value === null;
}

function isLibraryItem(value: unknown): value is ReelLibraryItem {
  if (!isRecord(value)) {
    return false;
  }

  return (
    Number.isSafeInteger(value.id) &&
    isNullableString(value.title) &&
    isNullableString(value.creator) &&
    isNullableString(value.shortcode) &&
    isNullableString(value.caption) &&
    Array.isArray(value.categories) &&
    value.categories.every((category) => typeof category === "string") &&
    isNullableNumber(value.duration_seconds) &&
    isNullableString(value.received_at) &&
    typeof value.has_transcript === "boolean"
  );
}

function isLibraryResponse(value: unknown): value is LibraryResponse {
  if (!isRecord(value) || !Array.isArray(value.items) || !isRecord(value.query) || !isRecord(value.pagination)) {
    return false;
  }

  return (
    value.items.every(isLibraryItem) &&
    typeof value.query.q === "string" &&
    Number.isSafeInteger(value.pagination.page) &&
    Number.isSafeInteger(value.pagination.page_size) &&
    typeof value.pagination.has_previous === "boolean" &&
    typeof value.pagination.has_next === "boolean"
  );
}

export function buildLibraryUrl({ page, q }: LibraryRequest): string {
  const params = new URLSearchParams();
  if (page > 1) {
    params.set("page", String(page));
  }
  if (q) {
    params.set("q", q);
  }

  const query = params.toString();
  return query ? `/library?${query}` : "/library";
}

export async function fetchLibraryPage(
  { page, q }: LibraryRequest,
  request: typeof fetch = fetch,
  incomingHeaders?: Headers,
): Promise<LibraryResponse | null> {
  const url = new URL("/api/reels", apiBaseUrl());
  url.searchParams.set("page", String(page));
  if (q) {
    url.searchParams.set("q", q);
  }

  try {
    const requestHeaders = incomingHeaders ?? (await headers());
    const response = await request(url, {
      cache: "no-store",
      headers: {
        accept: "application/json",
        cookie: requestHeaders.get("cookie") ?? "",
      },
    });
    if (!response.ok) {
      return null;
    }

    const payload: unknown = await response.json();
    return isLibraryResponse(payload) ? payload : null;
  } catch {
    return null;
  }
}
