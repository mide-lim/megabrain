from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import UUID


@dataclass(frozen=True, slots=True)
class TranscriptionResult:
    transcript_text: str
    transcript_language: str | None
    provider: str
    model: str
    provider_request_id: str | None


@dataclass(frozen=True, slots=True)
class BatchSubmissionResult:
    """A submitted provider operation that has not reached a terminal state."""

    provider: str
    model: str
    provider_request_id: str
    state: Literal["processing"]


@dataclass(frozen=True, slots=True)
class BatchReconciliationResult:
    """The result of one exact known BatchRecognize operation lookup."""

    state: Literal["pending", "terminal_success", "terminal_provider_failure"]
    provider: str
    model: str
    provider_request_id: str
    transcript_text: str | None
    transcript_language: str | None


class SynchronousRecognitionUnsupportedError(RuntimeError):
    """The audio cannot be processed with synchronous Recognize."""

    error_code = "STT_SYNC_RECOGNIZE_UNSUPPORTED"
    stage = "transcription"
    retryable = False


class SpeechToTextError(RuntimeError):
    """A stable, sanitized transcription provider failure."""

    stage = "transcription"

    def __init__(self, error_code: str, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.retryable = retryable


class ReconciliationError(RuntimeError):
    """A sanitized control-plane failure while reading a known Batch operation."""

    stage = "transcription"

    def __init__(self, error_code: str, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.retryable = retryable


class SpeechToTextAdapter(ABC):
    @abstractmethod
    def transcribe(
        self,
        audio_path: Path,
        *,
        language_hint: str | None = None,
        duration_seconds: float | None = None,
        attempt_id: UUID | str | None = None,
    ) -> TranscriptionResult | BatchSubmissionResult:
        """Transcribe or submit one local audio file into a provider-neutral result."""
