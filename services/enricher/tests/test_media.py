from __future__ import annotations

import json
import subprocess
import wave
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.media import (
    MediaProcessingError,
    extract_audio,
    probe_media,
    temporary_audio,
)


def _ffmpeg(output: Path, *, audio: bool, sample_rate: int = 22_050) -> Path:
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "color=c=black:s=16x16:d=0.2:r=5",
    ]
    if audio:
        command.extend(
            [
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency=440:sample_rate={sample_rate}:duration=0.2",
                "-shortest",
                "-c:a",
                "aac",
            ]
        )
    command.extend(["-c:v", "mpeg4", "-y", str(output)])
    subprocess.run(command, check=True, capture_output=True, timeout=10)
    return output


@pytest.fixture
def media_with_audio(tmp_path: Path) -> Path:
    return _ffmpeg(tmp_path / "with-audio.mp4", audio=True)


@pytest.fixture
def media_without_audio(tmp_path: Path) -> Path:
    return _ffmpeg(tmp_path / "without-audio.mp4", audio=False)


def test_a_probe_normalizes_only_approved_minimum_metadata(
    media_with_audio: Path,
) -> None:
    metadata = probe_media(media_with_audio)

    assert metadata.container_format == "mp4"
    assert metadata.duration_seconds == pytest.approx(0.2, abs=0.05)
    assert metadata.video.codec == "mpeg4"
    assert (metadata.video.width, metadata.video.height) == (16, 16)
    assert metadata.audio is not None
    assert metadata.audio.codec == "aac"
    assert metadata.audio.sample_rate_hz == 22_050
    assert metadata.audio.channels == 1
    assert metadata.audio.duration_seconds == pytest.approx(0.2, abs=0.05)
    assert isinstance(metadata.container_format, str)
    assert isinstance(metadata.duration_seconds, float)
    assert isinstance(metadata.video.width, int)
    assert isinstance(metadata.video.height, int)
    assert isinstance(metadata.audio.sample_rate_hz, int)
    assert isinstance(metadata.audio.channels, int)
    assert set(metadata.model_dump()) == {
        "container_format",
        "duration_seconds",
        "video",
        "audio",
    }


def test_b_probe_represents_missing_audio_without_extracting(
    media_without_audio: Path,
) -> None:
    metadata = probe_media(media_without_audio)

    assert metadata.video.codec == "mpeg4"
    assert metadata.audio is None


def test_c_probe_rejects_malformed_json_with_stable_sanitized_error() -> None:
    runner = Mock(return_value=subprocess.CompletedProcess([], 0, "not-json", ""))

    with pytest.raises(MediaProcessingError) as raised:
        probe_media(Path("private-input.mp4"), runner=runner)

    assert raised.value.error_code == "PROBE_FAILED"
    assert raised.value.stage == "probe"
    assert raised.value.retryable is False
    assert str(raised.value) == "Media probe failed"
    assert "private-input" not in str(raised.value)


def test_probe_command_failure_has_stable_sanitized_error() -> None:
    runner = Mock(
        side_effect=subprocess.CalledProcessError(
            1,
            ["ffprobe"],
            stderr="private ffprobe detail",
        )
    )

    with pytest.raises(MediaProcessingError) as raised:
        probe_media(Path("private-input.mp4"), runner=runner)

    assert raised.value.error_code == "PROBE_FAILED"
    assert raised.value.stage == "probe"
    assert str(raised.value) == "Media probe failed"
    assert "private" not in str(raised.value)


def test_d_probe_rejects_invalid_json_shape() -> None:
    runner = Mock(
        return_value=subprocess.CompletedProcess(
            [], 0, json.dumps({"format": {}, "streams": "invalid"}), ""
        )
    )

    with pytest.raises(MediaProcessingError, match="^Media probe failed$") as raised:
        probe_media(Path("input.mp4"), runner=runner)

    assert (raised.value.error_code, raised.value.stage) == (
        "PROBE_FAILED",
        "probe",
    )


def test_e_probe_uses_safe_argv_timeout_and_captured_output() -> None:
    runner = Mock(side_effect=subprocess.TimeoutExpired(["ffprobe"], 7))

    with pytest.raises(MediaProcessingError) as raised:
        probe_media(Path("name; touch PWNED.mp4"), timeout_seconds=7, runner=runner)

    argv = runner.call_args.args[0]
    assert argv[0] == "ffprobe"
    assert argv[-1] == "name; touch PWNED.mp4"
    assert runner.call_args.kwargs == {
        "check": True,
        "capture_output": True,
        "text": True,
        "timeout": 7,
    }
    assert raised.value.error_code == "PROBE_FAILED"
    assert "PWNED" not in str(raised.value)


def test_f_extracts_pcm_s16le_mono_and_preserves_source_sample_rate(
    media_with_audio: Path, tmp_path: Path
) -> None:
    output = tmp_path / "audio.wav"

    result = extract_audio(media_with_audio, output)

    with wave.open(str(output), "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getframerate() == 22_050
    assert result.format == "wav"
    assert result.sample_rate_hz == 22_050
    assert result.channels == 1
    assert result.duration_seconds == pytest.approx(0.2, abs=0.05)


def test_g_extract_uses_expected_argv_without_forcing_16khz(tmp_path: Path) -> None:
    runner = Mock(return_value=subprocess.CompletedProcess([], 0, "", ""))
    output = tmp_path / "audio.wav"

    with pytest.raises(MediaProcessingError) as raised:
        extract_audio(Path("input.mp4"), output, timeout_seconds=9, runner=runner)

    argv = runner.call_args.args[0]
    assert argv == [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        "input.mp4",
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ac",
        "1",
        "-y",
        str(output),
    ]
    assert "-ar" not in argv
    assert runner.call_args.kwargs == {
        "check": True,
        "capture_output": True,
        "timeout": 9,
    }
    assert (raised.value.error_code, raised.value.stage) == (
        "AUDIO_EXTRACTION_FAILED",
        "audio_extract",
    )


def test_h_temporary_audio_cleans_up_after_success(media_with_audio: Path) -> None:
    with temporary_audio(media_with_audio) as extracted:
        audio_path = extracted.path
        parent = audio_path.parent
        assert audio_path.exists()

    assert not audio_path.exists()
    assert not parent.exists()


def test_i_temporary_audio_cleans_up_partial_file_after_extraction_failure() -> None:
    created: list[Path] = []

    def failing_runner(argv: list[str], **_kwargs: object) -> None:
        output = Path(argv[-1])
        output.write_bytes(b"partial sensitive audio")
        created.append(output)
        raise subprocess.CalledProcessError(1, argv, stderr=b"private detail")

    with (
        pytest.raises(MediaProcessingError) as raised,
        temporary_audio(Path("input.mp4"), runner=failing_runner),
    ):
        raise AssertionError("context must not be entered")

    assert raised.value.error_code == "AUDIO_EXTRACTION_FAILED"
    assert str(raised.value) == "Audio extraction failed"
    assert len(created) == 1
    assert not created[0].exists()
    assert not created[0].parent.exists()


def test_temporary_audio_cleans_up_when_transcription_body_fails(
    media_with_audio: Path,
) -> None:
    with (
        pytest.raises(RuntimeError, match="provider failed"),
        temporary_audio(media_with_audio) as extracted,
    ):
        audio_path = extracted.path
        parent = audio_path.parent
        raise RuntimeError("provider failed")

    assert not audio_path.exists()
    assert not parent.exists()
