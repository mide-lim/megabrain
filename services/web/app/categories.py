from __future__ import annotations

from psycopg.rows import dict_row

from app import database

REEL_EXISTS_QUERY = "SELECT 1 FROM app.reels WHERE id = %s"

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

FIND_CATEGORY_QUERY = """
SELECT id
FROM app.categories
WHERE lower(name) = lower(%s)
"""

REMOVE_CATEGORY_QUERY = """
DELETE FROM app.reel_categories
WHERE reel_id = %s AND category_id = %s
"""


def reel_exists(reel_id: int) -> bool:
    with database.connect() as connection, connection.cursor() as cursor:
        cursor.execute(REEL_EXISTS_QUERY, (reel_id,))
        return cursor.fetchone() is not None


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


def create_and_associate_category(reel_id: int, name: str) -> None:
    with database.connect() as connection, connection.cursor() as cursor:
        cursor.execute(INSERT_CATEGORY_QUERY, (name,))
        cursor.execute(FIND_CATEGORY_QUERY, (name,))
        category_id = cursor.fetchone()[0]
        cursor.execute(ASSOCIATE_CATEGORY_QUERY, (reel_id, category_id))


def remove_category(reel_id: int, category_id: int) -> None:
    with database.connect() as connection, connection.cursor() as cursor:
        cursor.execute(REMOVE_CATEGORY_QUERY, (reel_id, category_id))
