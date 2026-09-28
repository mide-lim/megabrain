from __future__ import annotations

from psycopg.rows import dict_row

from app import database


class CategoryNameConflict(Exception):
    """Raised when a global category name collides case-insensitively."""


REEL_EXISTS_QUERY = "SELECT 1 FROM app.reels WHERE id = %s"
CATEGORY_EXISTS_QUERY = "SELECT 1 FROM app.categories WHERE id = %s"

CATEGORIES_FOR_REEL_QUERY = """
SELECT
    c.id,
    c.name,
    (rc.reel_id IS NOT NULL) AS assigned
FROM app.categories AS c
LEFT JOIN app.reel_categories AS rc
    ON rc.category_id = c.id
   AND rc.reel_id = %s
ORDER BY lower(c.name), c.id
"""

CATEGORIES_QUERY = """
SELECT
    c.id,
    c.name,
    COUNT(rc.reel_id) AS reel_count
FROM app.categories AS c
LEFT JOIN app.reel_categories AS rc
    ON rc.category_id = c.id
GROUP BY c.id, c.name
ORDER BY lower(c.name), c.id
"""

CATEGORY_QUERY = """
SELECT
    c.id,
    c.name,
    COUNT(rc.reel_id) AS reel_count
FROM app.categories AS c
LEFT JOIN app.reel_categories AS rc
    ON rc.category_id = c.id
WHERE c.id = %s
GROUP BY c.id, c.name
"""

CATEGORY_REELS_QUERY = """
SELECT
    r.id,
    r.title,
    r.creator,
    r.shortcode,
    r.caption,
    r.duration_seconds,
    r.download_status,
    r.curation_status,
    r.transcription_status,
    r.received_at,
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
WHERE EXISTS (
    SELECT 1
    FROM app.reel_categories AS filter_rc
    WHERE filter_rc.reel_id = r.id
      AND filter_rc.category_id = %s
)
ORDER BY r.received_at DESC NULLS LAST, r.id DESC
LIMIT %s OFFSET %s
"""

ASSOCIATE_CATEGORY_QUERY = """
INSERT INTO app.reel_categories (reel_id, category_id)
SELECT r.id, c.id
FROM app.reels AS r
CROSS JOIN app.categories AS c
WHERE r.id = %s AND c.id = %s
ON CONFLICT (reel_id, category_id) DO NOTHING
"""

INSERT_CATEGORY_QUERY = """
INSERT INTO app.categories (name)
VALUES (%s)
ON CONFLICT (lower(name)) DO NOTHING
"""

CREATE_CATEGORY_QUERY = """
INSERT INTO app.categories (name)
VALUES (%s)
ON CONFLICT (lower(name)) DO NOTHING
RETURNING id, name
"""

FIND_CATEGORY_QUERY = """
SELECT id
FROM app.categories
WHERE lower(name) = lower(%s)
"""

RENAME_CATEGORY_QUERY = """
UPDATE app.categories
SET name = %s
WHERE id = %s
  AND NOT EXISTS (
      SELECT 1
      FROM app.categories AS other
      WHERE other.id <> %s
        AND lower(other.name) = lower(%s)
  )
RETURNING id, name
"""

DELETE_CATEGORY_QUERY = """
DELETE FROM app.categories
WHERE id = %s
RETURNING id, name
"""

REMOVE_CATEGORY_QUERY = """
DELETE FROM app.reel_categories
WHERE reel_id = %s AND category_id = %s
"""


def reel_exists(reel_id: int) -> bool:
    with database.connect() as connection, connection.cursor() as cursor:
        cursor.execute(REEL_EXISTS_QUERY, (reel_id,))
        return cursor.fetchone() is not None


def category_exists(category_id: int) -> bool:
    with database.connect() as connection, connection.cursor() as cursor:
        cursor.execute(CATEGORY_EXISTS_QUERY, (category_id,))
        return cursor.fetchone() is not None


def fetch_categories() -> list[dict]:
    with (
        database.connect() as connection,
        connection.cursor(row_factory=dict_row) as cursor,
    ):
        cursor.execute(CATEGORIES_QUERY)
        return cursor.fetchall()


def fetch_category(category_id: int) -> dict | None:
    with (
        database.connect() as connection,
        connection.cursor(row_factory=dict_row) as cursor,
    ):
        cursor.execute(CATEGORY_QUERY, (category_id,))
        return cursor.fetchone()


def fetch_category_reels(
    category_id: int,
    page: int,
    page_size: int,
) -> tuple[list[dict], bool]:
    offset = (page - 1) * page_size
    with (
        database.connect() as connection,
        connection.cursor(row_factory=dict_row) as cursor,
    ):
        cursor.execute(
            CATEGORY_REELS_QUERY,
            (category_id, page_size + 1, offset),
        )
        rows = cursor.fetchall()
    return rows[:page_size], len(rows) > page_size


def fetch_categories_for_reel(reel_id: int) -> tuple[list[dict], list[dict]]:
    with (
        database.connect() as connection,
        connection.cursor(row_factory=dict_row) as cursor,
    ):
        cursor.execute(CATEGORIES_FOR_REEL_QUERY, (reel_id,))
        categories = cursor.fetchall()

    assigned = [category for category in categories if category["assigned"]]
    available = [category for category in categories if not category["assigned"]]
    return assigned, available


def associate_category(reel_id: int, category_id: int) -> None:
    with database.connect() as connection, connection.cursor() as cursor:
        cursor.execute(ASSOCIATE_CATEGORY_QUERY, (reel_id, category_id))


def create_category(name: str) -> dict:
    with (
        database.connect() as connection,
        connection.cursor(row_factory=dict_row) as cursor,
    ):
        cursor.execute(CREATE_CATEGORY_QUERY, (name,))
        category = cursor.fetchone()
        if category is None:
            raise CategoryNameConflict(name)
        return category


def rename_category(category_id: int, name: str) -> dict | None:
    with (
        database.connect() as connection,
        connection.cursor(row_factory=dict_row) as cursor,
    ):
        cursor.execute(
            RENAME_CATEGORY_QUERY,
            (name, category_id, category_id, name),
        )
        category = cursor.fetchone()
        if category is not None:
            return category

        cursor.execute(CATEGORY_EXISTS_QUERY, (category_id,))
        if cursor.fetchone() is not None:
            raise CategoryNameConflict(name)
        return None


def delete_category(category_id: int) -> dict | None:
    with (
        database.connect() as connection,
        connection.cursor(row_factory=dict_row) as cursor,
    ):
        cursor.execute(DELETE_CATEGORY_QUERY, (category_id,))
        return cursor.fetchone()


def create_and_associate_category(reel_id: int, name: str) -> None:
    with database.connect() as connection, connection.cursor() as cursor:
        cursor.execute(INSERT_CATEGORY_QUERY, (name,))
        cursor.execute(FIND_CATEGORY_QUERY, (name,))
        category_id = cursor.fetchone()[0]
        cursor.execute(ASSOCIATE_CATEGORY_QUERY, (reel_id, category_id))


def remove_category(reel_id: int, category_id: int) -> None:
    with database.connect() as connection, connection.cursor() as cursor:
        cursor.execute(REMOVE_CATEGORY_QUERY, (reel_id, category_id))
