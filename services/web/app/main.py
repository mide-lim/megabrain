from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.openapi.utils import get_openapi
from fastapi.responses import RedirectResponse, Response
from fastapi.routing import APIRoute
from pydantic import BaseModel
from psycopg.rows import dict_row

from app import database
from app.auth.config import SESSION_COOKIE_NAME
from app.auth.dependencies import require_owner_session
from app.auth.routes import auth_router
from app.csrf import require_api_csrf
from app.categories import (
    associate_category,
    category_exists,
    create_and_associate_category,
    fetch_categories_for_reel,
    reel_exists,
    remove_category,
)
from app.presentation import reel_detail_context
from app.r2 import presigned_video_url
from app.reels import fetch_reel


VERSION = "0.1.0"
PAGE_SIZE = 12

OWNER_SESSION_SECURITY_SCHEME = "OwnerSessionCookie"


app = FastAPI(
    title="MegaBrain Web",
    version=VERSION,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    swagger_ui_oauth2_redirect_url=None,
)
app.include_router(auth_router)


def _uses_dependency(dependant: Any, dependency: Callable[..., Any]) -> bool:
    return any(
        child.call is dependency or _uses_dependency(child, dependency)
        for child in dependant.dependencies
    )


def _document_openapi_security(schema: dict[str, Any]) -> None:
    schema.setdefault("components", {}).setdefault("securitySchemes", {})[
        OWNER_SESSION_SECURITY_SCHEME
    ] = {
        "type": "apiKey",
        "in": "cookie",
        "name": SESSION_COOKIE_NAME,
        "description": "Opaque local single-owner session cookie.",
    }

    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue

        owner_protected = _uses_dependency(route.dependant, require_owner_session)
        csrf_protected = _uses_dependency(route.dependant, require_api_csrf)
        if not owner_protected and not csrf_protected:
            continue

        for operation in schema.get("paths", {}).get(route.path_format, {}).values():
            if not isinstance(operation, dict):
                continue
            responses = operation.setdefault("responses", {})
            if owner_protected:
                operation["security"] = [{OWNER_SESSION_SECURITY_SCHEME: []}]
                responses.setdefault("401", {"description": "Authentication required"})
            if csrf_protected:
                for parameter in operation.get("parameters", []):
                    if parameter.get("in") == "header" and parameter.get("name") == "X-CSRF-Token":
                        parameter["required"] = True
                        parameter["schema"] = {
                            "type": "string",
                            "title": "X-Csrf-Token",
                        }
                responses.setdefault("403", {"description": "CSRF token validation failed"})


def internal_openapi() -> dict[str, Any]:
    if app.openapi_schema is None:
        schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
        _document_openapi_security(schema)
        app.openapi_schema = schema
    return app.openapi_schema


app.openapi = internal_openapi


LIBRARY_QUERY = """
SELECT
    r.id,
    r.title,
    r.creator,
    r.shortcode,
    r.caption,
    r.duration_seconds,
    r.status,
    r.received_at,
    r.downloaded_at,
    (
        enrichment.outcome = 'transcribed'
        AND NULLIF(btrim(enrichment.transcript_text), '') IS NOT NULL
    ) AS has_transcript,
    COALESCE(categories.names, ARRAY[]::TEXT[]) AS categories
FROM app.reels AS r
LEFT JOIN LATERAL (
    SELECT
        outcome,
        transcript_text
    FROM app.reel_enrichments
    WHERE reel_id = r.id
    ORDER BY completed_at DESC, id DESC
    LIMIT 1
) AS enrichment ON TRUE
LEFT JOIN LATERAL (
    SELECT array_agg(c.name ORDER BY lower(c.name), c.id) AS names
    FROM app.reel_categories AS rc
    JOIN app.categories AS c ON c.id = rc.category_id
    WHERE rc.reel_id = r.id
) AS categories ON TRUE
WHERE (
    %s::text IS NULL
    OR r.creator ILIKE %s
    OR r.caption ILIKE %s
    OR (
        enrichment.outcome = 'transcribed'
        AND NULLIF(btrim(enrichment.transcript_text), '') IS NOT NULL
        AND enrichment.transcript_text ILIKE %s
    )
    OR EXISTS (
        SELECT 1
        FROM app.reel_categories AS search_rc
        JOIN app.categories AS search_category
            ON search_category.id = search_rc.category_id
        WHERE search_rc.reel_id = r.id
          AND search_category.name ILIKE %s
    )
)
ORDER BY r.received_at DESC NULLS LAST, r.id DESC
LIMIT %s OFFSET %s
"""


