#!/usr/bin/env python3.12
"""
Chapter 12 seed data — Portsmith Org Chart, Road Graph, and Category Tree.

Creates three self-contained hierarchical/graph structures for recursive
CTE exercises:

  - city_org       : Portsmith's city government org chart (a tree,
                      self-referencing via manager_id)
  - intersections,
    road_segments   : the road network from Chapter 2's `city_infrastructure`
                      turned into a graph — every node here is a *real*
                      intersection point computed with ST_Intersects /
                      ST_LineLocatePoint against Chapter 2's actual
                      geometry, and every edge length is a real
                      along-road distance (ST_LineSubstring + ST_Length),
                      not a straight-line approximation. Ring Road bends
                      around three sides of the city between some of its
                      intersections, so a straight-line distance would
                      have been wrong for several edges — this data was
                      derived directly from Chapter 2's live geometry,
                      not hand-estimated.
  - categories     : a 3-level category tree ("All Categories" -> the 5
                      real business categories from Chapter 1 -> their
                      real subcategories/cuisines), for the faceted-search
                      ancestor-walk exercise.

Requires: Chapter 1's seed script (ch01_seed.py) and Chapter 2's seed
          script (ch02_seed.py) to have been run first.

Usage:
    python ch12_seed.py [DSN]

    DSN defaults to "dbname=portsmith".
"""

import sys

import psycopg

DSN = sys.argv[1] if len(sys.argv) > 1 else "dbname=portsmith"

DDL = """
DROP TABLE IF EXISTS city_org CASCADE;
DROP TABLE IF EXISTS road_segments CASCADE;
DROP TABLE IF EXISTS intersections CASCADE;
DROP TABLE IF EXISTS categories CASCADE;

CREATE TABLE city_org (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    title       TEXT NOT NULL,
    manager_id  INTEGER REFERENCES city_org (id)
);

CREATE TABLE intersections (
    id    SERIAL PRIMARY KEY,
    name  TEXT NOT NULL,
    geom  GEOMETRY(POINT, 4326) NOT NULL
);

CREATE TABLE road_segments (
    id                 SERIAL PRIMARY KEY,
    road_name          TEXT NOT NULL,
    from_intersection  INTEGER NOT NULL REFERENCES intersections (id),
    to_intersection    INTEGER NOT NULL REFERENCES intersections (id),
    length_m           NUMERIC(8, 1) NOT NULL
);

CREATE TABLE categories (
    id         SERIAL PRIMARY KEY,
    name       TEXT NOT NULL,
    parent_id  INTEGER REFERENCES categories (id)
);
"""

# ---------------------------------------------------------------------------
# city_org — Portsmith city government, 4 levels deep.
# Each row: (name, title, manager_name_or_None). Order matters: a manager
# must appear earlier in the list than anyone reporting to them.
# ---------------------------------------------------------------------------

CITY_ORG: list[tuple[str, str, str | None]] = [
    ("Coretta Vance", "Mayor", None),

    ("Marcus Webb", "Director of Public Works", "Coretta Vance"),
    ("Dana Ruiz", "Streets & Sanitation Supervisor", "Marcus Webb"),
    ("Leo Park", "Streets Crew", "Dana Ruiz"),
    ("Priya Nair", "Streets Crew", "Dana Ruiz"),
    ("Sam Okafor", "Streets Crew", "Dana Ruiz"),
    ("Tom Delgado", "Water & Sewer Supervisor", "Marcus Webb"),
    ("Ivy Chen", "Water & Sewer Crew", "Tom Delgado"),
    ("Noah Brandt", "Water & Sewer Crew", "Tom Delgado"),

    ("Helena Cross", "Director of Permitting & Licensing", "Coretta Vance"),
    ("Grace Halloway", "Senior Permit Reviewer", "Helena Cross"),
    ("Owen Fitch", "Permit Clerk", "Grace Halloway"),
    ("Mia Sorensen", "Permit Clerk", "Grace Halloway"),
    ("Ray Castellano", "Building Inspector", "Helena Cross"),

    ("Aisha Bonner", "Director of Parks & Recreation", "Coretta Vance"),
    ("Felix Wren", "Parks Maintenance Supervisor", "Aisha Bonner"),
    ("Nora Villalobos", "Groundskeeper", "Felix Wren"),
    ("Ezra Kowalski", "Groundskeeper", "Felix Wren"),

    ("Diane Okonjo", "Chief of Police", "Coretta Vance"),
    ("Marcus Reilly", "Patrol Captain", "Diane Okonjo"),
    ("Kwame Asante", "Patrol Officer", "Marcus Reilly"),
    ("Bianca Ferro", "Patrol Officer", "Marcus Reilly"),
    ("Theo Lindqvist", "Patrol Officer", "Marcus Reilly"),
    ("Paula Mensah", "Records Sergeant", "Diane Okonjo"),

    ("Julian Ostrowski", "Director of Finance", "Coretta Vance"),
    ("Renata Sikes", "City Accountant", "Julian Ostrowski"),
    ("Colin Marsh", "Budget Analyst", "Julian Ostrowski"),

    ("Wendell Achebe", "Director of IT", "Coretta Vance"),
    ("Zara Lindholm", "Systems Administrator", "Wendell Achebe"),
    ("Hugo Petrakis", "Database Administrator", "Wendell Achebe"),
]

