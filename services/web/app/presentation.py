from __future__ import annotations

from typing import Any


def reel_detail_context(reel: dict[str, Any], video_url: str | None) -> dict[str, Any]:
    transcript = reel.get("transcript_text")
    if reel.get("enrichment_outcome") != "transcribed" or not (
        isinstance(transcript, str) and transcript.strip()
    ):
        transcript = None

    duration = reel.get("media_duration_seconds")
    if duration is None:
        duration = reel.get("duration_seconds")

    return {
        "reel": reel,
        "duration": duration,
        "transcript": transcript,
        "video_url": video_url,
    }
