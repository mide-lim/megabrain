from __future__ import annotations

DOWNLOAD_STATUS_RECEIVED = "received"
DOWNLOAD_STATUS_DOWNLOADING = "downloading"
DOWNLOAD_STATUS_DOWNLOADED = "downloaded"
DOWNLOAD_STATUS_FAILED = "failed"

CURATION_STATUS_INBOX = "inbox"
CURATION_STATUS_ORGANIZED = "organized"

TRANSCRIPTION_STATUS_NOT_REQUESTED = "not_requested"
TRANSCRIPTION_STATUS_QUEUED = "queued"
TRANSCRIPTION_STATUS_PROCESSING = "processing"
TRANSCRIPTION_STATUS_COMPLETED = "completed"
TRANSCRIPTION_STATUS_FAILED = "failed"

DOWNLOAD_STATUSES = frozenset(
    {
        DOWNLOAD_STATUS_RECEIVED,
        DOWNLOAD_STATUS_DOWNLOADING,
        DOWNLOAD_STATUS_DOWNLOADED,
        DOWNLOAD_STATUS_FAILED,
    }
)
CURATION_STATUSES = frozenset({CURATION_STATUS_INBOX, CURATION_STATUS_ORGANIZED})
TRANSCRIPTION_STATUSES = frozenset(
    {
        TRANSCRIPTION_STATUS_NOT_REQUESTED,
        TRANSCRIPTION_STATUS_QUEUED,
        TRANSCRIPTION_STATUS_PROCESSING,
        TRANSCRIPTION_STATUS_COMPLETED,
        TRANSCRIPTION_STATUS_FAILED,
    }
)

class LifecycleStatusError(ValueError):
    """Raised when a lifecycle state is outside its approved vocabulary."""


def _validate(value: str, allowed: frozenset[str], dimension: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise LifecycleStatusError(f"Unsupported {dimension} status")
    return value


def validate_download_status(value: str) -> str:
    return _validate(value, DOWNLOAD_STATUSES, "download")


def validate_curation_status(value: str) -> str:
    return _validate(value, CURATION_STATUSES, "curation")


def validate_transcription_status(value: str) -> str:
    return _validate(value, TRANSCRIPTION_STATUSES, "transcription")


def default_reel_lifecycle() -> dict[str, str]:
    """Return the conservative lifecycle fields for a newly persisted Reel."""
    return {
        "download_status": DOWNLOAD_STATUS_RECEIVED,
        "curation_status": CURATION_STATUS_INBOX,
        "transcription_status": TRANSCRIPTION_STATUS_NOT_REQUESTED,
    }
