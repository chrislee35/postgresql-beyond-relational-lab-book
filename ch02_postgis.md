# Chapter 2 — PostGIS: Geospatial Queries on Real Geometry

> *"A city is not a list of rows. It is a shape on the ground."*

---

## Background

Every interesting question about a city is ultimately a spatial question. Which
businesses are near the harbour? Which neighbourhood is this address in? How
large is the industrial waterfront? Relational databases answer these badly when
location is stored as a text field or a pair of float columns — there is no
native concept of "within", "contains", or "distance".

PostGIS is a PostgreSQL extension that adds first-class geometry and geography
types, plus several hundred spatial functions and operators. It turns PostgreSQL
into a full spatial database: you can store points, lines, and polygons;
index them with GIST; and answer proximity, containment, and area queries in
SQL without an external GIS system.

This matters in practice far beyond mapping applications. Address geocoding,
logistics routing, fraud detection (is this login coming from the expected
region?), real estate valuation, and urban planning all reach for spatial
queries. PostGIS is the standard tool for all of them in the PostgreSQL
ecosystem.

---

## The Scenario

The Portsmith business directory from Chapter 1 stores each business's
neighbourhood as a plain text column. That works for simple filtering, but it
cannot answer *where* questions: it cannot find businesses near a given
coordinate, cannot verify that a business address actually falls inside its
declared neighbourhood, and cannot measure distances.

This chapter adds a point geometry to every business record, then introduces
three new spatial tables:

| Table                  | Geometry type | What it holds                              |
|------------------------|---------------|--------------------------------------------|
| `neighborhoods`        | `POLYGON`     | Boundary polygons for Portsmith's six neighbourhoods |
| `parks`                | `POLYGON`     | Six public parks and green spaces          |
| `city_infrastructure`  | `LINESTRING`  | Twelve named road segments                 |

All coordinates are in WGS-84 (SRID 4326), the same coordinate system used by
GPS and most web mapping APIs.

---

## Exercise Goals

By the end of this chapter you will be able to:

- Store and inspect `POLYGON` geometry using WKT (Well-Known Text) and
  `ST_GeomFromText`.
- Run proximity searches with `ST_DWithin`, and understand why the
  `::geography` cast matters for distance accuracy.
- Perform spatial joins using `ST_Within` and `ST_Contains`, and explain
  the difference between them.
- Compute polygon areas in square kilometres using `ST_Area` with the
  geography type.
- Find the nearest feature for every row using `ST_Distance` and a
  `CROSS JOIN LATERAL`.
- Create a GIST spatial index and confirm that PostgreSQL uses it.

---

## Installation

### 1 — PostGIS server package

PostGIS is a separate package from PostgreSQL. On Debian/Ubuntu:

```bash
sudo apt install -y postgresql-16-postgis-3
```

### 2 — Enable PostGIS in the database

Connect to the `portsmith` database and enable the extension:

```bash
psql portsmith
```

```sql
CREATE EXTENSION IF NOT EXISTS postgis;
```

Verify it loaded:

```sql
SELECT postgis_full_version();
```

You should see a long string beginning with `POSTGIS="3.x.x"`. If you see an
error about the extension not existing, the server package is not installed.

---

## Loading the Data

### Prerequisites

Chapter 1's seed script must have been run first — the `businesses` table must
exist. If it does not:

```bash
python data/ch01_seed.py
```

### Run the Chapter 2 seed

```bash
python data/ch02_seed.py
```

Expected output:

```
Connecting to: dbname=portsmith
Enabling PostGIS extension …
Applying DDL …
Inserting 6 neighbourhoods …
Inserting 6 parks …
Inserting 12 road segments …
Updating 48 business locations …

Done:
  businesses with geometry : 48
  neighbourhoods           : 6
  parks                    : 6
  road segments            : 12
```

### Verify the load

Open `psql portsmith` and run these four checks.

**Check 1 — businesses now has a geometry column:**

```sql
\d businesses
```

You should see a new `geom` column of type `geometry(Point,4326)`.

**Check 2 — neighbourhood table structure and row count:**

