from __future__ import annotations

from pathlib import Path

import pytest
from google.api_core import exceptions as google_exceptions

from app.gcs import GoogleTemporaryAudioStore, TemporaryAudioStoreError


class FakeBlob:
    def __init__(self) -> None:
        self.generation = 42
        self.upload_call: tuple[str, str, int] | None = None

    def upload_from_filename(
        self,
        filename: str,
        *,
        content_type: str,
        if_generation_match: int,
    ) -> None:
        self.upload_call = (filename, content_type, if_generation_match)


class FakeBucket:
    def __init__(self, blob: FakeBlob) -> None:
        self._blob = blob
        self.object_name: str | None = None

    def blob(self, object_name: str) -> FakeBlob:
        self.object_name = object_name
        return self._blob


class FakeStorageClient:
    def __init__(self, bucket: FakeBucket) -> None:
        self._bucket = bucket
        self.bucket_name: str | None = None

    def bucket(self, bucket_name: str) -> FakeBucket:
        self.bucket_name = bucket_name
        return self._bucket


def test_upload_uses_attempt_namespace_create_only_and_wav_content_type(
    tmp_path: Path,
) -> None:
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"wav")
    blob = FakeBlob()
    bucket = FakeBucket(blob)
    client = FakeStorageClient(bucket)
    store = GoogleTemporaryAudioStore(bucket="configured-temp-bucket", client=client)

    result = store.upload(
        attempt_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        path=audio_path,
    )

    assert client.bucket_name == "configured-temp-bucket"
    assert bucket.object_name == (
        "f6/transcription/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/audio.wav"
    )
    assert blob.upload_call == (str(audio_path), "audio/wav", 0)
    assert result.bucket == "configured-temp-bucket"
    assert result.object_name == bucket.object_name
    assert result.uri == f"gs://configured-temp-bucket/{bucket.object_name}"
    assert result.generation == "42"


def test_upload_object_precondition_collision_is_a_stable_error(tmp_path: Path) -> None:
    class CollisionBlob(FakeBlob):
        def upload_from_filename(
            self,
            filename: str,
            *,
            content_type: str,
            if_generation_match: int,
        ) -> None:
            self.upload_call = (filename, content_type, if_generation_match)
            raise google_exceptions.PreconditionFailed("object already exists")

    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"wav")
    blob = CollisionBlob()
    store = GoogleTemporaryAudioStore(
        bucket="configured-temp-bucket",
        client=FakeStorageClient(FakeBucket(blob)),
    )

    with pytest.raises(TemporaryAudioStoreError) as raised:
        store.upload(
            attempt_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            path=audio_path,
        )

    assert raised.value.error_code == "STT_BATCH_OBJECT_CONFLICT"
    assert str(raised.value) == "Temporary transcription audio object already exists"
    assert blob.upload_call == (str(audio_path), "audio/wav", 0)
