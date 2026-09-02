from __future__ import annotations

import hmac
import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from psycopg.rows import dict_row
from starlette.templating import Jinja2Templates

from app import database
from app.categories import (
    associate_category,
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
APP_DIR = Path(__file__).parent

CSRF_COOKIE_NAME = "__Host-csrf_token"
CSRF_TOKEN_BYTES = 32


def _csrf_token(request: Request) -> tuple[str, bool]:
    existing = request.cookies.get(CSRF_COOKIE_NAME)

    if existing:
        return existing, False

    return secrets.token_urlsafe(CSRF_TOKEN_BYTES), True


app = FastAPI(title="MegaBrain Web", version=VERSION)
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
templates = Jinja2Templates(directory=APP_DIR / "templates")


LIBRARY_QUERY = """
SELECT
    r.id,
    r.creator,
    r.shortcode,
    r.caption,
    r.status,
    r.received_at,
    r.downloaded_at,
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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "healthy", "version": VERSION}


@app.get("/", response_class=HTMLResponse)
def library(
    request: Request,
    page: int = Query(default=1, ge=1),
    q: str | None = Query(default=None),
) -> HTMLResponse:
    search_term = q.strip() if q is not None else ""
    normalized_search = search_term or None

    try:
        reels, has_next = fetch_reels(page, normalized_search)
    except Exception:  # noqa: BLE001 - HTTP boundary must hide database details.
        return templates.TemplateResponse(
            request=request,
            name="library.html",
            context={
                "reels": [],
                "page": page,
                "has_next": False,
                "error": True,
                "q": search_term,
            },
            status_code=503,
        )

    return templates.TemplateResponse(
        request=request,
        name="library.html",
        context={
            "reels": reels,
            "page": page,
            "has_next": has_next,
            "error": False,
            "q": search_term,
        },
    )


@app.get("/reels/{reel_id}", response_class=HTMLResponse)
def reel_detail(
    request: Request,
    reel_id: int,
    curation_error: str | None = None,
) -> HTMLResponse:
    try:
        reel = fetch_reel(reel_id)
    except Exception:  # noqa: BLE001 - HTTP boundary must hide database details.
        return templates.TemplateResponse(
            request=request,
            name="reel_detail.html",
            context={"error": True},
            status_code=503,
        )

    if reel is None:
        return templates.TemplateResponse(
            request=request,
            name="reel_detail.html",
            context={"missing": True},
            status_code=404,
        )

    try:
        assigned_categories, available_categories = fetch_categories_for_reel(
            reel_id
        )
    except Exception:  # noqa: BLE001 - HTTP boundary must hide database details.
        return templates.TemplateResponse(
            request=request,
            name="reel_detail.html",
            context={"error": True},
            status_code=503,
        )

    csrf_token, set_csrf_cookie = _csrf_token(request)

    context = reel_detail_context(reel, presigned_video_url(reel))
    context.update(
        {
            "assigned_categories": assigned_categories,
            "available_categories": available_categories,
            "curation_error": curation_error,
            "csrf_token": csrf_token,
        }
    )

    response = templates.TemplateResponse(
        request=request,
        name="reel_detail.html",
        context=context,
    )

    if set_csrf_cookie:
        response.set_cookie(
            CSRF_COOKIE_NAME,
            csrf_token,
            secure=True,
            httponly=True,
            samesite="lax",
            path="/",
        )

    return response


def _reel_redirect(
    reel_id: int,
    error: str | None = None,
) -> RedirectResponse:
    suffix = f"?curation_error={error}" if error else ""

    return RedirectResponse(
        f"/reels/{reel_id}{suffix}",
        status_code=303,
    )


def _missing_reel_response(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="reel_detail.html",
        context={"missing": True},
        status_code=404,
    )


def _require_csrf(
    request: Request,
    csrf_token: str | None = Form(default=None),
) -> None:
    cookie_token = request.cookies.get(CSRF_COOKIE_NAME)

    valid = bool(
        cookie_token
        and csrf_token
        and hmac.compare_digest(cookie_token, csrf_token)
    )

    if not valid:
        raise HTTPException(
            status_code=403,
            detail="CSRF token validation failed",
        )


@app.post("/reels/{reel_id}/categories")
def add_reel_category(
    request: Request,
    reel_id: int,
    category_id: int = Form(),
    _csrf: None = Depends(_require_csrf),
) -> Response:
    try:
        if not reel_exists(reel_id):
            return _missing_reel_response(request)

        associate_category(reel_id, category_id)

    except Exception:  # noqa: BLE001 - HTTP boundary must hide database details.
        return _reel_redirect(reel_id, "database")

    return _reel_redirect(reel_id)


@app.post("/reels/{reel_id}/categories/new")
def create_reel_category(
    request: Request,
    reel_id: int,
    name: str = Form(),
    _csrf: None = Depends(_require_csrf),
) -> Response:
    normalized_name = name.strip()

    try:
        if not reel_exists(reel_id):
            return _missing_reel_response(request)

        if not normalized_name:
            return _reel_redirect(reel_id, "empty-name")

        create_and_associate_category(reel_id, normalized_name)

    except Exception:  # noqa: BLE001 - HTTP boundary must hide database details.
        return _reel_redirect(reel_id, "database")

    return _reel_redirect(reel_id)


@app.post("/reels/{reel_id}/categories/{category_id}/remove")
def remove_reel_category(
    request: Request,
    reel_id: int,
    category_id: int,
    _csrf: None = Depends(_require_csrf),
) -> Response:
    try:
        if not reel_exists(reel_id):
            return _missing_reel_response(request)

        remove_category(reel_id, category_id)

    except Exception:  # noqa: BLE001 - HTTP boundary must hide database details.
        return _reel_redirect(reel_id, "database")

    return _reel_redirect(reel_id)