```sql
SELECT name, population,
       ST_AsText(geom) AS wkt_preview
FROM   neighborhoods
ORDER  BY name;
```

```
       name         | population |            wkt_preview
--------------------+------------+------------------------------------
 Harbour District   |       4200 | POLYGON((-1.805 50.69,...))
 Industrial Port    |       2100 | POLYGON((-1.77 50.69,...))
 Northgate          |      18500 | POLYGON((-1.83 50.732,...))
 Old Town           |       6800 | POLYGON((-1.805 50.71,...))
 Riverside          |       9300 | POLYGON((-1.773 50.71,...))
 University Quarter |      11200 | POLYGON((-1.83 50.71,...))
(6 rows)
```

**Check 3 — parks and roads:**

```sql
SELECT COUNT(*) FROM parks;
SELECT COUNT(*) FROM city_infrastructure;
```

Both should return 6 and 12 respectively.

**Check 4 — SRID on all tables:**

```sql
SELECT f_table_name, f_geometry_column, srid, type
FROM   geometry_columns
WHERE  f_table_schema = 'public'
ORDER  BY f_table_name;
```

```
      f_table_name      | f_geometry_column | srid |    type
------------------------+-------------------+------+------------
 businesses             | geom              | 4326 | POINT
 city_infrastructure    | geom              | 4326 | LINESTRING
 neighborhoods          | geom              | 4326 | POLYGON
 parks                  | geom              | 4326 | POLYGON
(4 rows)
```

If all four pass, proceed to the exercises.

---

## Exercises

---

### Exercise 1 — Neighbourhood Polygons and WKT

Geometry in PostGIS is often loaded from **Well-Known Text** (WKT), a
human-readable representation of shapes. Understanding WKT lets you read
geometry from SQL output, write it in queries, and reason about what you stored.

**1.1 — Read a polygon in WKT**

```sql
SELECT name, ST_AsText(geom) AS wkt
FROM   neighborhoods
WHERE  name = 'Harbour District';
```

```
       name        |                          wkt
-------------------+------------------------------------------------------
 Harbour District  | POLYGON((-1.805 50.69,-1.77 50.69,-1.77 50.71,...))
```

WKT for a polygon is `POLYGON((x1 y1, x2 y2, ...))`. In geographic coordinates
the convention is *longitude latitude* (x then y), matching the X/Y convention
in maths. The ring must **close** — the last coordinate must equal the first.

**1.2 — Inspect the bounding box**

`ST_Envelope` returns the minimum bounding rectangle for any geometry:

```sql
SELECT name,
       ST_XMin(ST_Envelope(geom)) AS west,
       ST_XMax(ST_Envelope(geom)) AS east,
       ST_YMin(ST_Envelope(geom)) AS south,
       ST_YMax(ST_Envelope(geom)) AS north
FROM   neighborhoods
ORDER  BY name;
```

Use this output to confirm each polygon sits in the right part of the
coordinate space (longitudes around −1.75 to −1.83, latitudes around 50.69
to 50.76).

**1.3 — Count vertices**

```sql
SELECT name,
       ST_NPoints(geom) AS vertex_count
FROM   neighborhoods
ORDER  BY name;
```

Each neighbourhood polygon has five vertices (four corners plus the closing
duplicate). A real city boundary imported from an OS/census shapefile might
have thousands.

**1.4 — Understand the SRID**

`ST_SRID` returns the spatial reference identifier stored with the geometry:

```sql
SELECT name, ST_SRID(geom) AS srid
FROM   neighborhoods
LIMIT  3;
```

SRID 4326 is the WGS-84 system used by GPS. Every geometry in these tables
carries the same SRID, which means they can be compared and joined directly.
If SRIDs differ, PostGIS will return an error — a deliberate safety check.

> **The geometry/geography distinction:** In PostGIS, `geometry` stores
> coordinates in whatever units the SRS defines. For SRID 4326 that means
> degrees. When you ask for a distance between two `geometry` points in 4326,
> you get a value in *degrees* — nearly useless for human-scale distances.
> The `geography` type, by contrast, always works on a spheroid and returns
> distances in *metres*. You can cast any SRID-4326 geometry to geography
> with `::geography` to get metre-based calculations. The exercises use this
> cast throughout.