# ---------------------------------------------------------------------------
# intersections — real points, computed against Chapter 2's actual
# city_infrastructure geometry via ST_Intersects / ST_LineLocatePoint.
# (lon, lat) pairs below are exact intersection coordinates, not estimates.
# ---------------------------------------------------------------------------

INTERSECTIONS: list[tuple[str, float, float]] = [
    ("Harbour Walk & Anchor Lane",        -1.783,  50.702),
    ("Portside Drive & Anchor Lane",      -1.783,  50.706),
    ("Bay Street & Ring Road (West)",     -1.83,   50.738),
    ("Bay Street & Canal Road",           -1.762,  50.738),
    ("Bay Street & Ring Road (East)",     -1.75,   50.738),
    ("Canal Road & Tidewater Lane",       -1.762,  50.71778947368421),
    ("Canal Road & Quay Street",          -1.762,  50.721),
    ("Dock Road & Ring Road",             -1.75,   50.698),
    ("Fisherman's Row & Market Street",   -1.793,  50.718),
    ("Harbour Walk & Ring Road",          -1.805,  50.702),
    ("Lighthouse Avenue & Ring Road",     -1.83,   50.72),
    ("Lighthouse Avenue & Market Street", -1.793,  50.72),
    ("Portside Drive & Ring Road",        -1.805,  50.706),
    ("Quay Street & Tidewater Lane",      -1.7559, 50.721),
    ("Quay Street & Ring Road",           -1.75,   50.721),
]

# road_segments — (road_name, from_name, to_name, length_m). Straight
# roads use straight-line geography distance; Ring Road's segments use
# ST_LineSubstring + ST_Length along its actual (bent) path, computed
# directly against Chapter 2's geometry — see module docstring.
ROAD_SEGMENTS: list[tuple[str, str, str, float]] = [
    ("Anchor Lane",       "Harbour Walk & Anchor Lane",        "Portside Drive & Anchor Lane",      445.0),
    ("Bay Street",         "Bay Street & Ring Road (West)",      "Bay Street & Canal Road",           4800.3),
    ("Bay Street",         "Bay Street & Canal Road",            "Bay Street & Ring Road (East)",     847.1),
    ("Canal Road",         "Canal Road & Tidewater Lane",        "Canal Road & Quay Street",          357.1),
    ("Canal Road",         "Canal Road & Quay Street",           "Bay Street & Canal Road",           1891.1),
    ("Harbour Walk",       "Harbour Walk & Ring Road",           "Harbour Walk & Anchor Lane",        1554.2),
    ("Lighthouse Avenue",  "Lighthouse Avenue & Ring Road",      "Lighthouse Avenue & Market Street", 2612.9),
    ("Market Street",      "Fisherman's Row & Market Street",    "Lighthouse Avenue & Market Street", 222.5),
    ("Portside Drive",     "Portside Drive & Ring Road",         "Portside Drive & Anchor Lane",      1554.1),
    ("Quay Street",        "Canal Road & Quay Street",           "Quay Street & Tidewater Lane",      430.8),
    ("Quay Street",        "Quay Street & Tidewater Lane",       "Quay Street & Ring Road",           416.6),
    ("Ring Road",          "Lighthouse Avenue & Ring Road",      "Bay Street & Ring Road (West)",     2002.4),
    ("Ring Road",          "Bay Street & Ring Road (West)",      "Bay Street & Ring Road (East)",     10541.7),
    ("Ring Road",          "Bay Street & Ring Road (East)",      "Quay Street & Ring Road",           1888.9),
    ("Ring Road",          "Quay Street & Ring Road",            "Dock Road & Ring Road",             2559.7),
    ("Ring Road",          "Dock Road & Ring Road",              "Harbour Walk & Ring Road",          6111.4),
    ("Ring Road",          "Harbour Walk & Ring Road",           "Portside Drive & Ring Road",        443.9),
    ("Ring Road",          "Portside Drive & Ring Road",         "Lighthouse Avenue & Ring Road",     3323.3),
    ("Tidewater Lane",     "Canal Road & Tidewater Lane",        "Quay Street & Tidewater Lane",      559.6),
]