def fetch_reels(page: int, search_term: str | None = None) -> tuple[list[dict], bool]:
    offset = (page - 1) * PAGE_SIZE
    pattern = f"%{search_term}%" if search_term is not None else None

    with (
        database.connect() as connection,
        connection.cursor(row_factory=dict_row) as cursor,
    ):
        cursor.execute(
            LIBRARY_QUERY,
            (
                search_term,
                pattern,
                pattern,
                pattern,
                pattern,
                PAGE_SIZE + 1,
                offset,
            ),
        )
        rows = cursor.fetchall()

    return rows[:PAGE_SIZE], len(rows) > PAGE_SIZE


def normalize_library_search(q: str | None) -> str:
    return q.strip() if q is not None else ""


def fetch_library_page(
    page: int,
    q: str | None,
) -> tuple[list[dict], bool, str]:
    search_term = normalize_library_search(q)
    reels, has_next = fetch_reels(page, search_term or None)
    return reels, has_next, search_term


def reel_library_projection(reel: dict) -> dict:
    return {
        "id": reel["id"],
        "title": reel.get("title"),
        "creator": reel.get("creator"),
        "shortcode": reel.get("shortcode"),
        "caption": reel.get("caption"),
        "categories": reel.get("categories") or [],
        "duration_seconds": reel.get("duration_seconds"),
        "received_at": reel.get("received_at"),
        "has_transcript": bool(reel.get("has_transcript")),
    }


class AssignCategoryRequest(BaseModel):
    category_id: int


class CreateCategoryRequest(BaseModel):
    name: str


class ReelCategoryResponse(BaseModel):
    id: int
    name: str


class ReelTranscriptResponse(BaseModel):
    available: bool
    text: str | None
    language: str | None
    completed_at: datetime | None


class ReelCategoriesResponse(BaseModel):
    assigned: list[ReelCategoryResponse]
    available: list[ReelCategoryResponse]


class ReelVideoResponse(BaseModel):
    available: bool
    src: str | None


class ReelDetailResponse(BaseModel):
    id: int
    title: str | None
    creator: str | None
    shortcode: str | None
    original_url: str | None
    status: str | None
    caption: str | None
    duration_seconds: float | None
    received_at: datetime | None
    downloaded_at: datetime | None
    filename: str | None
    mime_type: str | None
    file_size_bytes: int | None
    transcript: ReelTranscriptResponse
    categories: ReelCategoriesResponse
    video: ReelVideoResponse


def reel_detail_projection(
    reel: dict[str, Any],
    assigned_categories: list[dict[str, Any]],
    available_categories: list[dict[str, Any]],
) -> ReelDetailResponse:
    presentation = reel_detail_context(reel, None)
    transcript = presentation["transcript"]
    transcript_available = transcript is not None
    video_available = bool(reel.get("object_key"))

    return ReelDetailResponse(
        id=reel["id"],
        title=reel.get("title"),
        creator=reel.get("creator"),
        shortcode=reel.get("shortcode"),
        original_url=reel.get("original_url"),
        status=reel.get("status"),
        caption=reel.get("caption"),
        duration_seconds=presentation["duration"],
        received_at=reel.get("received_at"),
        downloaded_at=reel.get("downloaded_at"),
        filename=reel.get("filename"),
        mime_type=reel.get("mime_type"),
        file_size_bytes=reel.get("file_size_bytes"),
        transcript=ReelTranscriptResponse(
            available=transcript_available,
            text=transcript if transcript_available else None,
            language=reel.get("transcript_language") if transcript_available else None,
            completed_at=reel.get("enrichment_completed_at") if transcript_available else None,
        ),
        categories=ReelCategoriesResponse(
            assigned=[ReelCategoryResponse(id=category["id"], name=category["name"]) for category in assigned_categories],
            available=[ReelCategoryResponse(id=category["id"], name=category["name"]) for category in available_categories],
        ),
        video=ReelVideoResponse(
            available=video_available,
            src=f"/api/reels/{reel['id']}/video" if video_available else None,
        ),
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "healthy", "version": VERSION}


