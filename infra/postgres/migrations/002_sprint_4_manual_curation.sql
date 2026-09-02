-- Sprint 4 manual category curation.

CREATE TABLE app.categories (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL
        CHECK (btrim(name) <> '')
        CHECK (name !~'^[[:space:]]|[[:space:]]$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX categories_name_lower_unique_idx
    ON app.categories (lower(name));

CREATE TABLE app.reel_categories (
    reel_id BIGINT NOT NULL REFERENCES app.reels(id) ON DELETE CASCADE,
    category_id BIGINT NOT NULL REFERENCES app.categories(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (reel_id, category_id)
);

CREATE INDEX reel_categories_category_id_idx
    ON app.reel_categories (category_id);