---

### Exercise 2 — Proximity Search with `ST_DWithin`

`ST_DWithin(a, b, distance)` returns true when the distance between `a` and `b`
is at most `distance`. With geography inputs the distance is in metres.

**2.1 — Find businesses within 500 m of Portsmith Pier**

Portsmith's main pier entrance sits at approximately (−1.785, 50.700). Find
every business within 500 metres of it:

```sql
SELECT b.name,
       b.neighbourhood,
       ROUND(
           ST_Distance(b.geom::geography,
                       ST_Point(-1.785, 50.700)::geography)::numeric
       ) AS distance_m
FROM   businesses b
WHERE  ST_DWithin(b.geom::geography,
                  ST_Point(-1.785, 50.700)::geography,
                  500)
ORDER  BY distance_m;
```

```
          name           |  neighbourhood   | distance_m
-------------------------+------------------+------------
 The Gilded Clam         | Harbour District |         70
 Anchor & Oar Tavern     | Harbour District |        179
 Tidal Wave Surf Shop    | Harbour District |        307
 Harbour Inn             | Harbour District |        437
 Portsmith Fish Market   | Harbour District |        484
(5 rows)
```

All five results are in the Harbour District — exactly what you would expect
for a search centred on the pier.

**2.2 — Why `::geography` matters**

Try the same query without the cast. Note that `ST_Point(...)` without an
explicit SRID gets SRID 0, which PostGIS refuses to compare against SRID-4326
geometry — so you must use `ST_SetSRID`:

```sql
SELECT b.name,
       ROUND(ST_Distance(b.geom,
                         ST_SetSRID(ST_Point(-1.785, 50.700), 4326))::numeric,
             6)                AS distance_degrees
FROM   businesses b
WHERE  ST_DWithin(b.geom,
                  ST_SetSRID(ST_Point(-1.785, 50.700), 4326),
                  500)
ORDER  BY distance_degrees;
```

The `WHERE` clause now has a threshold of `500` — but in *degrees*. One degree
of latitude is about 111 km, so this matches businesses within roughly
55,000 km: all 48 of them, from the whole city. The `distance_degrees` values
in the output are tiny fractions like `0.001000`, not useful numbers.

```
 rows returned: 48  (the entire city, not 5)
```

> **Rule:** For any distance query on SRID-4326 data, always cast to
> `::geography` in `ST_DWithin` and `ST_Distance`. The cast has negligible
> performance cost at the scales used in city-level data.

**2.3 — Try different radii**

How many businesses fall within 1 km of the pier? 2 km?

```sql
SELECT radius_m,
       COUNT(*) AS business_count
FROM   (VALUES (500), (1000), (2000)) AS radii(radius_m)
CROSS JOIN LATERAL (
    SELECT 1
    FROM   businesses b
    WHERE  ST_DWithin(b.geom::geography,
                      ST_Point(-1.785, 50.700)::geography,
                      radius_m)
) AS matches
GROUP  BY radius_m
ORDER  BY radius_m;
```

```
 radius_m | business_count
----------+----------------
      500 |              5
     1000 |              8
     2000 |             17
(3 rows)
```

The pier sits in the southern Harbour District. Doubling the radius to 2 km
pulls in more of the central neighbourhoods, but the northern Northgate
businesses are nearly 5 km away — a reminder that Portsmith stretches a
significant distance north from the waterfront.

---

### Exercise 3 — Spatial Joins with `ST_Within` and `ST_Contains`

A **spatial join** links rows from two tables based on a geometric relationship
rather than a key match. The most common are containment tests: does point A
fall inside polygon B?

**3.1 — Which neighbourhood is each business in?**

```sql
SELECT b.name,
       b.neighbourhood          AS declared_neighbourhood,
       n.name                   AS postgis_neighbourhood
FROM   businesses  b
JOIN   neighborhoods n ON ST_Within(b.geom, n.geom)
ORDER  BY n.name, b.name;
```

`ST_Within(a, b)` returns true when geometry `a` lies completely inside
geometry `b`. The query should return all 48 businesses, each matched to its
neighbourhood.

