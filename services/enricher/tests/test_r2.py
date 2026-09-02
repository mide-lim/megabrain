from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.main import process_source
from app.media import EnrichmentRequest, MediaProcessingError
from app.r2 import verified_r2_object


class FakeClientError(Exception):
    def __init__(self, response: dict[str, object]) -> None:
        self.response = response


class FakeR2Client:
    def __init__(
        self,
        content: bytes,
        *,
        declared_size: int | None = None,
        download_error: Exception | None = None,
    ) -> None:
        self.content = content
        self.declared_size = (
            declared_size if declared_size is not None else len(content)
        )
        self.download_error = download_error

    def head_object(self, **_kwargs: object) -> dict[str, int]:
        return {"ContentLength": self.declared_size}

    def download_fileobj(self, _bucket: str, _key: str, output: object) -> None:
        output.write(self.content)  # type: ignore[attr-defined]
        if self.download_error is not None:
            raise self.download_error


def _payload(content: bytes) -> EnrichmentRequest:
    return EnrichmentRequest(
        contract_version="1.0",
        attempt_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        reel_id=42,
        shortcode="ABC_123-x",
        object_key="original/instagram/reels/ABC_123-x/video.mp4",
        expected_sha256=hashlib.sha256(content).hexdigest(),
        expected_size_bytes=len(content),
        pipeline_version="sprint-3-v1",
    )


def test_valid_object_reaches_media_pipeline_and_is_cleaned_afterward() -> None:
    content = b"valid media bytes"
    observed: list[Path] = []

    def pipeline(path: Path) -> str:
        observed.append(path)
        assert path.read_bytes() == content
        return "processed"

    result = process_source(
        _payload(content),
        client=FakeR2Client(content),
        bucket="test-bucket",
        pipeline=pipeline,
    )

    assert result == "processed"
    assert len(observed) == 1
    assert not observed[0].exists()
    assert not observed[0].parent.exists()


def test_hash_mismatch_does_not_call_pipeline_and_cleans_temporary_file() -> None:
    content = b"tampered media"
    payload = _payload(content)
    payload.expected_sha256 = "0" * 64
    seen: list[Path] = []
    called = False

    def pipeline(_path: Path) -> None:
        nonlocal called
        called = True

    with (
        pytest.raises(MediaProcessingError) as raised,
        verified_r2_object(
            client=FakeR2Client(content),
            bucket="test-bucket",
            object_key=payload.object_key,
            shortcode=payload.shortcode,
            expected_sha256=payload.expected_sha256,
            expected_size_bytes=payload.expected_size_bytes,
        ) as (path, _metadata),
    ):
        seen.append(path)
        pipeline(path)

    assert raised.value.error_code == "INTEGRITY_MISMATCH"
    assert raised.value.stage == "integrity"
    assert called is False
    assert seen == []


def test_partial_download_is_rejected_and_temporary_file_is_cleaned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = b"partial"
    created: list[Path] = []
    original_open = Path.open

    def tracking_open(path: Path, *args: object, **kwargs: object):
        created.append(path)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", tracking_open)

    with (
        pytest.raises(MediaProcessingError) as raised,
        verified_r2_object(
            client=FakeR2Client(content, declared_size=len(content) + 5),
            bucket="test-bucket",
            object_key="original/instagram/reels/ABC_123-x/video.mp4",
            shortcode="ABC_123-x",
            expected_sha256=hashlib.sha256(content).hexdigest(),
        ),
    ):
        raise AssertionError("invalid download must not be yielded")

    assert raised.value.error_code == "INTEGRITY_MISMATCH"
    assert created
    assert all(not path.exists() for path in created)
    assert all(not path.parent.exists() for path in created)


def test_download_failure_does_not_yield_and_cleans_partial_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = b"partial sensitive data"
    created: list[Path] = []
    original_open = Path.open

    def tracking_open(path: Path, *args: object, **kwargs: object):
        created.append(path)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", tracking_open)
    failure = FakeClientError(
        {"Error": {"Code": "RequestTimeout"}, "ResponseMetadata": {}}
    )

    with (
        pytest.raises(MediaProcessingError) as raised,
        verified_r2_object(
            client=FakeR2Client(content, download_error=failure),
            bucket="test-bucket",
            object_key="original/instagram/reels/ABC_123-x/video.mp4",
            shortcode="ABC_123-x",
            expected_sha256=hashlib.sha256(content).hexdigest(),
        ),
    ):
        raise AssertionError("failed download must not be yielded")

    assert raised.value.error_code == "OBJECT_READ_FAILED"
    assert raised.value.retryable is True
    assert len(created) == 1
    assert not created[0].exists()
    assert not created[0].parent.exists()


def test_missing_object_has_stable_error_without_pipeline_handoff() -> None:
    class MissingClient(FakeR2Client):
        def head_object(self, **_kwargs: object) -> dict[str, int]:
            raise FakeClientError(
                {
                    "Error": {"Code": "NoSuchKey"},
                    "ResponseMetadata": {"HTTPStatusCode": 404},
                }
            )

    with pytest.raises(MediaProcessingError) as raised:
        process_source(
            _payload(b"content"),
            client=MissingClient(b"content"),
            bucket="test-bucket",
            pipeline=lambda _path: pytest.fail("pipeline must not run"),
        )

    assert raised.value.error_code == "OBJECT_NOT_FOUND"
    assert raised.value.stage == "r2_download"
