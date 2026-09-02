from __future__ import annotations

import hashlib
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest

from app import main
from app.media import (
    AudioMetadata,
    EnrichmentRequest,
    ExtractedAudio,
    MediaMetadata,
    SourceMetadata,
    TranscriptionInput,
    VideoMetadata,
)
from app.stt.base import SpeechToTextError, TranscriptionResult


def payload(content: bytes = b"video") -> EnrichmentRequest:
    return EnrichmentRequest(
        contract_version="1.0",
        attempt_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        reel_id=42,
        shortcode="ABC_123-x",
        object_key="original/instagram/reels/ABC_123-x/video.mp4",
        expected_sha256=hashlib.sha256(content).hexdigest(),
        expected_size_bytes=len(content),
        pipeline_version="sprint-3-v1",
        language_hint="pt-BR",
    )


def metadata(*, audio: bool) -> MediaMetadata:
    return MediaMetadata(
        container_format="mp4",
        duration_seconds=2.0,
        video=VideoMetadata(codec="h264", width=1080, height=1920),
        audio=(
            AudioMetadata(codec="aac", sample_rate_hz=48_000, channels=2)
            if audio
            else None
        ),
    )


def source() -> SourceMetadata:
    return SourceMetadata(
        object_key=payload().object_key,
        sha256=hashlib.sha256(b"video").hexdigest(),
        size_bytes=5,
    )


def test_no_audio_returns_normalized_result_without_extracting_or_stt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extract = Mock(side_effect=AssertionError("must not extract"))
    adapter = Mock()
    monkeypatch.setattr(main, "temporary_audio", extract)

    result = main.enrich_media(
        payload(),
        Path("video"),
        source(),
        metadata=metadata(audio=False),
        stt_adapter=adapter,
    )

    assert result.transcription.outcome == "no_audio"
    assert result.transcription_input is None
    assert result.transcription.transcript_text is None
    assert result.transcription.engine.provider is None
    extract.assert_not_called()
    adapter.transcribe.assert_not_called()


@pytest.mark.parametrize(
    ("text", "outcome"), [(" fala clara ", "transcribed"), ("  ", "empty_transcript")]
)
def test_audio_is_extracted_transcribed_and_normalized(
    monkeypatch: pytest.MonkeyPatch, text: str, outcome: str
) -> None:
    audio_input = TranscriptionInput(
        format="wav", sample_rate_hz=48_000, channels=1, duration_seconds=2.0
    )

    @contextmanager
    def fake_audio(_path: Path):
        yield ExtractedAudio(Path("audio.wav"), audio_input)

    adapter = Mock()
    adapter.transcribe.return_value = TranscriptionResult(
        text, "pt-BR", "google", "chirp_3", "req-1"
    )
    monkeypatch.setattr(main, "temporary_audio", fake_audio)

    result = main.enrich_media(
        payload(),
        Path("video"),
        source(),
        metadata=metadata(audio=True),
        stt_adapter=adapter,
    )

    assert result.transcription.outcome == outcome
    assert result.transcription.transcript_text == text.strip()
    assert result.transcription.engine.model == "chirp_3"
    assert result.transcription_input == audio_input
    adapter.transcribe.assert_called_once_with(
        Path("audio.wav"), language_hint="pt-BR", duration_seconds=2.0
    )


def test_response_exposes_only_approved_transcription_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audio_input = TranscriptionInput(
        format="wav", sample_rate_hz=48_000, channels=1, duration_seconds=2.0
    )

    @contextmanager
    def fake_audio(_path: Path):
        yield ExtractedAudio(Path("audio.wav"), audio_input)

    adapter = Mock()
    adapter.transcribe.return_value = TranscriptionResult(
        "texto", "pt-BR", "google", "chirp_3", "request-id"
    )
    monkeypatch.setattr(main, "temporary_audio", fake_audio)

    response = main.enrich_media(
        payload(),
        Path("video"),
        source(),
        metadata=metadata(audio=True),
        stt_adapter=adapter,
    ).model_dump(mode="json")

    assert set(response["transcription"]) == {
        "outcome",
        "transcript_text",
        "transcript_language",
        "engine",
    }
    assert set(response["transcription"]["engine"]) == {
        "provider",
        "model",
        "request_id",
    }
    serialized = str(response)
    assert "timestamps" not in serialized
    assert "transcript_segments" not in serialized
    assert "raw" not in serialized


