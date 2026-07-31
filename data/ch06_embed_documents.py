#!/usr/bin/env python3.12
"""
Chapter 6 — embed city_documents with a real sentence-transformer model.

Computes a 384-dimensional embedding for every row in city_documents using
all-MiniLM-L6-v2 (https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2),
run locally on CPU, and stores it in the `embedding` column added by
ch06_seed.py. This is the one script in the chapter with a heavy dependency
(sentence-transformers, and therefore torch) — see the chapter's
Installation section for the CPU-only install command. Nothing else in
Chapter 6 needs it: city_photos' embeddings are synthetic and every query
exercise only needs pgvector and psycopg.

The model embeds `title` and `body` concatenated, matching the same
"index the title too" reasoning as the tsvector column in Chapter 4.

Requires: ch06_seed.py to have been run first (adds the `embedding` column).

Usage:
    python ch06_embed_documents.py [DSN]

    DSN defaults to "dbname=portsmith".
"""

import sys

import psycopg
from pgvector.psycopg import register_vector
from sentence_transformers import SentenceTransformer

DSN = sys.argv[1] if len(sys.argv) > 1 else "dbname=portsmith"
MODEL_NAME = "all-MiniLM-L6-v2"


def main() -> None:
    print(f"Connecting to: {DSN}")
    with psycopg.connect(DSN) as conn:
        register_vector(conn)

        with conn.cursor() as cur:
            cur.execute("SELECT id, title, body FROM city_documents ORDER BY id")
            rows = cur.fetchall()

        print(f"Loading {MODEL_NAME} (first run downloads ~90MB of model weights) …")
        model = SentenceTransformer(MODEL_NAME)

        print(f"Embedding {len(rows)} documents …")
        texts = [f"{title}. {body}" for _id, title, body in rows]
        embeddings = model.encode(texts, show_progress_bar=False, normalize_embeddings=True)

        with conn.cursor() as cur:
            for (doc_id, _title, _body), embedding in zip(rows, embeddings):
                cur.execute(
                    "UPDATE city_documents SET embedding = %s WHERE id = %s",
                    (embedding, doc_id),
                )

        conn.commit()
        print(f"Done — {len(rows)} rows in city_documents now have an embedding.")


if __name__ == "__main__":
    main()