# ---------------------------------------------------------------------------
# categories — "All Categories" -> Chapter 1's 5 real categories -> their
# real subcategories/cuisines, read directly from the `businesses` table.
# ---------------------------------------------------------------------------

ROOT_CATEGORY = "All Categories"

CATEGORY_CHILDREN: dict[str, list[str]] = {
    "restaurant": [
        "seafood", "pub", "italian", "french", "chinese", "indian",
        "mexican", "caribbean", "thai", "vegan", "deli", "bakery",
        "american", "british",
    ],
    "retail": [
        "specialty_food", "bookshop", "sporting_goods", "gallery",
        "hardware", "grocery", "electronics", "pharmacy",
        "marine_hardware", "art_supplies",
    ],
    "service": [
        "barber", "legal", "accountant", "tailor", "auto_repair",
        "spa", "dentist", "veterinarian", "plumber",
    ],
    "accommodation": ["inn", "bed_and_breakfast", "hotel", "hostel"],
    "entertainment": ["theater", "pub", "live_music", "cinema", "bar"],
}


def main() -> None:
    print(f"Connecting to: {DSN}")
    with psycopg.connect(DSN) as conn:
        with conn.cursor() as cur:
            print("Creating schema …")
            cur.execute(DDL)

            print(f"Inserting {len(CITY_ORG)} city_org rows …")
            name_to_id: dict[str, int] = {}
            for name, title, manager_name in CITY_ORG:
                manager_id = name_to_id[manager_name] if manager_name else None
                cur.execute(
                    "INSERT INTO city_org (name, title, manager_id) VALUES (%s, %s, %s) RETURNING id",
                    (name, title, manager_id),
                )
                (new_id,) = cur.fetchone()
                name_to_id[name] = new_id

            print(f"Inserting {len(INTERSECTIONS)} intersections …")
            intersection_ids: dict[str, int] = {}
            for name, lon, lat in INTERSECTIONS:
                cur.execute(
                    "INSERT INTO intersections (name, geom) "
                    "VALUES (%s, ST_SetSRID(ST_MakePoint(%s, %s), 4326)) RETURNING id",
                    (name, lon, lat),
                )
                (new_id,) = cur.fetchone()
                intersection_ids[name] = new_id

            print(f"Inserting {len(ROAD_SEGMENTS)} road segments …")
            for road_name, from_name, to_name, length_m in ROAD_SEGMENTS:
                cur.execute(
                    "INSERT INTO road_segments (road_name, from_intersection, to_intersection, length_m) "
                    "VALUES (%s, %s, %s, %s)",
                    (road_name, intersection_ids[from_name], intersection_ids[to_name], length_m),
                )

            print("Inserting category tree …")
            cur.execute(
                "INSERT INTO categories (name, parent_id) VALUES (%s, NULL) RETURNING id",
                (ROOT_CATEGORY,),
            )
            (root_id,) = cur.fetchone()
            n_categories = 1
            for category, children in CATEGORY_CHILDREN.items():
                cur.execute(
                    "INSERT INTO categories (name, parent_id) VALUES (%s, %s) RETURNING id",
                    (category, root_id),
                )
                (category_id,) = cur.fetchone()
                n_categories += 1
                for child in children:
                    cur.execute(
                        "INSERT INTO categories (name, parent_id) VALUES (%s, %s)",
                        (child, category_id),
                    )
                    n_categories += 1
            print(f"  {n_categories} category rows")

        conn.commit()

        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM city_org")
            (n_org,) = cur.fetchone()
            cur.execute("SELECT COUNT(*) FROM road_segments")
            (n_roads,) = cur.fetchone()
            cur.execute("SELECT COUNT(*) FROM categories")
            (n_cats,) = cur.fetchone()
        print(f"Done — {n_org} rows in city_org, {n_roads} rows in road_segments, "
              f"{n_cats} rows in categories.")


if __name__ == "__main__":
    main()