@app.get("/api/reels")
def reels_api(
    response: Response,
    page: int = Query(default=1, ge=1),
    q: str | None = Query(default=None),
    _owner=Depends(require_owner_session),
) -> dict:
    response.headers["Cache-Control"] = "no-store"

    try:
        reels, has_next, search_term = fetch_library_page(page, q)
    except Exception:  # noqa: BLE001 - HTTP boundary must hide database details.
        response.status_code = 503
        return {"detail": "Library temporarily unavailable"}

    return {
        "items": [reel_library_projection(reel) for reel in reels],
        "query": {"q": search_term},
        "pagination": {
            "page": page,
            "page_size": PAGE_SIZE,
            "has_previous": page > 1,
            "has_next": has_next,
        },
    }


@app.post("/api/reels/{reel_id}/categories", status_code=status.HTTP_204_NO_CONTENT)
def assign_reel_category_api(
    reel_id: int,
    payload: AssignCategoryRequest,
    _owner=Depends(require_owner_session),
    _csrf: None = Depends(require_api_csrf),
) -> Response:
    if not reel_exists(reel_id):
        raise HTTPException(status_code=404, detail="Reel not found")
    if not category_exists(payload.category_id):
        raise HTTPException(status_code=404, detail="Category not found")

    try:
        associate_category(reel_id, payload.category_id)
    except Exception:  # noqa: BLE001 - HTTP boundary must hide database details.
        raise HTTPException(status_code=503, detail="Category update temporarily unavailable") from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/api/reels/{reel_id}/categories/new", status_code=status.HTTP_204_NO_CONTENT)
def create_reel_category_api(
    reel_id: int,
    payload: CreateCategoryRequest,
    _owner=Depends(require_owner_session),
    _csrf: None = Depends(require_api_csrf),
) -> Response:
    normalized_name = payload.name.strip()
    if not normalized_name:
        raise HTTPException(status_code=422, detail="Category name must not be empty")
    if not reel_exists(reel_id):
        raise HTTPException(status_code=404, detail="Reel not found")

    try:
        create_and_associate_category(reel_id, normalized_name)
    except Exception:  # noqa: BLE001 - HTTP boundary must hide database details.
        raise HTTPException(status_code=503, detail="Category update temporarily unavailable") from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.delete("/api/reels/{reel_id}/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_reel_category_api(
    reel_id: int,
    category_id: int,
    _owner=Depends(require_owner_session),
    _csrf: None = Depends(require_api_csrf),
) -> Response:
    if not reel_exists(reel_id):
        raise HTTPException(status_code=404, detail="Reel not found")

    try:
        remove_category(reel_id, category_id)
    except Exception:  # noqa: BLE001 - HTTP boundary must hide database details.
        raise HTTPException(status_code=503, detail="Category update temporarily unavailable") from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get(
    "/api/reels/{reel_id}",
    response_model=ReelDetailResponse,
    responses={
        404: {"description": "Reel not found"},
        503: {"description": "Reel detail temporarily unavailable"},
    },
)
def reel_detail_api(
    reel_id: int,
    response: Response,
    _owner=Depends(require_owner_session),
) -> ReelDetailResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        reel = fetch_reel(reel_id)
    except Exception:  # noqa: BLE001 - HTTP boundary must hide database details.
        raise HTTPException(status_code=503, detail="Reel detail temporarily unavailable") from None

    if reel is None:
        raise HTTPException(status_code=404, detail="Reel not found")

    try:
        assigned_categories, available_categories = fetch_categories_for_reel(reel_id)
    except Exception:  # noqa: BLE001 - HTTP boundary must hide database details.
        raise HTTPException(status_code=503, detail="Reel detail temporarily unavailable") from None

    return reel_detail_projection(reel, assigned_categories, available_categories)


@app.get(
    "/api/reels/{reel_id}/video",
    status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    response_class=RedirectResponse,
    responses={
        404: {"description": "Reel not found"},
        503: {"description": "Video temporarily unavailable"},
    },
)
def reel_video_api(
    reel_id: int,
    _owner=Depends(require_owner_session),
) -> Response:
    try:
        reel = fetch_reel(reel_id)
    except Exception:  # noqa: BLE001 - HTTP boundary must hide database details.
        raise HTTPException(status_code=503, detail="Video temporarily unavailable") from None

    if reel is None:
        raise HTTPException(status_code=404, detail="Reel not found")

    signed_url = presigned_video_url(reel)
    if signed_url is None:
        raise HTTPException(status_code=503, detail="Video temporarily unavailable")

    redirect_response = RedirectResponse(signed_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    redirect_response.headers["Cache-Control"] = "no-store"
    return redirect_response
