#!/usr/bin/env python3.12
"""
Chapter 2 seed data — Portsmith Geospatial Layer.

Extends the `businesses` table from Chapter 1 with a point geometry column,
then creates three new tables:
  - neighborhoods      : polygon boundaries for Portsmith's six neighbourhoods
  - parks              : polygon geometry for six public parks
  - city_infrastructure: named road linestrings

Requires: Chapter 1 seed (ch01_seed.py) to have been run first so that the
          `businesses` table exists.
Requires: PostGIS installed on the PostgreSQL server
          (e.g. `sudo apt install postgresql-16-postgis-3`).

Usage:
    python ch02_seed.py [DSN]

    DSN defaults to "dbname=portsmith".
"""

import sys

import psycopg

DSN = sys.argv[1] if len(sys.argv) > 1 else "dbname=portsmith"

# ---------------------------------------------------------------------------
# PostGIS extension
# ---------------------------------------------------------------------------

ENABLE_POSTGIS = "CREATE EXTENSION IF NOT EXISTS postgis;"

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

DDL = """
-- Add a point geometry column to businesses (drop first for idempotency)
ALTER TABLE businesses DROP COLUMN IF EXISTS geom;
ALTER TABLE businesses ADD COLUMN geom GEOMETRY(POINT, 4326);

-- Neighbourhood polygons
DROP TABLE IF EXISTS neighborhoods CASCADE;
CREATE TABLE neighborhoods (
    id          SERIAL PRIMARY KEY,
    name        TEXT                       NOT NULL,
    population  INTEGER,
    geom        GEOMETRY(POLYGON, 4326)    NOT NULL
);

-- Public parks
DROP TABLE IF EXISTS parks CASCADE;
CREATE TABLE parks (
    id           SERIAL PRIMARY KEY,
    name         TEXT                       NOT NULL,
    neighborhood TEXT                       NOT NULL,
    geom         GEOMETRY(POLYGON, 4326)    NOT NULL
);

-- Road infrastructure
DROP TABLE IF EXISTS city_infrastructure CASCADE;
CREATE TABLE city_infrastructure (
    id        SERIAL PRIMARY KEY,
    name      TEXT                         NOT NULL,
    road_type TEXT                         NOT NULL,
    geom      GEOMETRY(LINESTRING, 4326)   NOT NULL
);
"""

# ---------------------------------------------------------------------------
# Portsmith coordinate layout (all WGS-84 / SRID 4326)
#
# The city sits on the southern English coast (fictional).  Approximate
# bounding box: longitude -1.830 to -1.750, latitude 50.690 to 50.760.
#
# Neighbourhood grid (non-overlapping rectangles):
#
#   University Quarter  -1.830..-1.805  50.710..50.732
#   Old Town            -1.805..-1.773  50.710..50.732
#   Riverside           -1.773..-1.750  50.710..50.732
#   Harbour District    -1.805..-1.770  50.690..50.710
#   Industrial Port     -1.770..-1.750  50.690..50.710
#   Northgate           -1.830..-1.750  50.732..50.760
# ---------------------------------------------------------------------------

NEIGHBORHOODS: list[dict] = [
    {
        "name": "Harbour District",
        "population": 4200,
        "wkt": (
            "POLYGON(("
            "-1.805 50.690, -1.770 50.690, -1.770 50.710, -1.805 50.710, -1.805 50.690"
            "))"
        ),
    },
    {
        "name": "Old Town",
        "population": 6800,
        "wkt": (
            "POLYGON(("
            "-1.805 50.710, -1.773 50.710, -1.773 50.732, -1.805 50.732, -1.805 50.710"
            "))"
        ),
    },
    {
        "name": "Northgate",
        "population": 18500,
        "wkt": (
            "POLYGON(("
            "-1.830 50.732, -1.750 50.732, -1.750 50.760, -1.830 50.760, -1.830 50.732"
            "))"
        ),
    },
    {
        "name": "Riverside",
        "population": 9300,
        "wkt": (
            "POLYGON(("
            "-1.773 50.710, -1.750 50.710, -1.750 50.732, -1.773 50.732, -1.773 50.710"
            "))"
        ),
    },
    {
        "name": "University Quarter",
        "population": 11200,
        "wkt": (
            "POLYGON(("
            "-1.830 50.710, -1.805 50.710, -1.805 50.732, -1.830 50.732, -1.830 50.710"
            "))"
        ),
    },
    {
        "name": "Industrial Port",
        "population": 2100,
        "wkt": (
            "POLYGON(("
            "-1.770 50.690, -1.750 50.690, -1.750 50.710, -1.770 50.710, -1.770 50.690"
            "))"
        ),
    },
]

# ---------------------------------------------------------------------------
# Business point locations  (longitude, latitude)
# Every point falls clearly inside its neighbourhood polygon.
# ---------------------------------------------------------------------------

