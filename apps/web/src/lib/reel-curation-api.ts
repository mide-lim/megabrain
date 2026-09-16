import { fetchCsrfToken } from "./csrf-client";
import {
  isReelLifecycleProjection,
  type CurationStatus,
  type ReelLifecycleProjection,
} from "./reel-lifecycle";

export type { ReelLifecycleProjection } from "./reel-lifecycle";

export async function performCurationMutation(
  reelId: number,
  curation_status: CurationStatus,
  request: typeof fetch = fetch,
): Promise<ReelLifecycleProjection | null> {
  const csrfToken = await fetchCsrfToken(request);
  if (csrfToken === null) {
    return null;
  }

  try {
    const response = await request(`/api/reels/${reelId}/curation`, {
      method: "PATCH",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrfToken,
      },
      body: JSON.stringify({ curation_status }),
    });
    if (!response.ok) {
      return null;
    }

    const payload: unknown = await response.json().catch(() => null);
    return isReelLifecycleProjection(payload) && payload.id === reelId ? payload : null;
  } catch {
    return null;
  }
}

export function reconcileLifecycleProjection(
  confirmed: ReelLifecycleProjection,
  response: ReelLifecycleProjection | null,
): ReelLifecycleProjection {
  return response ?? confirmed;
}
