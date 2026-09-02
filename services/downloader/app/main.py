from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import os
import re
import secrets
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlparse

import boto3
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field, field_validator
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger("megabrain-downloader")

app = FastAPI(
    title="MegaBrain Downloader",
    version="0.2.0",
)


def required_env(name: str) -> str:
    value = os.getenv(name)

    if not value:
        raise RuntimeError(
            f"Variável obrigatória ausente: {name}"
        )

    return value


R2_ENDPOINT = required_env("R2_ENDPOINT")
R2_ACCESS_KEY_ID = required_env("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = required_env(
    "R2_SECRET_ACCESS_KEY"
)
R2_BUCKET = required_env("R2_BUCKET")
DOWNLOADER_API_KEY = required_env(
    "DOWNLOADER_API_KEY"
)


s3_client = boto3.client(
    service_name="s3",
    endpoint_url=R2_ENDPOINT,
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY,
    region_name="auto",
)


class DownloadRequest(BaseModel):
    item_id: int = Field(gt=0)
    shortcode: str
    url: str
    telegram_chat_id: int

    @field_validator("shortcode")
    @classmethod
    def validate_shortcode(
        cls,
        value: str,
    ) -> str:
        if not re.fullmatch(
            r"[A-Za-z0-9_-]+",
            value,
        ):
            raise ValueError("Shortcode inválido")

        return value

    @field_validator("url")
    @classmethod
    def validate_instagram_url(
        cls,
        value: str,
    ) -> str:
        parsed = urlparse(value)

        if parsed.scheme not in {"http", "https"}:
            raise ValueError(
                "A URL precisa usar HTTP ou HTTPS"
            )

        if parsed.hostname not in {
            "instagram.com",
            "www.instagram.com",
        }:
            raise ValueError(
                "A URL precisa pertencer ao Instagram"
            )

        if not re.match(
            r"^/reels?/[A-Za-z0-9_-]+/?",
            parsed.path,
        ):
            raise ValueError(
                "A URL não corresponde a um Reel"
            )

        return value


def calculate_sha256(file_path: Path) -> str:
    digest = hashlib.sha256()

    with file_path.open("rb") as source:
        for chunk in iter(
            lambda: source.read(1024 * 1024),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def probe_stream_types(
    file_path: Path,
) -> set[str]:
    """
    Usa o ffprobe para descobrir se o arquivo possui
    vídeo, áudio ou ambos.
    """

    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "stream=codec_type",
        "-of",
        "json",
        str(file_path),
    ]

    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )

    payload = json.loads(result.stdout)

    return {
        stream["codec_type"]
        for stream in payload.get("streams", [])
        if stream.get("codec_type")
    }


def source_expects_audio(
    info: dict,
) -> bool:
    """
    Verifica pelos formatos escolhidos pelo yt-dlp
    se o resultado deveria conter áudio.
    """

    requested_formats = (
        info.get("requested_formats") or []
    )

    if requested_formats:
        return any(
            media_format.get("acodec")
            not in {None, "none"}
            for media_format in requested_formats
        )

    return (
        info.get("acodec")
        not in {None, "none"}
    )


def find_downloaded_media(
    directory: Path,
    expects_audio: bool,
) -> tuple[Path, set[str]]:
    """
    Procura o arquivo final do yt-dlp e valida
    seus streams com ffprobe.

    Arquivos somente de áudio nunca são aceitos.
    """

    ignored_suffixes = {
        ".part",
        ".ytdl",
        ".json",
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
        ".description",
    }

    candidates = [
        file
        for file in directory.iterdir()
        if file.is_file()
        and file.suffix.lower()
        not in ignored_suffixes
    ]

    if not candidates:
        raise RuntimeError(
            "O yt-dlp não produziu nenhum "
            "arquivo de mídia."
        )

    valid_candidates: list[
        tuple[Path, set[str]]
    ] = []

    for candidate in candidates:
        try:
            stream_types = probe_stream_types(
                candidate
            )

            logger.info(
                "Arquivo candidato: %s | "
                "streams: %s",
                candidate.name,
                sorted(stream_types),
            )

        except (
            subprocess.SubprocessError,
            json.JSONDecodeError,
            OSError,
        ) as error:
            logger.warning(
                "Não foi possível analisar "
                "o arquivo %s: %s",
                candidate.name,
                error,
            )
            continue

        if "video" not in stream_types:
            logger.warning(
                "Arquivo ignorado por não "
                "possuir vídeo: %s",
                candidate.name,
            )
            continue

        if (
            expects_audio
            and "audio" not in stream_types
        ):
            logger.warning(
                "Arquivo ignorado por não "
                "possuir áudio: %s",
                candidate.name,
            )
            continue

        valid_candidates.append(
            (
                candidate,
                stream_types,
            )
        )

    if not valid_candidates:
        if expects_audio:
            raise RuntimeError(
                "Nenhum arquivo final contém "
                "vídeo e áudio. A combinação "
                "pelo FFmpeg pode ter falhado."
            )

        raise RuntimeError(
            "Nenhum arquivo produzido contém "
            "stream de vídeo."
        )

    media_path, stream_types = max(
        valid_candidates,
        key=lambda item: (
            item[0].stat().st_size
        ),
    )

    return media_path, stream_types


def check_api_key(
    received_key: str | None,
) -> None:
    if not received_key:
        raise HTTPException(
            status_code=401,
            detail="Chave interna ausente",
        )

    if not secrets.compare_digest(
        received_key,
        DOWNLOADER_API_KEY,
    ):
        raise HTTPException(
            status_code=401,
            detail="Chave interna inválida",
        )


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "healthy",
        "version": "0.2.0",
    }


