#!/usr/bin/env python3.12
"""
Chapter 6 — semantic and hybrid search over city_documents.

Embeds a query string with the same all-MiniLM-L6-v2 model used to build
the embedding column (ch06_embed_documents.py) and finds the closest
documents by cosine distance. With --hybrid, also blends in the
Chapter 4 keyword score (ts_rank) for a combined ranking.

Usage:
    python ch06_semantic_search.py "waterfront redevelopment funding"
    python ch06_semantic_search.py "bike lane" --hybrid
    python ch06_semantic_search.py "bike lane" --hybrid --kw-weight 0.4 --top 8

    DSN defaults to "dbname=portsmith"; override with --dsn.
"""

import argparse

import psycopg
from pgvector.psycopg import register_vector
from sentence_transformers import SentenceTransformer

MODEL_NAME = "all-MiniLM-L6-v2"

SEMANTIC_SQL = """
SELECT id, title, 1 - (embedding <=> %(qvec)s) AS sem_score
FROM   city_documents
ORDER  BY embedding <=> %(qvec)s
LIMIT  %(top)s
"""

HYBRID_SQL = """
WITH keyword AS (
    SELECT id, ts_rank(search_vector, plainto_tsquery('english', %(query)s)) AS kw_score
    FROM   city_documents
    WHERE  search_vector @@ plainto_tsquery('english', %(query)s)
),
semantic AS (
    SELECT id, 1 - (embedding <=> %(qvec)s) AS sem_score
    FROM   city_documents
    ORDER  BY embedding <=> %(qvec)s
    LIMIT  %(top)s
)
SELECT d.id, d.title,
       COALESCE(k.kw_score, 0)  AS kw_score,
       COALESCE(s.sem_score, 0) AS sem_score,
       %(kw_weight)s * COALESCE(k.kw_score, 0) + %(sem_weight)s * COALESCE(s.sem_score, 0) AS hybrid_score
FROM   city_documents d
LEFT JOIN keyword  k ON k.id = d.id
LEFT JOIN semantic s ON s.id = d.id
WHERE  k.id IS NOT NULL OR s.id IS NOT NULL
ORDER  BY hybrid_score DESC
LIMIT  %(top)s
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query")
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--hybrid", action="store_true")
    parser.add_argument("--kw-weight", type=float, default=0.4)
    parser.add_argument("--dsn", default="dbname=portsmith")
    args = parser.parse_args()

    model = SentenceTransformer(MODEL_NAME)
    qvec = model.encode(args.query, normalize_embeddings=True)

    with psycopg.connect(args.dsn) as conn:
        register_vector(conn)
        with conn.cursor() as cur:
            if args.hybrid:
                cur.execute(
                    HYBRID_SQL,
                    {
                        "query": args.query,
                        "qvec": qvec,
                        "top": args.top,
                        "kw_weight": args.kw_weight,
                        "sem_weight": 1 - args.kw_weight,
                    },
                )
                print(f"{'id':>4}  {'kw':>7}  {'sem':>7}  {'hybrid':>7}  title")
                for doc_id, title, kw, sem, hybrid in cur.fetchall():
                    print(f"{doc_id:>4}  {kw:>7.4f}  {sem:>7.4f}  {hybrid:>7.4f}  {title}")
            else:
                cur.execute(SEMANTIC_SQL, {"qvec": qvec, "top": args.top})
                print(f"{'id':>4}  {'sim':>7}  title")
                for doc_id, title, sim in cur.fetchall():
                    print(f"{doc_id:>4}  {sim:>7.4f}  {title}")


if __name__ == "__main__":
    main()
