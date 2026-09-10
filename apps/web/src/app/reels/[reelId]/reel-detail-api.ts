import { headers } from "next/headers";

export type ReelCategory = {
  id: number;
  name: string;
};

export type ReelDetail = {
  id: number;
  title: string | null;
  creator: string | null;
  shortcode: string | null;
  original_url: string | null;
  status: string | null;
  caption: string | null;
  duration_seconds: number | null;
  received_at: string | null;
  downloaded_at: string | null;
  filename: string | null;
  mime_type: string | null;
  file_size_bytes: number | null;
  transcript: {
    available: boolean;
    text: string | null;
    language: string | null;
    completed_at: string | null;
  };
  categories: {
    assigned: ReelCategory[];
    available: ReelCategory[];
  };
  video: {
    available: boolean;
    src: string | null;
  };
};

export type ReelDetailFetchResult =
  | { kind: "ok"; reel: ReelDetail }
  | { kind: "not-found" }
  | { kind: "unavailable" };

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

function isCategory(value: unknown): value is ReelCategory {
  return isRecord(value) && Number.isSafeInteger(value.id) && typeof value.name === "string";
}

function isReelDetail(value: unknown): value is ReelDetail {
  if (!isRecord(value) || !isRecord(value.transcript) || !isRecord(value.categories) || !isRecord(value.video)) {
    return false;
  }

  const transcript = value.transcript;
  const categories = value.categories;
  const video = value.video;
  return (
    Number.isSafeInteger(value.id) &&
    isNullableString(value.title) &&
    isNullableString(value.creator) &&
    isNullableString(value.shortcode) &&
    isNullableString(value.original_url) &&
    isNullableString(value.status) &&
    isNullableString(value.caption) &&
    isNullableNumber(value.duration_seconds) &&
    isNullableString(value.received_at) &&
    isNullableString(value.downloaded_at) &&
    isNullableString(value.filename) &&
    isNullableString(value.mime_type) &&
    isNullableNumber(value.file_size_bytes) &&
    typeof transcript.available === "boolean" &&
    isNullableString(transcript.text) &&
    isNullableString(transcript.language) &&
    isNullableString(transcript.completed_at) &&
    Array.isArray(categories.assigned) &&
    categories.assigned.every(isCategory) &&
    Array.isArray(categories.available) &&
    categories.available.every(isCategory) &&
    typeof video.available === "boolean" &&
    (video.available
      ? video.src === `/api/reels/${value.id}/video`
      : video.src === null)
  );
}

export async function fetchReelDetail(
  reelId: number,
  request: typeof fetch = fetch,
  incomingHeaders?: Headers,
): Promise<ReelDetailFetchResult> {
  try {
    const requestHeaders = incomingHeaders ?? (await headers());
    const response = await request(new URL(`/api/reels/${reelId}`, apiBaseUrl()), {
      cache: "no-store",
      headers: {
        accept: "application/json",
        cookie: requestHeaders.get("cookie") ?? "",
      },
    });

    if (response.status === 404) {
      return { kind: "not-found" };
    }
    if (!response.ok) {
      return { kind: "unavailable" };
    }

    const payload: unknown = await response.json();
    return isReelDetail(payload) ? { kind: "ok", reel: payload } : { kind: "unavailable" };
  } catch {
    return { kind: "unavailable" };
  }
}