Confirm the declared `neighbourhood` column always matches `postgis_neighbourhood`:

```sql
SELECT COUNT(*) AS mismatches
FROM   businesses  b
JOIN   neighborhoods n ON ST_Within(b.geom, n.geom)
WHERE  b.neighbourhood <> n.name;
```

```
 mismatches
------------
          0
(1 row)
```

Zero mismatches: the text column from Chapter 1 and the geometry are
consistent.

**3.2 — `ST_Contains` is the inverse**

`ST_Contains(a, b)` returns true when polygon `a` contains geometry `b` —
it is the mirror of `ST_Within`. These two queries produce identical results:

```sql
-- Point inside polygon
SELECT b.name FROM businesses b
JOIN   neighborhoods n ON ST_Within(b.geom, n.geom)
WHERE  n.name = 'Old Town'
ORDER  BY b.name;

-- Polygon contains point
SELECT b.name FROM businesses b
JOIN   neighborhoods n ON ST_Contains(n.geom, b.geom)
WHERE  n.name = 'Old Town'
ORDER  BY b.name;
```

```
          name
--------------------------
 Bella Napoli
 Finch & Sons Barbers
 Le Petit Bistro
 Old Town Hardware
 Portsmith Accountancy Ltd.
 Portsmith Arms Hotel
 Portsmith Legal Group
 Portsmith Tailors
 The Clocktower Pub
(9 rows)
```

Both return the same 9 Old Town businesses.

> **The subtle difference:** `ST_Contains(A, B)` requires that no point of B
> lies on the boundary of A. A point sitting exactly *on* a polygon edge would
> fail `ST_Contains` but pass `ST_Covers`. In practice, coordinates rarely land
> precisely on a boundary, so the two functions behave identically for most
> point-in-polygon work. Reach for `ST_Covers` if you need to include
> boundary-touching cases explicitly.

**3.3 — Check for gaps: businesses in no neighbourhood**

This query finds any businesses whose geometry falls outside every neighbourhood
polygon — useful for catching data quality problems:

```sql
SELECT b.name, b.neighbourhood
FROM   businesses b
WHERE  NOT EXISTS (
    SELECT 1
    FROM   neighborhoods n
    WHERE  ST_Within(b.geom, n.geom)
);
```

```
 name | neighbourhood
------+---------------
(0 rows)
```

All 48 businesses are inside a neighbourhood polygon.

---

### Exercise 4 — Computing Area in Square Kilometres

`ST_Area` returns the area of a polygon. Called on `geometry` (degrees), it
returns a value in square degrees — meaningless to most people. Called on `geography`, it
returns square metres.

**4.1 — Incorrect: area in square degrees**

```sql
SELECT name,
       ROUND(ST_Area(geom)::numeric, 6) AS area_sq_degrees
FROM   neighborhoods
ORDER  BY area_sq_degrees DESC;
```

The numbers look tiny (around `0.0007`). They are geometrically correct but
impossible to interpret as real-world area because degrees are not uniform
units.

**4.2 — Correct: area in square metres, then kilometres**

```sql
SELECT name,
       ROUND((ST_Area(geom::geography) / 1e6)::numeric, 2) AS area_km2
FROM   neighborhoods
ORDER  BY area_km2 DESC;
```

```
        name        | area_km2
--------------------+----------
 Northgate          |    17.59
 Old Town           |     5.53
 Harbour District   |     5.50
 University Quarter |     4.32
 Riverside          |     3.98
 Industrial Port    |     3.14
(6 rows)
```

Northgate is by far the largest neighbourhood — it spans the entire northern
width of the city. Industrial Port is the smallest, a tight strip of dockside
land. Old Town and Harbour District are almost identical in area despite having
very different characters.

> **Why the numbers differ slightly from manual estimates:** `ST_Area` on
> geography uses the WGS-84 spheroid, which accounts for the fact that the
> Earth is not a perfect sphere. At latitude 50.7° the correction is small
> (under 0.3%) but present.

**4.3 — Population density**

Combine the computed area with the `population` column:

