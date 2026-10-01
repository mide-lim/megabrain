import { headers } from "next/headers";

type PaperclipStatusResponse = {
  available: boolean;
};

function apiBaseUrl(): string {
  return process.env.MEGABRAIN_API_INTERNAL_URL ?? "http://web:8000";
}

function isPaperclipStatusResponse(value: unknown): value is PaperclipStatusResponse {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as Record<string, unknown>).available === "boolean"
  );
}

export async function fetchPaperclipAvailability(
  request: typeof fetch = fetch,
  incomingHeaders?: Headers,
): Promise<boolean> {
  try {
    const requestHeaders = incomingHeaders ?? (await headers());
    const response = await request(
      new URL("/api/platform/paperclip/status", apiBaseUrl()),
      {
        cache: "no-store",
        headers: {
          accept: "application/json",
          cookie: requestHeaders.get("cookie") ?? "",
        },
      },
    );
    if (!response.ok) {
      return false;
    }

    const payload: unknown = await response.json();
    return isPaperclipStatusResponse(payload) && payload.available;
  } catch {
    return false;
  }
}
