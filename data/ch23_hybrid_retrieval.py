#!/usr/bin/env python3.12
"""Chapter 23 -- hybrid retrieval: Chapter 6's pgvector semantic search
(live PostgreSQL 16, city_documents) combined with the Chapter 22/23
RDF graph (PostgreSQL 18 / pg-ripple container) to find not just a
relevant policy document, but the specific real businesses it actually
affects. Two independent queries, joined in Python -- the graph query
composes rdfs:subClassOf* and the adjacentTo property path directly,
deliberately not through pg_ripple.infer('rdfs'), which this chapter
found corrupts stored rdf:type facts rather than just failing to add
new ones.

Usage:
    python3.12 data/ch23_hybrid_retrieval.py "food truck vendor permits near restaurants"
"""
import sys

import psycopg
from pgvector.psycopg import register_vector
from sentence_transformers import SentenceTransformer

MODEL_NAME = "all-MiniLM-L6-v2"
PG16_DSN = "dbname=portsmith"
PG18_DSN = "host=localhost port=5434 user=chris password=ch22-scratch dbname=portsmith22"


def top_document(query: str):
    model = SentenceTransformer(MODEL_NAME)
    qvec = model.encode(query)
    with psycopg.connect(PG16_DSN) as conn:
        register_vector(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT title, department, 1 - (embedding <=> %s) AS score
                FROM city_documents ORDER BY embedding <=> %s LIMIT 1;
                """,
                (qvec, qvec),
            )
            return cur.fetchone()


def affected_businesses(neighborhood_iri: str, category_iri: str):
    with psycopg.connect(PG18_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT * FROM pg_ripple.sparql(
                    'PREFIX : <http://portsmith.example.org/> '
                    'PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> '
                    'SELECT ?t WHERE { ?t rdfs:subClassOf* %s . }'
                );""" % f"<{category_iri}>"
            )
            in_category = {row[0]["t"].strip("<>") for row in cur.fetchall()}

            cur.execute(
                """SELECT * FROM pg_ripple.sparql(
                    'PREFIX : <http://portsmith.example.org/> '
                    'SELECT ?n WHERE { %s (:adjacentTo|^:adjacentTo)* ?n . }'
                );""" % f"<{neighborhood_iri}>"
            )
            in_area = {row[0]["n"].strip("<>") for row in cur.fetchall()}

            cur.execute(
                """SELECT * FROM pg_ripple.sparql(
                    'PREFIX : <http://portsmith.example.org/> '
                    'PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> '
                    'SELECT ?bizLabel ?t ?n WHERE { ?b a ?t ; rdfs:label ?bizLabel ; :locatedIn ?n . }'
                );"""
            )
            return sorted({
                row[0]["bizLabel"].strip('"')
                for row in cur.fetchall()
                if row[0]["t"].strip("<>") in in_category and row[0]["n"].strip("<>") in in_area
            })


def main() -> None:
    query = sys.argv[1] if len(sys.argv) > 1 else "food truck vendor permits near restaurants"

    title, department, score = top_document(query)
    print(f"Top semantic match ({score:.3f}): {title!r} [{department}]")

    businesses = affected_businesses(
        "http://portsmith.example.org/harbour_district",
        "http://portsmith.example.org/Category_restaurant",
    )
    print(f"\nBusinesses actually affected (restaurant category, Harbour District or adjacent): {len(businesses)}")
    for name in businesses:
        print(" -", name)


if __name__ == "__main__":
    main()
