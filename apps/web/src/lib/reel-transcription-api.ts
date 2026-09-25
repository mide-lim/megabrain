import { fetchCsrfToken } from "./csrf-client";
import { isReelLifecycleProjection, type ReelLifecycleProjection } from "./reel-lifecycle";

export async function requestReelTranscription(
  reelId: number,
  request: typeof fetch = fetch,
): Promise<ReelLifecycleProjection | null> {
  const csrfToken = await fetchCsrfToken(request);
  if (csrfToken === null) {
    return null;
  }

  try {
    const response = await request(`/api/reels/${reelId}/transcription`, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrfToken,
      },
      body: "{}",
    });
    const payload: unknown = await response.json().catch(() => null);
    if ((response.status !== 200 && response.status !== 202) || !isReelLifecycleProjection(payload) || payload.id !== reelId) {
      return null;
    }
    return payload;
  } catch {
    return null;
  }
}
