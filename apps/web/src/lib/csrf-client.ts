function isCsrfPayload(value: unknown): value is { csrf_token: string } {
  return typeof value === "object" && value !== null && typeof (value as { csrf_token?: unknown }).csrf_token === "string";
}

export async function fetchCsrfToken(request: typeof fetch = fetch): Promise<string | null> {
  try {
    const response = await request("/api/auth/csrf", {
      cache: "no-store",
      credentials: "same-origin",
      headers: { accept: "application/json" },
    });
    const payload: unknown = await response.json().catch(() => null);
    return response.ok && isCsrfPayload(payload) ? payload.csrf_token : null;
  } catch {
    return null;
  }
}
