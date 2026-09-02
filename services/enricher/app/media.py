from __future__ import annotations

import json
import re
import subprocess
import tempfile
import wave
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ErrorStage(str, Enum):
    INPUT = "input"
    R2_DOWNLOAD = "r2_download"
    INTEGRITY = "integrity"
    PROBE = "probe"
    AUDIO_EXTRACT = "audio_extract"
    TRANSCRIPTION = "transcription"
    INTERNAL = "internal"


class ErrorResponse(StrictModel):
    error_code: str
    stage: ErrorStage
    message: str
    retryable: bool
    attempt_id: UUID | None


class EnrichmentRequest(StrictModel):
    contract_version: str = Field(min_length=1)
    attempt_id: UUID
    reel_id: int = Field(gt=0, le=9_223_372_036_854_775_807)
    shortcode: str
    object_key: str = Field(min_length=1)
    expected_sha256: str
    expected_size_bytes: int | None = Field(
        default=None,
        gt=0,
        le=9_223_372_036_854_775_807,
    )
    pipeline_version: str = Field(min_length=1)
    language_hint: str | None = Field(default=None, min_length=1)

    @field_validator("shortcode")
    @classmethod
    def validate_shortcode(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise ValueError("Invalid shortcode")
        return value

    @field_validator("expected_sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError(
                "expected_sha256 must be 64 lowercase hexadecimal characters"
            )
        return value


class SourceMetadata(StrictModel):
    object_key: str
    sha256: str
    size_bytes: int = Field(gt=0)


class VideoMetadata(StrictModel):
    codec: str
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class AudioMetadata(StrictModel):
    codec: str
    sample_rate_hz: int = Field(gt=0)
    channels: int = Field(gt=0)
    duration_seconds: float | None = Field(default=None, ge=0)


class MediaMetadata(StrictModel):
    container_format: str
    duration_seconds: float = Field(ge=0)
    video: VideoMetadata
    audio: AudioMetadata | None


class TranscriptionInput(StrictModel):
    format: str
    sample_rate_hz: int = Field(gt=0)
    channels: int = Field(gt=0)
    duration_seconds: float = Field(ge=0)


class TranscriptionEngine(StrictModel):
    provider: str | None
    model: str | None
    request_id: str | None


class Transcription(StrictModel):
    outcome: Literal["transcribed", "no_audio", "empty_transcript"]
    transcript_text: str | None
    transcript_language: str | None
    engine: TranscriptionEngine


class ProcessingMetadata(StrictModel):
    started_at: datetime
    completed_at: datetime


class EnrichmentResponse(StrictModel):
    contract_version: str
    attempt_id: UUID
    reel_id: int
    shortcode: str
    pipeline_version: str
    processor_version: str
    source: SourceMetadata
    media: MediaMetadata
    transcription_input: TranscriptionInput | None
    transcription: Transcription
    processing: ProcessingMetadata
    warnings: list[str]


class MediaProcessingError(RuntimeError):
    """A stable, sanitized failure raised by local media processing."""

    def __init__(
        self,
        *,
        error_code: str,
        stage: ErrorStage,
        message: str,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.stage = stage
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class ExtractedAudio:
    path: Path
    metadata: TranscriptionInput


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


def _media_error(
    error_code: str,
    stage: ErrorStage,
    message: str,
) -> MediaProcessingError:
    return MediaProcessingError(
        error_code=error_code,
        stage=stage,
        message=message,
    )


def _positive_int(value: object) -> int:
    if isinstance(value, bool):
        raise TypeError
    parsed = int(str(value))
    if parsed <= 0:
        raise ValueError
    return parsed


def _non_negative_float(value: object) -> float:
    parsed = float(str(value))
    if parsed < 0:
        raise ValueError
    return parsed


def _container_name(format_name: object) -> str:
    names = {part.strip() for part in str(format_name).split(",")}
    if names.intersection({"mp4", "mov"}):
        return "mp4"
    name = next((part for part in names if part), "")
    if not name:
        raise ValueError
    return name


def _normalize_probe(payload: object) -> MediaMetadata:
    if not isinstance(payload, dict):
        raise TypeError
    raw_format = payload.get("format")
    streams = payload.get("streams")
    if not isinstance(raw_format, dict) or not isinstance(streams, list):
        raise TypeError

    video_stream = next(
        (
            stream
            for stream in streams
            if isinstance(stream, dict) and stream.get("codec_type") == "video"
        ),
        None,
    )
    if video_stream is None:
        raise ValueError
    audio_stream = next(
        (
            stream
            for stream in streams
            if isinstance(stream, dict) and stream.get("codec_type") == "audio"
        ),
        None,
    )

    duration = raw_format.get("duration")
    if duration is None:
        duration = video_stream.get("duration")
    audio = None
    if audio_stream is not None:
        audio_duration = audio_stream.get("duration")
        audio = AudioMetadata(
            codec=str(audio_stream["codec_name"]),
            sample_rate_hz=_positive_int(audio_stream["sample_rate"]),
            channels=_positive_int(audio_stream["channels"]),
            duration_seconds=(
                _non_negative_float(audio_duration)
                if audio_duration not in (None, "N/A")
                else None
            ),
        )

    return MediaMetadata(
        container_format=_container_name(raw_format.get("format_name")),
        duration_seconds=_non_negative_float(duration),
        video=VideoMetadata(
            codec=str(video_stream["codec_name"]),
            width=_positive_int(video_stream["width"]),
            height=_positive_int(video_stream["height"]),
        ),
        audio=audio,
    )


def probe_media(
    media_path: Path,
    *,
    timeout_seconds: float = 30,
    runner: CommandRunner = subprocess.run,
) -> MediaMetadata:
    argv = [
        "ffprobe",
        "-v",
        "error",
        "-show_format",
        "-show_streams",
        "-of",
        "json",
        str(media_path),
    ]
    try:
        completed = runner(
            argv,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        return _normalize_probe(json.loads(completed.stdout))
    except (
        OSError,
        subprocess.SubprocessError,
        json.JSONDecodeError,
        ValueError,
        KeyError,
        TypeError,
    ):
        raise _media_error(
            "PROBE_FAILED",
            ErrorStage.PROBE,
            "Media probe failed",
        ) from None


def extract_audio(
    media_path: Path,
    output_path: Path,
    *,
    timeout_seconds: float = 60,
    runner: CommandRunner = subprocess.run,
) -> TranscriptionInput:
    argv = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(media_path),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ac",
        "1",
        "-y",
        str(output_path),
    ]
    try:
        runner(
            argv,
            check=True,
            capture_output=True,
            timeout=timeout_seconds,
        )
        with wave.open(str(output_path), "rb") as wav:
            channels = wav.getnchannels()
            sample_width = wav.getsampwidth()
            sample_rate = wav.getframerate()
            frame_count = wav.getnframes()
        if channels != 1 or sample_width != 2 or sample_rate <= 0:
            raise ValueError
        return TranscriptionInput(
            format="wav",
            sample_rate_hz=sample_rate,
            channels=channels,
            duration_seconds=frame_count / sample_rate,
        )
    except (OSError, subprocess.SubprocessError, ValueError, wave.Error):
        raise _media_error(
            "AUDIO_EXTRACTION_FAILED",
            ErrorStage.AUDIO_EXTRACT,
            "Audio extraction failed",
        ) from None


@contextmanager
def temporary_audio(
    media_path: Path,
    *,
    timeout_seconds: float = 60,
    runner: CommandRunner = subprocess.run,
) -> Iterator[ExtractedAudio]:
    with tempfile.TemporaryDirectory(prefix="megabrain-audio-") as directory:
        path = Path(directory) / "audio.wav"
        metadata = extract_audio(
            media_path,
            path,
            timeout_seconds=timeout_seconds,
            runner=runner,
        )
        yield ExtractedAudio(path=path, metadata=metadata)
