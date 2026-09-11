from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

for name, value in {
    "R2_ENDPOINT": "https://example.invalid",
    "R2_ACCESS_KEY_ID": "test-access-key",
    "R2_SECRET_ACCESS_KEY": "test-secret-key",
    "R2_BUCKET": "test-bucket",
    "DOWNLOADER_API_KEY": "test-downloader-key",
}.items():
    os.environ.setdefault(name, value)

MODULE_PATH = Path(__file__).resolve().parents[1] / "app" / "main.py"
with patch("boto3.client") as mocked_boto_client:
    spec = importlib.util.spec_from_file_location(
        "megabrain_downloader_main",
        MODULE_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    downloader_main = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(downloader_main)


class FakeYoutubeDL:
    def __init__(self, options: dict) -> None:
        self.options = options

    def __enter__(self) -> "FakeYoutubeDL":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def extract_info(self, url: str, download: bool) -> dict:
        return {
            "duration": 12,
            "acodec": "aac",
            "uploader": "creator",
            "title": "title",
            "description": "caption",
        }

    def sanitize_info(self, info: dict) -> dict:
        return info


class DownloadRequestTests(unittest.TestCase):
    def test_valid_request_does_not_require_telegram_chat_id(self) -> None:
        payload = downloader_main.DownloadRequest(
            item_id=7,
            shortcode="AbC_123-xyz",
            url="https://www.instagram.com/reel/AbC_123-xyz/",
        )

        self.assertEqual(payload.item_id, 7)
        self.assertNotIn("telegram_chat_id", payload.model_dump())

    def test_legacy_extra_telegram_chat_id_is_ignored(self) -> None:
        payload = downloader_main.DownloadRequest.model_validate(
            {
                "item_id": 7,
                "shortcode": "AbC_123-xyz",
                "url": "https://www.instagram.com/reel/AbC_123-xyz/",
                "telegram_chat_id": 123456789,
            }
        )

        self.assertNotIn("telegram_chat_id", payload.model_dump())

    def test_canonical_request_validates(self) -> None:
        payload = downloader_main.DownloadRequest.model_validate(
            {
                "item_id": 1,
                "shortcode": "canonical_shortcode",
                "url": "https://instagram.com/reels/canonical_shortcode",
            }
        )

        self.assertEqual(payload.model_dump()["item_id"], 1)

    def test_shortcode_and_instagram_url_rules_remain_enforced(self) -> None:
        with self.assertRaises(ValueError):
            downloader_main.DownloadRequest(
                item_id=1,
                shortcode="not valid!",
                url="https://www.instagram.com/reel/valid/",
            )

        with self.assertRaises(ValueError):
            downloader_main.DownloadRequest(
                item_id=1,
                shortcode="valid",
                url="https://example.invalid/reel/valid/",
            )


class DownloadEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = downloader_main.DownloadRequest(
            item_id=7,
            shortcode="AbC_123-xyz",
            url="https://www.instagram.com/reel/AbC_123-xyz/",
        )

    def response_body(self, response: object) -> dict:
        return json.loads(response.body)

    def test_invalid_api_key_still_raises_401(self) -> None:
        with self.assertRaises(downloader_main.HTTPException) as raised:
            downloader_main.check_api_key("wrong-key")

        self.assertEqual(raised.exception.status_code, 401)

    def test_download_error_returns_safe_502_envelope(self) -> None:
        with patch.object(
            downloader_main,
            "YoutubeDL",
            side_effect=downloader_main.DownloadError("secret upstream detail"),
        ):
            response = downloader_main.download_reel(
                self.payload,
                "test-downloader-key",
            )

        body = self.response_body(response)
        self.assertEqual(response.status_code, 502)
        self.assertEqual(
            body,
            {
                "success": False,
                "item_id": 7,
                "shortcode": "AbC_123-xyz",
                "error": {
                    "code": "DOWNLOAD_FAILED",
                    "message": "Unable to acquire Reel media",
                    "retryable": True,
                },
            },
        )
        self.assertNotIn("secret upstream detail", response.body.decode())
        self.assertNotIn("telegram_chat_id", body)

    def test_unexpected_error_returns_safe_500_envelope(self) -> None:
        with patch.object(
            downloader_main,
            "YoutubeDL",
            side_effect=RuntimeError("internal /private/path detail"),
        ):
            response = downloader_main.download_reel(
                self.payload,
                "test-downloader-key",
            )

        body = self.response_body(response)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            body["error"]["code"], "DOWNLOADER_INTERNAL_ERROR")
        self.assertEqual(
            body["error"]["message"], "Downloader internal processing failed")
        self.assertNotIn("internal /private/path detail", response.body.decode())
        self.assertNotIn("telegram_chat_id", body)

    def test_success_response_has_no_telegram_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            media_path = Path(directory) / "media.mp4"
            media_path.write_bytes(b"fake-video-data")
            upload_file = MagicMock()

            with (
                patch.object(downloader_main, "YoutubeDL", FakeYoutubeDL),
                patch.object(
                    downloader_main,
                    "find_downloaded_media",
                    return_value=(media_path, {"video", "audio"}),
                ),
                patch.object(
                    downloader_main.s3_client,
                    "upload_file",
                    upload_file,
                ),
            ):
                response = downloader_main.download_reel(
                    self.payload,
                    "test-downloader-key",
                )

        self.assertIsInstance(response, dict)
        self.assertTrue(response["success"])
        self.assertEqual(response["item_id"], 7)
        self.assertNotIn("telegram_chat_id", response)
        upload_file.assert_called_once()


if __name__ == "__main__":
    unittest.main()
