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
type NewReelDispatchState = "accepted" | "unconfirmed";

type ReelFields = {
  id: number;
  shortcode: string;
  original_url: string;
  download_status: DownloadStatus;
  curation_status: CurationStatus;
  transcription_status: TranscriptionStatus;
};

export type NewlyCreatedReel = ReelFields & {
  created: true;
  download_status: "received";
  curation_status: "inbox";
  transcription_status: "not_requested";
};

export type ExistingReel = ReelFields & {
  created: false;
};

export type CreatedReel = NewlyCreatedReel | ExistingReel;

export type ReelCreationSuccess =
  | {
      ok: true;
      reel: NewlyCreatedReel;
      dispatch: { state: NewReelDispatchState };
    }
  | {
      ok: true;
      reel: ExistingReel;
      dispatch: { state: ReelDispatchState };
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

const REEL_KEYS = [
  "id",
  "shortcode",
  "original_url",
  "download_status",
  "curation_status",
  "transcription_status",
  "created",
] as const;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function hasExactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const valueKeys = Object.keys(value);
  return valueKeys.length === keys.length && valueKeys.every((key) => keys.includes(key));
}

function isDispatchState(value: unknown): value is ReelDispatchState {
  return typeof value === "string" && REEL_DISPATCH_STATES.includes(value as ReelDispatchState);
}

function isNewReelDispatchState(value: ReelDispatchState): value is NewReelDispatchState {
  return value === "accepted" || value === "unconfirmed";
}

function isCreatedReel(value: unknown): value is CreatedReel {
  if (!isRecord(value) || !hasExactKeys(value, REEL_KEYS)) return false;

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

function isNewlyCreatedReel(value: CreatedReel): value is NewlyCreatedReel {
  return value.created
    && value.download_status === "received"
    && value.curation_status === "inbox"
    && value.transcription_status === "not_requested";
}

function isSuccessPayload(value: unknown): value is Omit<ReelCreationSuccess, "ok"> {
  if (!isRecord(value) || !hasExactKeys(value, ["reel", "dispatch"]) || !isCreatedReel(value.reel)) {
    return false;
  }
  if (!isRecord(value.dispatch) || !hasExactKeys(value.dispatch, ["state"]) || !isDispatchState(value.dispatch.state)) {
    return false;
  }

  return !value.reel.created || (
    isNewlyCreatedReel(value.reel) && isNewReelDispatchState(value.dispatch.state)
  );
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

    if (payload.reel.created) {
      if (!isNewlyCreatedReel(payload.reel) || !isNewReelDispatchState(payload.dispatch.state)) {
        return { ok: false, code: "invalid_response" };
      }
      return {
        ok: true,
        reel: payload.reel,
        dispatch: { state: payload.dispatch.state },
      };
    }

    return {
      ok: true,
      reel: payload.reel,
      dispatch: { state: payload.dispatch.state },
    };
  } catch {
    return { ok: false, code: "network_error" };
  }
}
