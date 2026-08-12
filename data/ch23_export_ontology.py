#!/usr/bin/env python3.12
"""Export Chapter 12's real categories tree (48 rows, 3 levels) as an
RDFS class hierarchy, and classify each Chapter 1 business as an
instance of its most specific category class. Written for Chapter 23's
ontology exercises -- layers formal class semantics on top of Chapter
22's flat :hasCategory string literals, over the same pg-ripple
container.
"""
import re
import sys

import psycopg

DSN = sys.argv[1] if len(sys.argv) > 1 else "dbname=portsmith"
OUT = sys.argv[2] if len(sys.argv) > 2 else "ch23_ontology.ttl"


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def main() -> None:
    lines = [
        "@prefix : <http://portsmith.example.org/> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "",
    ]

    with psycopg.connect(DSN) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, parent_id FROM categories ORDER BY id;")
            categories = cur.fetchall()

            cur.execute(
                """
                SELECT id, details->>'category' AS category,
                       COALESCE(details->>'subcategory', details->>'cuisine') AS leaf
                FROM businesses ORDER BY id;
                """
            )
            businesses = cur.fetchall()

    by_id = {cid: (name, parent_id) for cid, name, parent_id in categories}

    lines.append("# Category class hierarchy -- real rows from Chapter 12's categories table")
    for cid, name, parent_id in categories:
        cls = f"Category_{slug(name)}"
        head = f':{cls} a rdfs:Class ; rdfs:label "{name}"'
        if parent_id is not None:
            parent_name, _ = by_id[parent_id]
            lines.append(f"{head} ; rdfs:subClassOf :Category_{slug(parent_name)} .")
        else:
            lines.append(f"{head} .")
    lines.append("")

    # top-level category name -> its category row id, for scoping leaf lookups
    top_by_name = {name: cid for cid, name, parent_id in categories if parent_id == 1}
    # (parent_id, leaf_name) -> category row, to disambiguate names reused
    # under different parents (e.g. "pub" exists under both restaurant and
    # entertainment)
    leaf_by_parent_and_name = {
        (parent_id, name): cid for cid, name, parent_id in categories
    }

    lines.append("# Business classification -- most specific real category each business has")
    unmatched = 0
    for biz_id, category, leaf in businesses:
        cls_id = None
        if category and category in top_by_name:
            top_id = top_by_name[category]
            if leaf:
                cls_id = leaf_by_parent_and_name.get((top_id, leaf))
            if cls_id is None:
                cls_id = top_id
        if cls_id is None:
            unmatched += 1
            continue
        cls_name, _ = by_id[cls_id]
        lines.append(f":business_{biz_id} a :Category_{slug(cls_name)} .")

    with open(OUT, "w") as f:
        f.write("\n".join(lines) + "\n")

    print(f"Wrote {len(categories)} category classes, "
          f"{len(businesses) - unmatched} business classifications "
          f"({unmatched} unmatched) to {OUT}")


if __name__ == "__main__":
    main()
