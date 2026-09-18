import { fetchCsrfToken } from "./csrf-client";
import {
  isCurationStatus,
  isDownloadStatus,
  isTranscriptionStatus,
  type CurationStatus,
  type DownloadStatus,
  type TranscriptionStatus,
} from "./reel-lifecycle";

export const REEL_DISPATCH_STATES = ["accepted", "not_required", "unconfirmed"] as const;

export type ReelDispatchState = (typeof REEL_DISPATCH_STATES)[number];

export type CreatedReel = {
  id: number;
  shortcode: string;
  original_url: string;
  download_status: DownloadStatus;
  curation_status: CurationStatus;
  transcription_status: TranscriptionStatus;
  created: boolean;
};

export type ReelCreationSuccess = {
  ok: true;
  reel: CreatedReel;
  dispatch: {
    state: ReelDispatchState;
  };
};

export type ReelCreationErrorCode =
  | "invalid_request"
  | "identity_conflict"
  | "registration_unavailable"
  | "dispatch_unavailable"
  | "session_unavailable"
  | "csrf_unavailable"
  | "network_error"
  | "invalid_response";

export type ReelCreationFailure = {
  ok: false;
  code: ReelCreationErrorCode;
};

export type ReelCreationResult = ReelCreationSuccess | ReelCreationFailure;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isDispatchState(value: unknown): value is ReelDispatchState {
  return typeof value === "string" && REEL_DISPATCH_STATES.includes(value as ReelDispatchState);
}

function isCreatedReel(value: unknown): value is CreatedReel {
  if (!isRecord(value)) return false;

  return (
    Number.isSafeInteger(value.id)
    && Number(value.id) > 0
    && typeof value.shortcode === "string"
    && value.shortcode.length > 0
    && typeof value.original_url === "string"
    && value.original_url.length > 0
    && isDownloadStatus(value.download_status)
    && isCurationStatus(value.curation_status)
    && isTranscriptionStatus(value.transcription_status)
    && typeof value.created === "boolean"
  );
}

function isSuccessPayload(value: unknown): value is Omit<ReelCreationSuccess, "ok"> {
  if (!isRecord(value) || !isCreatedReel(value.reel) || !isRecord(value.dispatch)) {
    return false;
  }
  return isDispatchState(value.dispatch.state);
}

function errorCodeFromResponse(status: number, payload: unknown): ReelCreationErrorCode {
  if (status === 401) return "session_unavailable";
  if (status === 403) return "csrf_unavailable";
  if (status === 409) return "identity_conflict";
  if (status === 422) return "invalid_request";

  if (status === 503 && isRecord(payload) && isRecord(payload.error)) {
    if (payload.error.code === "registration_unavailable") {
      return "registration_unavailable";
    }
    if (payload.error.code === "reel_dispatch_unavailable") {
      return "dispatch_unavailable";
    }
  }

  return "invalid_response";
}

export async function performReelCreation(
  rawUrl: string,
  request: typeof fetch = fetch,
): Promise<ReelCreationResult> {
  const url = rawUrl.trim();

  if (!url) {
    return { ok: false, code: "invalid_request" };
  }

  const csrfToken = await fetchCsrfToken(request);
  if (csrfToken === null) {
    return { ok: false, code: "csrf_unavailable" };
  }

  try {
    const response = await request("/api/reels", {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrfToken,
        accept: "application/json",
      },
      body: JSON.stringify({ url }),
    });

    const payload: unknown = await response.json().catch(() => null);

    if (!response.ok) {
      return { ok: false, code: errorCodeFromResponse(response.status, payload) };
    }

    if ((response.status !== 200 && response.status !== 201) || !isSuccessPayload(payload)) {
      return { ok: false, code: "invalid_response" };
    }

    if ((payload.reel.created && response.status !== 201) || (!payload.reel.created && response.status !== 200)) {
      return { ok: false, code: "invalid_response" };
    }

    return {
      ok: true,
      reel: payload.reel,
      dispatch: payload.dispatch,
    };
  } catch {
    return { ok: false, code: "network_error" };
  }
}
