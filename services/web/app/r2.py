from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import boto3

PRESIGNED_URL_TTL_SECONDS = 300


def _client(endpoint: str, access_key_id: str, secret_access_key: str) -> Any:
    return boto3.client(
        service_name="s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        region_name="auto",
    )


def presigned_video_url(reel: dict[str, Any]) -> str | None:
    object_key = reel.get("object_key")
    shortcode = reel.get("shortcode")
    storage_bucket = reel.get("storage_bucket")
    configured = {
        name: os.getenv(name)
        for name in (
            "R2_ENDPOINT",
            "R2_ACCESS_KEY_ID",
            "R2_SECRET_ACCESS_KEY",
            "R2_BUCKET",
        )
    }
    bucket = configured["R2_BUCKET"]
    valid_shortcode = isinstance(shortcode, str) and bool(shortcode)
    expected_prefix = (
        f"original/instagram/reels/{shortcode}/" if valid_shortcode else None
    )
    if (
        not isinstance(object_key, str)
        or not object_key
        or object_key.startswith("/")
        or ".." in Path(object_key).parts
        or expected_prefix is None
        or not object_key.startswith(expected_prefix)
        or object_key == expected_prefix
        or not isinstance(storage_bucket, str)
        or storage_bucket != bucket
        or not all(configured.values())
    ):
        return None

    try:
        client = _client(
            configured["R2_ENDPOINT"],
            configured["R2_ACCESS_KEY_ID"],
            configured["R2_SECRET_ACCESS_KEY"],
        )
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": object_key},
            ExpiresIn=PRESIGNED_URL_TTL_SECONDS,
        )
    except Exception:  # noqa: BLE001 - storage signing must fail closed.
        return None
