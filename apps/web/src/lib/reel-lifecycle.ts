export const DOWNLOAD_STATUSES = ["received", "downloading", "downloaded", "failed"] as const;
export const CURATION_STATUSES = ["inbox", "organized"] as const;
export const TRANSCRIPTION_STATUSES = ["not_requested", "queued", "processing", "completed", "failed"] as const;

export type DownloadStatus = (typeof DOWNLOAD_STATUSES)[number];
export type CurationStatus = (typeof CURATION_STATUSES)[number];
export type TranscriptionStatus = (typeof TRANSCRIPTION_STATUSES)[number];

export type ReelLifecycleProjection = {
  id: number;
  download_status: DownloadStatus;
  curation_status: CurationStatus;
  transcription_status: TranscriptionStatus;
};

function isOneOf<T extends readonly string[]>(value: unknown, values: T): value is T[number] {
  return typeof value === "string" && values.includes(value);
}

export function isDownloadStatus(value: unknown): value is DownloadStatus {
  return isOneOf(value, DOWNLOAD_STATUSES);
}

export function isCurationStatus(value: unknown): value is CurationStatus {
  return isOneOf(value, CURATION_STATUSES);
}

export function isTranscriptionStatus(value: unknown): value is TranscriptionStatus {
  return isOneOf(value, TRANSCRIPTION_STATUSES);
}

export function lifecycleKey(lifecycle: ReelLifecycleProjection): string {
  return `${lifecycle.id}:${lifecycle.download_status}:${lifecycle.curation_status}:${lifecycle.transcription_status}`;
}

export function isReelLifecycleProjection(value: unknown): value is ReelLifecycleProjection {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const projection = value as Record<string, unknown>;
  return (
    Number.isSafeInteger(projection.id)
    && isDownloadStatus(projection.download_status)
    && isCurationStatus(projection.curation_status)
    && isTranscriptionStatus(projection.transcription_status)
  );
}
