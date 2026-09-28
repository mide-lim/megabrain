import type { LibraryResponse } from "../library/library-api";
import { fetchLibraryPage } from "../library/library-api";

export function buildInboxUrl(page: number): string {
  return page > 1 ? "/inbox?page=" + page : "/inbox";
}

export async function fetchInboxPage(
  page: number,
  request: typeof fetch = fetch,
  incomingHeaders?: Headers,
): Promise<LibraryResponse | null> {
  return fetchLibraryPage(
    { page, q: "", curationStatus: "inbox" },
    request,
    incomingHeaders,
  );
}