@app.post("/download")
def download_reel(
    payload: DownloadRequest,
    x_megabrain_key: str | None = Header(
        default=None,
        alias="X-MegaBrain-Key",
    ),
) -> dict:
    check_api_key(x_megabrain_key)

    try:
        with TemporaryDirectory(
            prefix=(
                f"reel-"
                f"{payload.shortcode}-"
            )
        ) as temporary_directory:
            work_directory = Path(
                temporary_directory
            )

            output_template = str(
                work_directory
                / (
                    f"{payload.shortcode}"
                    ".%(ext)s"
                )
            )

            options = {
                # Ordem de preferência:
                # 1. MP4 pronto com vídeo e áudio.
                # 2. Vídeo MP4 + áudio M4A.
                # 3. Outro formato pronto completo.
                # 4. Vídeo e áudio separados.
                # 5. Vídeo silencioso como fallback.
                "format": (
                    "b[ext=mp4]"
                    "[vcodec!=none]"
                    "[acodec!=none]/"
                    "bv[ext=mp4]"
                    "+ba[ext=m4a]/"
                    "b[vcodec!=none]"
                    "[acodec!=none]/"
                    "bv+ba/"
                    "bv[ext=mp4]/"
                    "bv"
                ),
                "outtmpl": output_template,
                "merge_output_format": "mp4",
                "noplaylist": True,
                "quiet": False,
                "no_warnings": False,
                "retries": 3,
                "fragment_retries": 3,
                "socket_timeout": 30,
            }

            logger.info(
                "Iniciando download "
                "do item %s: %s",
                payload.item_id,
                payload.url,
            )

            with YoutubeDL(
                options
            ) as downloader:
                extracted_info = (
                    downloader.extract_info(
                        payload.url,
                        download=True,
                    )
                )

                expects_audio = (
                    source_expects_audio(
                        extracted_info
                    )
                )

                (
                    media_path,
                    stream_types,
                ) = find_downloaded_media(
                    work_directory,
                    expects_audio=(
                        expects_audio
                    ),
                )

                info = (
                    downloader.sanitize_info(
                        extracted_info
                    )
                )

            logger.info(
                "Arquivo final selecionado: "
                "%s | streams: %s",
                media_path.name,
                sorted(stream_types),
            )

            file_size = (
                media_path.stat().st_size
            )

            sha256 = calculate_sha256(
                media_path
            )

            extension = (
                media_path.suffix.lower()
                or ".mp4"
            )

            mime_type = (
                mimetypes.guess_type(
                    media_path.name
                )[0]
                or "application/octet-stream"
            )

            object_key = (
                "original/instagram/reels/"
                f"{payload.shortcode}/"
                f"video{extension}"
            )

            logger.info(
                "Enviando item %s para "
                "o R2: %s",
                payload.item_id,
                object_key,
            )

            s3_client.upload_file(
                str(media_path),
                R2_BUCKET,
                object_key,
                ExtraArgs={
                    "ContentType": mime_type,
                    "Metadata": {
                        "shortcode": (
                            payload.shortcode
                        ),
                        "sha256": sha256,
                        "streams": ",".join(
                            sorted(stream_types)
                        ),
                    },
                },
            )

            downloaded_at = datetime.now(
                timezone.utc
            ).isoformat()

            logger.info(
                "Item %s armazenado "
                "no R2: %s",
                payload.item_id,
                object_key,
            )

            duration = info.get("duration")

            return {
                "success": True,
                "item_id": (
                    payload.item_id
                ),
                "shortcode": (
                    payload.shortcode
                ),
                "telegram_chat_id": (
                    payload.telegram_chat_id
                ),
                "title": info.get(
                    "title"
                ),
                "creator": (
                    info.get("uploader")
                    or info.get("channel")
                    or info.get("creator")
                ),
                "caption": info.get(
                    "description"
                ),
                "duration_seconds": (
                    float(duration)
                    if isinstance(
                        duration,
                        (int, float),
                    )
                    else None
                ),
                "filename": (
                    media_path.name
                ),
                "mime_type": mime_type,
                "file_size_bytes": (
                    file_size
                ),
                "sha256": sha256,
                "stream_types": sorted(
                    stream_types
                ),
                "has_video": (
                    "video" in stream_types
                ),
                "has_audio": (
                    "audio" in stream_types
                ),
                "storage_provider": (
                    "cloudflare_r2"
                ),
                "storage_bucket": (
                    R2_BUCKET
                ),
                "object_key": object_key,
                "downloaded_at": (
                    downloaded_at
                ),
                "error_message": None,
            }

    except DownloadError as error:
        message = str(error)[:2000]

        logger.warning(
            "Falha do yt-dlp "
            "no item %s: %s",
            payload.item_id,
            message,
        )

        return {
            "success": False,
            "item_id": payload.item_id,
            "shortcode": payload.shortcode,
            "telegram_chat_id": (
                payload.telegram_chat_id
            ),
            "error_code": (
                "download_failed"
            ),
            "error_message": message,
        }

    except Exception as error:
        message = str(error)[:2000]

        logger.exception(
            "Falha inesperada "
            "no item %s",
            payload.item_id,
        )

        return {
            "success": False,
            "item_id": payload.item_id,
            "shortcode": payload.shortcode,
            "telegram_chat_id": (
                payload.telegram_chat_id
            ),
            "error_code": (
                "unexpected_error"
            ),
            "error_message": message,
        }