```sql
SELECT name,
       population,
       ROUND((ST_Area(geom::geography) / 1e6)::numeric, 2) AS area_km2,
       ROUND(
           (population / (ST_Area(geom::geography) / 1e6))::numeric
       ) AS pop_per_km2
FROM   neighborhoods
ORDER  BY pop_per_km2 DESC;
```

```
        name        | population | area_km2 | pop_per_km2
--------------------+------------+----------+-------------
 University Quarter |      11200 |     4.32 |        2592
 Riverside          |       9300 |     3.98 |        2340
 Old Town           |       6800 |     5.53 |        1230
 Northgate          |      18500 |    17.59 |        1052
 Harbour District   |       4200 |     5.50 |         763
 Industrial Port    |       2100 |     3.14 |         668
(6 rows)
```

The University Quarter and Riverside are the most densely populated
neighbourhoods — student housing and riverside apartments pack a lot of people
into compact areas. The Industrial Port is the least dense despite its small
size; much of it is warehouse and dock rather than residential.

---

### Exercise 5 — Nearest Park Using `ST_Distance` and a Lateral Join

Finding the nearest feature from another table requires a **lateral join** — a
subquery that can reference columns from the outer query row by row.

**5.1 — Distance from one business to one park**

`ST_Distance` between two geography values returns metres:

```sql
SELECT b.name                          AS business,
       p.name                          AS park,
       ROUND(ST_Distance(b.geom::geography,
                         p.geom::geography)::numeric) AS distance_m
FROM   businesses b,
       parks p
WHERE  b.name = 'The Gilded Clam'
ORDER  BY distance_m;
```

```
     business     |            park             | distance_m
------------------+-----------------------------+------------
 The Gilded Clam  | Harbourside Park            |        682
 The Gilded Clam  | Dockside Green              |       1315
 The Gilded Clam  | Market Square Gardens       |       2143
 The Gilded Clam  | Riverside Walk Park         |       2899
 The Gilded Clam  | University Grounds          |       3060
 The Gilded Clam  | Northgate Recreation Ground |       5006
(6 rows)
```

The nearest park to The Gilded Clam is Harbourside Park, 682 m away. The
`ST_Distance` to a polygon returns the distance from the point to the nearest
point on the polygon's boundary — zero when the point is inside the polygon.

**5.2 — Nearest park for a single business (lateral pattern)**

The canonical pattern for "nearest one thing" is `ORDER BY ... LIMIT 1` inside
a lateral subquery:

```sql
SELECT b.name,
       nearest.park_name,
       nearest.distance_m
FROM   businesses b
CROSS JOIN LATERAL (
    SELECT p.name                                               AS park_name,
           ROUND(ST_Distance(b.geom::geography,
                             p.geom::geography)::numeric)      AS distance_m
    FROM   parks p
    ORDER  BY b.geom::geography <-> p.geom::geography
    LIMIT  1
) AS nearest
WHERE  b.name = 'Quarter Note Jazz Club';
```

```
         name          |    park_name       | distance_m
-----------------------+--------------------+------------
 Quarter Note Jazz Club | University Grounds |        233
(1 row)
```

The `<->` operator is the KNN (k-nearest-neighbour) distance operator. When
used in an `ORDER BY` clause inside a lateral join, PostGIS can accelerate it
with the GIST index (which you will create in Exercise 6). Using `<->` in
`ORDER BY` is preferred over `ORDER BY ST_Distance(...)` for this reason.

**5.3 — Nearest park for every business**

Remove the `WHERE` filter to run across all 48 businesses:

```sql
SELECT b.name                          AS business,
       b.neighbourhood,
       nearest.park_name,
       nearest.distance_m
FROM   businesses b
CROSS JOIN LATERAL (
    SELECT p.name                                               AS park_name,
           ROUND(ST_Distance(b.geom::geography,
                             p.geom::geography)::numeric)      AS distance_m
    FROM   parks p
    ORDER  BY b.geom::geography <-> p.geom::geography
    LIMIT  1
) AS nearest
ORDER  BY b.neighbourhood, b.name;
```