def test_transcription_error_is_not_converted_to_a_content_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @contextmanager
    def fake_audio(_path: Path):
        yield ExtractedAudio(
            Path("audio.wav"),
            TranscriptionInput(
                format="wav", sample_rate_hz=16_000, channels=1, duration_seconds=1.0
            ),
        )

    adapter = Mock()
    adapter.transcribe.side_effect = SpeechToTextError(
        "STT_TIMEOUT", "Transcription timed out", retryable=True
    )
    monkeypatch.setattr(main, "temporary_audio", fake_audio)

    with pytest.raises(SpeechToTextError):
        main.enrich_media(
            payload(),
            Path("video"),
            source(),
            metadata=metadata(audio=True),
            stt_adapter=adapter,
        )


def test_complete_r2_to_stt_pipeline_is_mockable_without_external_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = b"video"
    observed_source_paths: list[Path] = []

    class R2Client:
        def head_object(self, **_kwargs: object) -> dict[str, int]:
            return {"ContentLength": len(content)}

        def download_fileobj(self, _bucket: str, _key: str, output: object) -> None:
            output.write(content)  # type: ignore[attr-defined]

    def fake_probe(path: Path) -> MediaMetadata:
        observed_source_paths.append(path)
        assert path.read_bytes() == content
        return metadata(audio=True)

    @contextmanager
    def fake_audio(path: Path):
        assert path == observed_source_paths[0]
        yield ExtractedAudio(
            Path("audio.wav"),
            TranscriptionInput(
                format="wav",
                sample_rate_hz=48_000,
                channels=1,
                duration_seconds=2,
            ),
        )

    adapter = Mock()
    adapter.transcribe.return_value = TranscriptionResult(
        "texto", "pt-BR", "google", "chirp_3", "request-id"
    )
    monkeypatch.setattr(main, "probe_media", fake_probe)
    monkeypatch.setattr(main, "temporary_audio", fake_audio)

    result = main.process_source(
        payload(content),
        client=R2Client(),
        bucket="bucket",
        stt_adapter=adapter,
    )

    assert result.source.sha256 == hashlib.sha256(content).hexdigest()
    assert result.transcription.outcome == "transcribed"
    assert len(observed_source_paths) == 1
    assert not observed_source_paths[0].exists()
    assert not observed_source_paths[0].parent.exists()


def test_pipeline_started_at_is_captured_before_r2_download(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = b"video"
    expected_started_at = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
    events: list[str] = []

    class FakeDateTime:
        @staticmethod
        def now(_timezone: object) -> datetime:
            events.append("started")
            return expected_started_at

    class R2Client:
        def head_object(self, **_kwargs: object) -> dict[str, int]:
            events.append("r2")
            return {"ContentLength": len(content)}

        def download_fileobj(self, _bucket: str, _key: str, output: object) -> None:
            output.write(content)  # type: ignore[attr-defined]

    def fake_enrich_media(
        _payload: EnrichmentRequest,
        _media_path: Path,
        _source: SourceMetadata,
        *,
        stt_adapter: object,
        started_at: datetime,
    ) -> str:
        events.append("enrich")
        assert started_at == expected_started_at
        return "completed"

    monkeypatch.setattr(main, "datetime", FakeDateTime)
    monkeypatch.setattr(main, "enrich_media", fake_enrich_media)

    result = main.process_source(
        payload(content),
        client=R2Client(),
        bucket="bucket",
        stt_adapter=Mock(),
    )

    assert result == "completed"
    assert events == ["started", "r2", "enrich"]
