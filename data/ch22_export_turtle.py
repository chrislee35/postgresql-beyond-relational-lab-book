#!/usr/bin/env python3.12
"""Export a slice of the live Portsmith DB (neighborhoods, their real
ST_Touches-derived adjacency, and businesses) as RDF triples in Turtle
syntax, for Chapter 22's pg-ripple exercises. Reads from the main
PostgreSQL 16 database (portsmith); writes a .ttl file meant to be
loaded into the isolated PostgreSQL 18 / pg-ripple container via
pg_ripple.load_turtle().
"""
import re
import sys

import psycopg

DSN = sys.argv[1] if len(sys.argv) > 1 else "dbname=portsmith"
OUT = sys.argv[2] if len(sys.argv) > 2 else "ch22_portsmith.ttl"


def slug(name: str) -> str:
    s = name.lower().replace("&", "and")
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s


def turtle_string(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def main() -> None:
    lines = [
        "@prefix : <http://portsmith.example.org/> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
        "",
        ':portsmith a :City ; rdfs:label "Portsmith" .',
        "",
    ]

    with psycopg.connect(DSN) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, population FROM neighborhoods ORDER BY id;")
            neighborhoods = cur.fetchall()

            cur.execute(
                """
                SELECT a.name, b.name
                FROM neighborhoods a
                JOIN neighborhoods b ON a.id < b.id AND ST_Touches(a.geom, b.geom)
                ORDER BY 1, 2;
                """
            )
            adjacency = cur.fetchall()

            cur.execute(
                """
                SELECT id, name, neighbourhood,
                       details->>'category' AS category,
                       details->>'subcategory' AS subcategory
                FROM businesses
                ORDER BY id;
                """
            )
            businesses = cur.fetchall()

    lines.append("# Neighborhoods -- real rows from Chapter 2's neighborhoods table")
    for _id, name, population in neighborhoods:
        iri = slug(name)
        lines.append(
            f':{iri} a :Neighborhood ; rdfs:label "{turtle_string(name)}" ; '
            f":population {population} ; :partOf :portsmith ."
        )
    lines.append("")

    lines.append(
        "# Adjacency -- real ST_Touches results against Chapter 2's polygons, "
        "one direction per touching pair"
    )
    for n1, n2 in adjacency:
        lines.append(f":{slug(n1)} :adjacentTo :{slug(n2)} .")
    lines.append("")

    lines.append("# Businesses -- real rows from Chapter 1's businesses table")
    for biz_id, name, neighbourhood, category, subcategory in businesses:
        parts = [
            f":business_{biz_id} a :Business",
            f'rdfs:label "{turtle_string(name)}"',
            f":locatedIn :{slug(neighbourhood)}",
        ]
        if category:
            parts.append(f':hasCategory "{turtle_string(category)}"')
        if subcategory:
            parts.append(f':hasSubcategory "{turtle_string(subcategory)}"')
        lines.append(" ; ".join(parts) + " .")

    with open(OUT, "w") as f:
        f.write("\n".join(lines) + "\n")

    print(f"Wrote {len(neighborhoods)} neighborhoods, {len(adjacency)} adjacency "
          f"edges, {len(businesses)} businesses to {OUT}")


if __name__ == "__main__":
    main()
