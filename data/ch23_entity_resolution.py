#!/usr/bin/env python3.12
"""Chapter 23 -- entity resolution head-to-head: Chapter 5's pg_trgm
trigram similarity vs. pg-ripple's CLK Bloom-filter dice_similarity,
run against the same real ground truth: the 12 genuine duplicate
resident pairs Chapter 5 seeded (residents.true_duplicate_of).

Usage:
    python3.12 data/ch23_entity_resolution.py
"""
import psycopg

PG16_DSN = "dbname=portsmith"
PG18_DSN = "host=localhost port=5434 user=chris password=ch22-scratch dbname=portsmith22"


def main() -> None:
    with psycopg.connect(PG16_DSN, autocommit=True) as pg16:
        with pg16.cursor() as cur:
            cur.execute(
                """
                SELECT a.full_name, b.full_name
                FROM residents a JOIN residents b ON b.true_duplicate_of = a.id
                ORDER BY a.id;
                """
            )
            pairs = cur.fetchall()

    print(f"{'name a':<24} {'name b':<24} {'pg_trgm':>8} {'ripple dice':>12}")
    with psycopg.connect(PG16_DSN, autocommit=True) as pg16, \
         psycopg.connect(PG18_DSN, autocommit=True) as pg18:
        with pg16.cursor() as c16, pg18.cursor() as c18:
            for a, b in pairs:
                c16.execute("SELECT similarity(%s, %s);", (a, b))
                trgm = c16.fetchone()[0]
                c18.execute(
                    "SELECT pg_ripple.dice_similarity("
                    "pg_ripple.bloom_encode(%s,'name'), pg_ripple.bloom_encode(%s,'name'));",
                    (a, b),
                )
                dice = c18.fetchone()[0]
                print(f"{a:<24} {b:<24} {trgm:>8.3f} {dice:>12.3f}")


if __name__ == "__main__":
    main()