BUSINESS_COORDS: dict[str, tuple[float, float]] = {
    # ── Harbour District ────────────────────────────────────────────────────
    "The Gilded Clam":               (-1.786, 50.700),
    "Anchor & Oar Tavern":           (-1.783, 50.701),
    "Portsmith Fish Market":         (-1.790, 50.697),
    "Harbour Inn":                   (-1.781, 50.703),
    "Lighthouse Bookshop":           (-1.778, 50.704),
    "Tidal Wave Surf Shop":          (-1.782, 50.702),
    "Mariners Rest B&B":             (-1.779, 50.705),
    "Saltbox Gallery":               (-1.777, 50.706),
    "Harbour View Theater":          (-1.775, 50.707),
    # ── Old Town ─────────────────────────────────────────────────────────────
    "Bella Napoli":                  (-1.794, 50.718),
    "Le Petit Bistro":               (-1.796, 50.717),
    "Old Town Hardware":             (-1.800, 50.720),
    "Finch & Sons Barbers":          (-1.788, 50.715),
    "The Clocktower Pub":            (-1.793, 50.717),
    "Portsmith Legal Group":         (-1.787, 50.720),
    "Portsmith Arms Hotel":          (-1.786, 50.719),
    "Portsmith Accountancy Ltd.":    (-1.789, 50.720),
    "Portsmith Tailors":             (-1.798, 50.720),
    # ── Northgate ────────────────────────────────────────────────────────────
    "Dragon Palace":                 (-1.779, 50.738),
    "Northgate Grocers":             (-1.792, 50.742),
    "AutoFix Portsmith":             (-1.804, 50.740),
    "The Grand Hotel Portsmith":     (-1.771, 50.737),
    "Lotus Spa & Wellness":          (-1.787, 50.741),
    "Spice Garden":                  (-1.778, 50.738),
    "Sol y Mar":                     (-1.780, 50.738),
    "Mango Bay Caribbean":           (-1.782, 50.737),
    "Bay Street Electronics":        (-1.774, 50.739),
    # ── Riverside ─────────────────────────────────────────────────────────────
    "River Bend Bakery":             (-1.762, 50.718),
    "The Riverside Vegan":           (-1.761, 50.719),
    "Thai Orchid":                   (-1.764, 50.716),
    "Quay Street Deli":              (-1.765, 50.720),
    "Portsmith Pharmacy":            (-1.760, 50.722),
    "Dr. Chen Dentistry":            (-1.766, 50.715),
    "Riverside Cinema":              (-1.759, 50.723),
    "Portsmith Veterinary Clinic":   (-1.761, 50.724),
    "The Art Depot":                 (-1.763, 50.721),
    # ── University Quarter ────────────────────────────────────────────────────
    "The Hungry Scholar":            (-1.813, 50.717),
    "Quarter Note Jazz Club":        (-1.811, 50.720),
    "University Bookshop":           (-1.818, 50.724),
    "Campus Bike & Sports":          (-1.812, 50.721),
    "Green Leaf Cafe":               (-1.814, 50.717),
    # ── Industrial Port ───────────────────────────────────────────────────────
    "Port Canteen":                  (-1.763, 50.697),
    "Marine Supply Co.":             (-1.761, 50.696),
    "Port View Hostel":              (-1.766, 50.699),
    "Ironside Auto":                 (-1.757, 50.702),
    "The Rusty Anchor":              (-1.762, 50.697),
    "Portsmith Plumbing & Heating":  (-1.756, 50.703),
    "Old Brewery Tap":               (-1.760, 50.698),
}

# ---------------------------------------------------------------------------
# Parks (small polygon patches)
# ---------------------------------------------------------------------------

PARKS: list[dict] = [
    {
        "name": "Harbourside Park",
        "neighborhood": "Harbour District",
        "wkt": (
            "POLYGON(("
            "-1.784 50.706, -1.780 50.706, -1.780 50.709, -1.784 50.709, -1.784 50.706"
            "))"
        ),
    },
    {
        "name": "Market Square Gardens",
        "neighborhood": "Old Town",
        "wkt": (
            "POLYGON(("
            "-1.796 50.719, -1.791 50.719, -1.791 50.722, -1.796 50.722, -1.796 50.719"
            "))"
        ),
    },
    {
        "name": "Riverside Walk Park",
        "neighborhood": "Riverside",
        "wkt": (
            "POLYGON(("
            "-1.764 50.722, -1.758 50.722, -1.758 50.728, -1.764 50.728, -1.764 50.722"
            "))"
        ),
    },
    {
        "name": "University Grounds",
        "neighborhood": "University Quarter",
        "wkt": (
            "POLYGON(("
            "-1.820 50.722, -1.812 50.722, -1.812 50.729, -1.820 50.729, -1.820 50.722"
            "))"
        ),
    },
    {
        "name": "Northgate Recreation Ground",
        "neighborhood": "Northgate",
        "wkt": (
            "POLYGON(("
            "-1.793 50.745, -1.780 50.745, -1.780 50.753, -1.793 50.753, -1.793 50.745"
            "))"
        ),
    },
    {
        "name": "Dockside Green",
        "neighborhood": "Industrial Port",
        "wkt": (
            "POLYGON(("
            "-1.768 50.703, -1.760 50.703, -1.760 50.707, -1.768 50.707, -1.768 50.703"
            "))"
        ),
    },
]

