from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class TemporaryAudioObject:
    bucket: str
    object_name: str
    uri: str
    generation: str


class TemporaryAudioStoreError(RuntimeError):
    """A stable, sanitized temporary audio transport failure."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


class GoogleTemporaryAudioStore:
    """Bounded GCS transport for one normalized BatchRecognize WAV input."""

    def __init__(self, *, bucket: str, client: Any | None = None) -> None:
        self._bucket_name = bucket.strip()
        self._client = client

    @property
    def configured(self) -> bool:
        return bool(self._bucket_name)

    def _get_client(self) -> Any:
        if self._client is None:
            from google.cloud import storage

            self._client = storage.Client()
        return self._client

    def upload(self, *, attempt_id: object, path: Path) -> TemporaryAudioObject:
        if not self.configured:
            raise TemporaryAudioStoreError(
                "STT_BATCH_CONFIGURATION_REQUIRED",
                "Batch transcription requires temporary storage configuration",
            )

        object_name = f"f6/transcription/{attempt_id}/audio.wav"
        try:
            blob = self._get_client().bucket(self._bucket_name).blob(object_name)
            blob.upload_from_filename(
                str(path),
                content_type="audio/wav",
                if_generation_match=0,
            )
        except Exception as error:  # noqa: BLE001 - storage SDK failures vary.
            if self._is_precondition_failure(error):
                raise TemporaryAudioStoreError(
                    "STT_BATCH_OBJECT_CONFLICT",
                    "Temporary transcription audio object already exists",
                ) from None
            raise TemporaryAudioStoreError(
                "STT_FAILED", "Temporary transcription audio upload failed"
            ) from None

        generation = getattr(blob, "generation", None)
        if generation is None:
            raise TemporaryAudioStoreError(
                "STT_FAILED", "Temporary transcription audio upload failed"
            )
        return TemporaryAudioObject(
            bucket=self._bucket_name,
            object_name=object_name,
            uri=f"gs://{self._bucket_name}/{object_name}",
            generation=str(generation),
        )

    @staticmethod
    def _is_precondition_failure(error: Exception) -> bool:
        from google.api_core import exceptions as google_errors

        return isinstance(error, google_errors.PreconditionFailed)