Scan the results. You should see a clean pattern: each neighbourhood's
businesses point to the park in that same neighbourhood. Notice that three
Riverside businesses (Portsmith Pharmacy, Portsmith Veterinary Clinic, Riverside
Cinema) and University Bookshop all show `distance_m = 0` — their coordinates
fall *inside* the park polygon. `ST_Distance` to a polygon returns zero when
the point is contained within it.

**5.4 — Aggregate: average walking distance to a park, by neighbourhood**

```sql
SELECT b.neighbourhood,
       ROUND(AVG(nearest.distance_m)::numeric) AS avg_distance_m
FROM   businesses b
CROSS JOIN LATERAL (
    SELECT ROUND(ST_Distance(b.geom::geography,
                             p.geom::geography)::numeric) AS distance_m
    FROM   parks p
    ORDER  BY b.geom::geography <-> p.geom::geography
    LIMIT  1
) AS nearest
GROUP  BY b.neighbourhood
ORDER  BY avg_distance_m;
```

This gives a rough "walkability to green space" metric per neighbourhood. Old
Town ranks first — Market Square Gardens sits centrally within the neighbourhood.
Northgate comes last despite having the largest park, because the park is in
the far north of the district while businesses cluster near the southern edge.

---

### Exercise 6 — GIST Indexes and Spatial Query Plans

Without an index, every spatial query is a sequential scan: PostgreSQL reads
every row, applies the geometry function, and discards non-matching rows. For
a 48-row dataset that is instant, but at 48 million rows it is not.

PostGIS spatial queries are accelerated by **GIST** (Generalised Search Tree)
indexes. A GIST index on a geometry column builds a tree of bounding boxes,
allowing the planner to quickly eliminate large portions of the table.

**6.1 — Observe the plan before indexing**

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT name
FROM   businesses
WHERE  ST_DWithin(geom::geography,
                  ST_Point(-1.785, 50.700)::geography,
                  500);
```

On the 48-row `businesses` table you will see something like:

```
Seq Scan on businesses  (cost=0.00..4.60 rows=1 width=...) ...
  Filter: (st_dwithin(...))
  Rows Removed by Filter: 43
```

A sequential scan is expected on a tiny table — the planner knows the overhead
of an index lookup exceeds the cost of reading all 48 rows.

**6.2 — Create GIST indexes on the geometry columns**

```sql
CREATE INDEX idx_businesses_geom
    ON businesses USING GIST (geom);

CREATE INDEX idx_neighborhoods_geom
    ON neighborhoods USING GIST (geom);

CREATE INDEX idx_parks_geom
    ON parks USING GIST (geom);

CREATE INDEX idx_city_infrastructure_geom
    ON city_infrastructure USING GIST (geom);
```

**6.3 — The geometry/geography index split**

With `enable_seqscan` off, verify which plan the proximity query uses:

```sql
SET enable_seqscan = off;

EXPLAIN (ANALYZE, BUFFERS)
SELECT name
FROM   businesses
WHERE  ST_DWithin(geom::geography,
                  ST_Point(-1.785, 50.700)::geography,
                  500);

SET enable_seqscan = on;
```

You will see — perhaps surprisingly — that the planner *still* uses a sequential
scan, even though `idx_businesses_geom` exists:

```
Seq Scan on businesses  (cost=10000000000.00...) ...
  Filter: st_dwithin((geom)::geography, ...)
```

**Why?** The GIST index was built on `geom` (type `geometry`). The query
filters on `geom::geography` (type `geography`). These are different types —
the index is not usable for geography operations.

To accelerate geography-based distance queries you need a **functional index**
on the cast:

```sql
CREATE INDEX idx_businesses_geom_geography
    ON businesses USING GIST (CAST(geom AS geography));
```

Now with `enable_seqscan` off:

```sql
SET enable_seqscan = off;

EXPLAIN (ANALYZE, BUFFERS)
SELECT name
FROM   businesses
WHERE  ST_DWithin(geom::geography,
                  ST_Point(-1.785, 50.700)::geography,
                  500);

SET enable_seqscan = on;
```

```
Index Scan using idx_businesses_geom_geography on businesses
  Index Cond: ((geom)::geography &&
               _st_expand('...', '500'))
  Filter: st_dwithin((geom)::geography, ...)
  Rows Removed by Filter: 2