# ---------------------------------------------------------------------------
# Road network (linestrings)
# ---------------------------------------------------------------------------

ROADS: list[dict] = [
    {
        "name": "Harbour Walk",
        "road_type": "arterial",
        "wkt": "LINESTRING(-1.805 50.702, -1.770 50.702)",
    },
    {
        "name": "Portside Drive",
        "road_type": "secondary",
        "wkt": "LINESTRING(-1.805 50.706, -1.770 50.706)",
    },
    {
        "name": "Market Street",
        "road_type": "arterial",
        "wkt": "LINESTRING(-1.793 50.710, -1.793 50.732)",
    },
    {
        "name": "Lighthouse Avenue",
        "road_type": "arterial",
        "wkt": "LINESTRING(-1.830 50.720, -1.773 50.720)",
    },
    {
        "name": "Bay Street",
        "road_type": "arterial",
        "wkt": "LINESTRING(-1.830 50.738, -1.750 50.738)",
    },
    {
        "name": "Canal Road",
        "road_type": "arterial",
        "wkt": "LINESTRING(-1.762 50.710, -1.762 50.750)",
    },
    {
        "name": "Dock Road",
        "road_type": "secondary",
        "wkt": "LINESTRING(-1.770 50.698, -1.750 50.698)",
    },
    {
        "name": "Quay Street",
        "road_type": "secondary",
        "wkt": "LINESTRING(-1.770 50.721, -1.750 50.721)",
    },
    {
        "name": "Tidewater Lane",
        "road_type": "secondary",
        "wkt": "LINESTRING(-1.773 50.712, -1.754 50.722)",
    },
    {
        "name": "Anchor Lane",
        "road_type": "local",
        "wkt": "LINESTRING(-1.783 50.700, -1.783 50.708)",
    },
    {
        "name": "Fisherman's Row",
        "road_type": "local",
        "wkt": "LINESTRING(-1.803 50.718, -1.785 50.718)",
    },
    {
        "name": "Ring Road",
        "road_type": "motorway",
        "wkt": (
            "LINESTRING("
            "-1.830 50.710, -1.830 50.760, -1.750 50.760, "
            "-1.750 50.690, -1.805 50.690, -1.805 50.710, -1.830 50.710"
            ")"
        ),
    },
]

# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def main() -> None:
    print(f"Connecting to: {DSN}")
    with psycopg.connect(DSN) as conn:
        with conn.cursor() as cur:

            # ── PostGIS ──────────────────────────────────────────────────────
            print("Enabling PostGIS extension …")
            cur.execute(ENABLE_POSTGIS)

            # ── Schema ───────────────────────────────────────────────────────
            print("Applying DDL …")
            cur.execute(DDL)

            # ── Neighbourhoods ───────────────────────────────────────────────
            print(f"Inserting {len(NEIGHBORHOODS)} neighbourhoods …")
            cur.executemany(
                """
                INSERT INTO neighborhoods (name, population, geom)
                VALUES (%(name)s, %(population)s,
                        ST_GeomFromText(%(wkt)s, 4326))
                """,
                NEIGHBORHOODS,
            )

            # ── Parks ────────────────────────────────────────────────────────
            print(f"Inserting {len(PARKS)} parks …")
            cur.executemany(
                """
                INSERT INTO parks (name, neighborhood, geom)
                VALUES (%(name)s, %(neighborhood)s,
                        ST_GeomFromText(%(wkt)s, 4326))
                """,
                PARKS,
            )

            # ── Roads ────────────────────────────────────────────────────────
            print(f"Inserting {len(ROADS)} road segments …")
            cur.executemany(
                """
                INSERT INTO city_infrastructure (name, road_type, geom)
                VALUES (%(name)s, %(road_type)s,
                        ST_GeomFromText(%(wkt)s, 4326))
                """,
                ROADS,
            )

            # ── Business point geometry ──────────────────────────────────────
            print(f"Updating {len(BUSINESS_COORDS)} business locations …")
            for name, (lon, lat) in BUSINESS_COORDS.items():
                cur.execute(
                    """
                    UPDATE businesses
                    SET    geom = ST_SetSRID(ST_MakePoint(%s, %s), 4326)
                    WHERE  name = %s
                    """,
                    (lon, lat, name),
                )

            # ── Sanity check ─────────────────────────────────────────────────
            cur.execute("SELECT COUNT(*) FROM businesses WHERE geom IS NOT NULL")
            (geom_count,) = cur.fetchone()
            cur.execute("SELECT COUNT(*) FROM neighborhoods")
            (nb_count,) = cur.fetchone()
            cur.execute("SELECT COUNT(*) FROM parks")
            (park_count,) = cur.fetchone()
            cur.execute("SELECT COUNT(*) FROM city_infrastructure")
            (road_count,) = cur.fetchone()

            print(
                f"\nDone:\n"
                f"  businesses with geometry : {geom_count}\n"
                f"  neighbourhoods           : {nb_count}\n"
                f"  parks                    : {park_count}\n"
                f"  road segments            : {road_count}"
            )

        conn.commit()


if __name__ == "__main__":
    main()
