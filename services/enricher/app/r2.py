from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from app.media import ErrorStage, MediaProcessingError, SourceMetadata


def _download_error(
    error_code: str,
    message: str,
    *,
    retryable: bool,
) -> MediaProcessingError:
    return MediaProcessingError(
        error_code=error_code,
        stage=ErrorStage.R2_DOWNLOAD,
        message=message,
        retryable=retryable,
    )


def _integrity_error() -> MediaProcessingError:
    return MediaProcessingError(
        error_code="INTEGRITY_MISMATCH",
        stage=ErrorStage.INTEGRITY,
        message="Downloaded object failed integrity validation",
        retryable=False,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_object_key(object_key: str, shortcode: str) -> None:
    expected_prefix = f"original/instagram/reels/{shortcode}/"
    if (
        not object_key.startswith(expected_prefix)
        or object_key == expected_prefix
        or ".." in Path(object_key).parts
        or object_key.startswith("/")
    ):
        raise MediaProcessingError(
            error_code="INVALID_REQUEST",
            stage=ErrorStage.INPUT,
            message="Object key is not valid for the requested Reel",
            retryable=False,
        )


def _translate_download_error(error: Exception) -> MediaProcessingError:
    response = getattr(error, "response", {})
    if not isinstance(response, dict):
        response = {}
    code = str(response.get("Error", {}).get("Code", ""))
    status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    if code in {"404", "NoSuchKey", "NotFound"} or status == 404:
        return _download_error(
            "OBJECT_NOT_FOUND",
            "Source object was not found",
            retryable=False,
        )
    if code in {"403", "AccessDenied"} or status == 403:
        return _download_error(
            "OBJECT_ACCESS_DENIED",
            "Source object could not be accessed",
            retryable=False,
        )
    return _download_error(
        "OBJECT_READ_FAILED",
        "Source object could not be downloaded",
        retryable=True,
    )


@contextmanager
def verified_r2_object(
    *,
    client: Any,
    bucket: str,
    object_key: str,
    shortcode: str,
    expected_sha256: str,
    expected_size_bytes: int | None = None,
) -> Iterator[tuple[Path, SourceMetadata]]:
    validate_object_key(object_key, shortcode)
    with tempfile.TemporaryDirectory(prefix="megabrain-source-") as directory:
        path = Path(directory) / "source"
        try:
            head = client.head_object(Bucket=bucket, Key=object_key)
            remote_size = int(head["ContentLength"])
            with path.open("wb") as output:
                client.download_fileobj(bucket, object_key, output)
                output.flush()
                os.fsync(output.fileno())
            size_bytes = path.stat().st_size
            sha256 = _sha256(path)
        # Storage SDKs expose provider errors through different exception classes.
        except Exception as error:  # noqa: BLE001
            raise _translate_download_error(error) from None

        if (
            size_bytes <= 0
            or size_bytes != remote_size
            or (expected_size_bytes is not None and size_bytes != expected_size_bytes)
            or sha256 != expected_sha256
        ):
            raise _integrity_error()

        yield (
            path,
            SourceMetadata(
                object_key=object_key,
                sha256=sha256,
                size_bytes=size_bytes,
            ),
        )
