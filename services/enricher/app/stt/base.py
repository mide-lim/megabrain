from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class TranscriptionResult:
    transcript_text: str
    transcript_language: str | None
    provider: str
    model: str
    provider_request_id: str | None


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


class SpeechToTextAdapter(ABC):
    @abstractmethod
    def transcribe(
        self,
        audio_path: Path,
        *,
        language_hint: str | None = None,
        duration_seconds: float | None = None,
    ) -> TranscriptionResult:
        """Transcribe one local audio file into a provider-neutral result."""
