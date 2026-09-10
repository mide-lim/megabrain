import { headers } from "next/headers";
import { redirect } from "next/navigation";

export type OwnerSession = {
  email: string;
};

type SessionBootstrapResponse = {
  authenticated: true;
  user: {
    email: string;
  };
};

function apiBaseUrl(): string {
  return process.env.MEGABRAIN_API_INTERNAL_URL ?? "http://web:8000";
}

function isOwnerSessionPayload(value: unknown): value is SessionBootstrapResponse {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const payload = value as Record<string, unknown>;
  if (payload.authenticated !== true || typeof payload.user !== "object" || payload.user === null) {
    return false;
  }

  const user = payload.user as Record<string, unknown>;
  return typeof user.email === "string" && user.email.length > 0;
}

export async function getOwnerSession(
  incomingHeaders?: Headers,
  request: typeof fetch = fetch,
): Promise<OwnerSession | null> {
  const requestHeaders = incomingHeaders ?? (await headers());

  try {
    const response = await request(new URL("/api/auth/session", apiBaseUrl()), {
      cache: "no-store",
      headers: {
        accept: "application/json",
        cookie: requestHeaders.get("cookie") ?? "",
      },
    });

    if (response.status === 401 || !response.ok) {
      return null;
    }

    const payload: unknown = await response.json();
    return isOwnerSessionPayload(payload) ? { email: payload.user.email } : null;
  } catch {
    return null;
  }
}

export async function requireOwnerSession(): Promise<OwnerSession> {
  const session = await getOwnerSession();
  if (session === null) {
    redirect("/login");
  }
  return session;
}