```

The index is now used. The index condition uses `&&` (bounding-box overlap on
the spheroid) to quickly discard most rows, then `st_dwithin` rechecks the
exact distance for the survivors.

**6.4 — Verify the spatial join plan**

The containment join uses geometry-to-geometry operations, so
`idx_businesses_geom` (the plain geometry index) *is* used there:

```sql
SET enable_seqscan = off;

EXPLAIN (ANALYZE, BUFFERS)
SELECT b.name, n.name AS neighbourhood
FROM   businesses b
JOIN   neighborhoods n ON ST_Within(b.geom, n.geom);

SET enable_seqscan = on;
```

```
Nested Loop ...
  ->  Seq Scan on neighborhoods n  (6 rows — tiny table)
  ->  Index Scan using idx_businesses_geom on businesses b
        Index Cond: (geom @ n.geom)
        Filter: st_within(geom, n.geom)
```

For each neighbourhood polygon, `idx_businesses_geom` is used to find
businesses whose bounding box falls inside the neighbourhood's bounding box
(`geom @ n.geom`), then `st_within` rechecks the exact containment.

> **The index rule:** A GIST index on `geom geometry` accelerates
> geometry-to-geometry operations (`ST_Within`, `ST_Contains`, `ST_Intersects`,
> `&&`). A GIST index on `CAST(geom AS geography)` accelerates geography
> operations (`ST_DWithin(...::geography, ...)`, `<->` on geography). If you
> query both ways, create both indexes — they coexist happily on the same
> table.

---

## Summary — What You Should Now Know

You have worked through the core PostGIS toolkit for points, polygons, and
linear features. Here is a reference for everything used:

| Function / operator | What it does |
|---------------------|-------------|
| `ST_GeomFromText(wkt, srid)` | Parse WKT into a geometry with the given SRID |
| `ST_AsText(geom)` | Format geometry as WKT for display |
| `ST_SetSRID(ST_MakePoint(lon, lat), srid)` | Construct a point geometry |
| `ST_Point(lon, lat)::geography` | Construct a point and cast to geography |
| `geom::geography` | Cast a 4326 geometry to geography (distances now in metres) |
| `ST_SRID(geom)` | Return the SRID stored with a geometry |
| `ST_NPoints(geom)` | Count vertices in a geometry |
| `ST_Envelope(geom)` | Return the bounding-box rectangle |
| `ST_XMin/XMax/YMin/YMax(geom)` | Extract bounding-box extents |
| `ST_DWithin(a, b, d)` | True when the distance between a and b is ≤ d |
| `ST_Distance(a, b)` | Distance between two geometries (metres for geography) |
| `a::geography <-> b::geography` | KNN distance operator; use in ORDER BY for index acceleration |
| `ST_Within(a, b)` | True when a lies completely inside b |
| `ST_Contains(a, b)` | True when a contains b (inverse of ST_Within) |
| `ST_Area(geom::geography)` | Area in square metres on the spheroid |
| `CROSS JOIN LATERAL (... LIMIT 1)` | Nearest-neighbour join pattern |
| `USING GIST (geom)` | Create a GIST spatial index |

> **Geometry vs geography in one sentence:** Use `geometry` for storage and
> when working with projected coordinate systems where units are already metres
> or feet. Cast to `geography` any time you need distance, area, or proximity
> results in real-world units from SRID-4326 data.

The coordinates added in this chapter will carry forward. Chapter 12 extends
the `city_infrastructure` road network into a graph and uses a recursive CTE
to find the shortest path between two intersections.

---

*Going further: PostGIS supports many more geometry types — `MULTIPOLYGON`
for areas with holes, `GEOMETRYCOLLECTION` for mixed types, and 3D geometries
with a Z coordinate for elevation data. For routing specifically, `pgRouting`
builds on PostGIS to provide Dijkstra, A\*, and turn-restriction-aware
shortest-path algorithms over road network graphs. For importing real boundary
data, `shp2pgsql` converts ESRI Shapefiles directly into PostGIS-compatible
`INSERT` statements, and `ogr2ogr` handles GeoJSON, KML, GeoPackage, and dozens
of other formats.*
