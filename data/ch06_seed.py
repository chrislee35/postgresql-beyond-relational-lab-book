#!/usr/bin/env python3.12
"""
Chapter 6 seed data — Portsmith Vector Search.

Adds an `embedding vector(384)` column to `city_documents` (left NULL here —
populate it by running ch06_embed_documents.py, which uses a real
sentence-transformer model) and creates `city_photos`: a synthetic,
much larger table of clustered 384-dimensional vectors standing in for
image embeddings from a photo library. There is no real photo content
behind city_photos — each row's vector is a random point drawn from one of
ten category clusters, purely so the ANN-indexing exercises (IVFFlat,
HNSW) have enough rows and enough real cluster structure to be worth
indexing at all, which 30 documents never would be.

Requires: Chapter 4 seed (ch04_seed.py) to have been run first so that the
          `city_documents` table exists.
Requires: the pgvector extension enabled on the database (superuser-only
          on pgvector < 0.7 — see the chapter's Installation section):
              sudo -u postgres psql portsmith -c "CREATE EXTENSION vector;"

Usage:
    python ch06_seed.py [DSN]

    DSN defaults to "dbname=portsmith".
"""

import sys

import numpy as np
import psycopg
from pgvector.psycopg import register_vector

DSN = sys.argv[1] if len(sys.argv) > 1 else "dbname=portsmith"

DIM = 384
PHOTOS_PER_CATEGORY = 500
# Larger value = tighter, more separable clusters (easier for ANN indexes);
# smaller value = fuzzier clusters, closer to how real embeddings behave.
CLUSTER_CONCENTRATION = 6.0

NEIGHBOURHOODS = [
    "Harbour District",
    "Industrial Port",
    "Northgate",
    "Old Town",
    "Riverside",
    "University Quarter",
]

# ---------------------------------------------------------------------------
# Ten synthetic photo categories. Each gets a random unit-vector "anchor"
# in 384-dimensional space; every photo in that category is a random point
# clustered around its category's anchor. Real image embedding models
# (e.g. CLIP) produce exactly this kind of structure — photos of similar
# subjects land near each other in vector space — so this reproduces the
# *shape* of the problem ANN indexes solve without needing real photos or
# a vision model.
# ---------------------------------------------------------------------------

CATEGORIES = [
    "harbour_waterfront",
    "historic_architecture",
    "public_park",
    "street_market",
    "municipal_building",
    "residential_street",
    "industrial_dock",
    "wildlife_nature",
    "infrastructure_construction",
    "community_event",
]

DDL = """
ALTER TABLE city_documents ADD COLUMN IF NOT EXISTS embedding vector(384);

DROP TABLE IF EXISTS city_photos CASCADE;

CREATE TABLE city_photos (
    id            SERIAL PRIMARY KEY,
    category      TEXT NOT NULL,
    neighbourhood TEXT NOT NULL,
    caption       TEXT NOT NULL,
    embedding     vector(384) NOT NULL
);
"""


def make_category_vectors(rng: np.random.Generator) -> dict[str, np.ndarray]:
    return {cat: rng.normal(size=DIM) for cat in CATEGORIES}


def make_photo_embedding(rng: np.random.Generator, anchor: np.ndarray) -> np.ndarray:
    noise = rng.normal(size=DIM) / CLUSTER_CONCENTRATION
    vec = anchor + noise
    return vec / np.linalg.norm(vec)


def main() -> None:
    print(f"Connecting to: {DSN}")
    with psycopg.connect(DSN) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('city_documents')")
            (city_documents_exists,) = cur.fetchone()
            if city_documents_exists is None:
                sys.exit(
                    "ERROR: the 'city_documents' table does not exist. "
                    "Run `python data/ch04_seed.py` first."
                )
            cur.execute("SELECT to_regtype('vector')")
            (vector_type_exists,) = cur.fetchone()
            if vector_type_exists is None:
                sys.exit(
                    "ERROR: the pgvector extension is not enabled. Run:\n"
                    '  sudo -u postgres psql portsmith -c "CREATE EXTENSION vector;"'
                )
            cur.execute("""
                SELECT 1 FROM information_schema.columns
                WHERE  table_name = 'city_documents' AND column_name = 'search_vector'
            """)
            if cur.fetchone() is None:
                sys.exit(
                    "ERROR: city_documents.search_vector does not exist. Chapter 6's "
                    "hybrid-search exercise needs it, but it's created by hand in "
                    "Chapter 4's Exercise 3 -- ch04_seed.py alone does not add it "
                    "(and re-running ch04_seed.py drops it if you already had it). "
                    "Run this once to restore it:\n\n"
                    "  ALTER TABLE city_documents ADD COLUMN search_vector tsvector;\n"
                    "  UPDATE city_documents SET search_vector = "
                    "to_tsvector('english', title || ' ' || body);\n"
                    "  CREATE OR REPLACE FUNCTION city_documents_search_vector_update() "
                    "RETURNS trigger AS $$\n"
                    "  BEGIN\n"
                    "      NEW.search_vector := to_tsvector('english', NEW.title || ' ' || NEW.body);\n"
                    "      RETURN NEW;\n"
                    "  END;\n"
                    "  $$ LANGUAGE plpgsql;\n"
                    "  CREATE TRIGGER trg_city_documents_search_vector\n"
                    "      BEFORE INSERT OR UPDATE OF title, body ON city_documents\n"
                    "      FOR EACH ROW EXECUTE FUNCTION city_documents_search_vector_update();\n"
                    "  CREATE INDEX idx_city_documents_search_vector\n"
                    "      ON city_documents USING GIN (search_vector);"
                )

        register_vector(conn)

        with conn.cursor() as cur:
            print("Applying DDL …")
            cur.execute(DDL)

            rng = np.random.default_rng(42)
            category_anchors = make_category_vectors(rng)

            total = len(CATEGORIES) * PHOTOS_PER_CATEGORY
            print(f"Generating {total} synthetic photo embeddings …")
            rows = []
            for category in CATEGORIES:
                anchor = category_anchors[category]
                for i in range(PHOTOS_PER_CATEGORY):
                    embedding = make_photo_embedding(rng, anchor)
                    neighbourhood = NEIGHBOURHOODS[rng.integers(len(NEIGHBOURHOODS))]
                    caption = f"{category.replace('_', ' ')} photo #{i + 1}"
                    rows.append((category, neighbourhood, caption, embedding))

            with cur.copy(
                "COPY city_photos (category, neighbourhood, caption, embedding) FROM STDIN"
            ) as copy:
                for row in rows:
                    copy.write_row(row)

            cur.execute("SELECT COUNT(*) FROM city_photos")
            (photo_count,) = cur.fetchone()
            print(f"Done — {photo_count} rows in city_photos across {len(CATEGORIES)} categories.")
            print(
                "city_documents.embedding added but left NULL — "
                "run `python data/ch06_embed_documents.py` next."
            )

        conn.commit()


if __name__ == "__main__":
    main()
