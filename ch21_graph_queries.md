# Chapter 21 — Graph Queries: PostgreSQL 19's Property Graphs

> *Chapter 12 taught you how graph traversal works by making you write
> the recursion yourself. This chapter asks a narrower question: now
> that PostgreSQL 19 has a real, built-in graph query language, when
> does reaching for it actually pay off — and, just as importantly for
> software still in beta, what does it not do yet?*

---

## Background

PostgreSQL 19 adds `SQL/PGQ` — the ISO SQL:2023 standard for querying
relational tables as if they were a labeled property graph, without
copying anything into a separate graph database. Two new pieces of
syntax carry the whole feature:

- **`CREATE PROPERTY GRAPH`** — a schema object that declares which
  existing tables are *vertices* and which are *edges*, entirely on top
  of ordinary tables you already have. No new storage, no ETL — the
  same rows Chapter 12 queried with `WITH RECURSIVE` are reused
  directly.
- **`GRAPH_TABLE`** — a query construct, used inside `FROM`, that
  matches *patterns* against a property graph — `(a)-[r]->(b)` reads
  much closer to "a graph shape" than a self-join or a recursive CTE
  does.

The honest framing for this chapter, and the reason it stayed a
placeholder for months: PostgreSQL 19 was still in beta when this was
written, and nothing about SQL/PGQ had been run for real yet. Writing
it required standing up an actual PostgreSQL 19 instance and finding
out, empirically, what the beta actually supports — which turned out to
be a genuinely different (and smaller) feature than the placeholder
outline assumed. That gap is most of this chapter's real content.

---

## The Scenario

This chapter reuses Chapter 12's data unchanged: the 30-row Portsmith
government org chart (`city_org`) and the real road network derived
from Chapter 2's PostGIS geometry (`intersections`, `road_segments`).
Nothing new is seeded — the same graphs, queried a second way.

Because PostgreSQL 19 was beta at the time of writing, it runs in an
**isolated Docker container**, not on the same PostgreSQL 16 cluster
every earlier chapter has built up real, cumulative state on. See the
Environment Setup section below for exactly how that's wired up,
including three real gotchas hit getting a beta Debian package building
at all.

---

## Exercise Goals

By the end of this chapter you will be able to:

- Stand up a second, disposable PostgreSQL instance for trying beta
  features without touching a cluster you depend on.
- Declare a `CREATE PROPERTY GRAPH` over existing tables, including the
  self-referencing edge case (`city_org.manager_id` pointing back into
  `city_org` itself).
- Write `GRAPH_TABLE` pattern-matching queries, including undirected
  edge patterns.
- Know precisely which of SQL/PGQ's standard-defined features are
  actually implemented in PostgreSQL 19 beta2, versus which ones parse
  as errors today — verified directly, not assumed from the standard.
  Verified is not implied — the beta's own errors are the appendix.
- Decide, for a given traversal, whether `GRAPH_TABLE` is a genuine
  readability win today or whether Chapter 12's recursive CTE is still
  the only tool that actually works.

---

## Environment Setup — A Second Cluster for PostgreSQL 19

Rather than upgrading the machine's real PostgreSQL 16 install — which
carries real, cumulative state from twenty prior chapters — PostgreSQL
19 runs in a throwaway Docker container on port 5433, built from
`docker/ch21/Dockerfile` in this repo. Three real problems came up
getting that container running at all, each worth knowing if you build
something similar:

**1. PGDG's beta packages live in a `main <version>` *component*, not a
separate suite.** The first attempt pointed apt at a `bookworm-pgdg-testing`
suite that doesn't exist. PGDG actually publishes pre-release major
versions as an additional `main 19` component *inside* the normal
`bookworm-pgdg` suite — and that component alone isn't enough, since
`postgresql-19`/`postgresql-client-19` still depend on an up-to-date
`postgresql-common`/`libpq5` that only the plain `main` component
carries:

```
deb [signed-by=...] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main
deb [signed-by=...] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main 19
```

**2. Debian's `postgresql-19` package auto-creates a cluster on
install — and splits config from data.** Unlike the official
`postgres` Docker image (built from a plain source tarball), Debian's
packaging runs `pg_createcluster` as part of `apt-get install`,
producing a cluster whose data lives at `/var/lib/postgresql/19/main`
but whose `postgresql.conf`/`pg_hba.conf` live separately, under
`/etc/postgresql/19/main/`. Nothing in this book's earlier chapters hit
this, because they all install extensions into an *already-running*
cluster someone else set up — this is the first chapter to build a
cluster from scratch in a container image. A hand-rolled `initdb`
(needed to get `postgresql.conf` genuinely inside `PGDATA`, matching
what a plain `postgres -D $PGDATA` expects) collides with that
auto-created cluster, since its `PG_VERSION` file already exists.
Fixed by dropping the auto-created cluster at build time before
`initdb` ever runs:

```dockerfile
RUN apt-get install -y postgresql-19 postgresql-client-19 \
    && pg_dropcluster --stop 19 main
```

**3. Local-socket peer authentication doesn't match container UID
patterns.** The container runs as OS user `postgres` but the app role
is `chris` — `initdb`'s default local-socket auth (`peer`, matching OS
username to role name) rejects that combination outright. Fine for a
disposable scratch container: `initdb --auth-local=trust`.

Bring it up:

```bash
cd docker/ch21
docker compose up --build
```

```
$ psql -h localhost -p 5433 -U chris -d portsmith19 -c "SELECT version();"
WARNING:  authenticated with an MD5-encrypted password
DETAIL:  MD5 password support is deprecated and will be removed in a future release of PostgreSQL.
                                                     version
------------------------------------------------------------------------------------------------------------------
 PostgreSQL 19beta2 (Debian 19~beta2-1.pgdg12+1) on x86_64-pc-linux-gnu, compiled by gcc (Debian 12.2.0-14+deb12u1) 12.2.0, 64-bit
```

That `MD5 password support is deprecated` warning is itself a small,
real signal of what's coming in a future major version, seen live
rather than read about in a release note.

**Getting Chapter 12's data across.** `intersections.geom` is a real
PostGIS `GEOMETRY(POINT, 4326)` column, and PostGIS packages for a
still-beta PostgreSQL 19 aren't reliably available yet — so rather than
pull PostGIS into this scratch container just to store three points'
worth of geometry, the graph exercises below only need plain
coordinates, not spatial operators. Exported as `lon`/`lat` instead:

```bash
psql portsmith -c "\copy (SELECT id, name, ST_X(geom) AS lon, ST_Y(geom) AS lat FROM intersections ORDER BY id) TO 'intersections.csv' CSV HEADER"
psql portsmith -c "\copy (SELECT id, road_name, from_intersection, to_intersection, length_m FROM road_segments ORDER BY id) TO 'road_segments.csv' CSV HEADER"
psql portsmith -c "\copy (SELECT id, name, title, manager_id FROM city_org ORDER BY id) TO 'city_org.csv' CSV HEADER"

psql -h localhost -p 5433 -U chris -d portsmith19 -c "\copy intersections FROM 'intersections.csv' CSV HEADER"
psql -h localhost -p 5433 -U chris -d portsmith19 -c "\copy road_segments FROM 'road_segments.csv' CSV HEADER"
psql -h localhost -p 5433 -U chris -d portsmith19 -c "\copy city_org FROM 'city_org.csv' CSV HEADER"
```

All three row counts matched the source exactly: 30 `city_org` rows, 15
`intersections`, 19 `road_segments`.

---

## Exercises

### Exercise 1 — Confirming SQL/PGQ Is Really There

Before writing anything, confirm the feature actually exists in this
beta rather than trusting a release announcement. The clearest proof
isn't `\h` (client-side help text is bundled with whichever `psql`
binary you're running — the *server's* matching `psql`, not an older
local one, is what actually knows this syntax) but the system catalog
itself:

```sql
SELECT relname FROM pg_class WHERE relname LIKE '%propgraph%' OR relname = 'property_graphs';
```

```
                    relname
------------------------------------------------
 pg_propgraph_element
 pg_propgraph_element_label
 pg_propgraph_label
 pg_propgraph_label_property
 pg_propgraph_property
 property_graphs
 ...
```

Real, dedicated catalog tables — `CREATE PROPERTY GRAPH` isn't sugar
over some existing mechanism, it's genuinely new catalog infrastructure
in this release.

---

### Exercise 2 — Defining a Property Graph Over `city_org`

`city_org` is a self-referencing table: every row is a potential
vertex, and the `manager_id` foreign key back into the same table is
the edge. Declaring it:

```sql
CREATE PROPERTY GRAPH city_org_graph
    VERTEX TABLES ( city_org KEY (id) LABEL employee PROPERTIES ALL COLUMNS )
    EDGE TABLES (
        city_org AS reports_to
            KEY (id)
            SOURCE KEY (id) REFERENCES city_org (id)
            DESTINATION KEY (manager_id) REFERENCES city_org (id)
            LABEL reports_to
            NO PROPERTIES
    );
```

The real gotcha, found by iterating against the actual error messages:
the `SOURCE`/`DESTINATION` clauses look, from the documentation's
bracket notation, like `KEY (...) REFERENCES` and a trailing
`table (...)` are two independently optional pieces. In practice, on
this beta, only the combined form parses —
`KEY (local_column) REFERENCES vertex_table (vertex_key_column)` — read
exactly like an ordinary foreign key. Both of these failed:

```
SOURCE KEY (id) REFERENCES city_org
DESTINATION KEY (manager_id) REFERENCES city_org
-- ERROR:  syntax error at or near "DESTINATION"

SOURCE city_org (id)
-- ERROR:  syntax error at or near "("
```

Confirm it registered:

```sql
\dG+
```

```
                                List of property graphs
 Schema |      Name      |      Type      | Owner | Persistence |  Size   | Description
--------+----------------+----------------+-------+-------------+---------+-------------
 public | city_org_graph | property graph | chris | permanent   | 0 bytes |
```

(`0 bytes` because there's no new storage — the property graph is a
view over `city_org`, exactly as advertised.)

---

### Exercise 3 — Fixed-Depth Pattern Matching, Side by Side With Chapter 12

The most direct rewrite of Chapter 12's "walk from a leaf to the root"
recursive CTE, at a *known* depth. Leo Park is a Streets Crew member,
three levels below the Mayor:

```sql
SELECT * FROM GRAPH_TABLE (city_org_graph
    MATCH (a IS employee WHERE a.name = 'Leo Park')
          -[IS reports_to]-> (b IS employee)
          -[IS reports_to]-> (c IS employee)
          -[IS reports_to]-> (d IS employee)
    COLUMNS (a.name AS lvl0, b.name AS lvl1, c.name AS lvl2, d.name AS lvl3)
);
```

```
   lvl0   |   lvl1    |    lvl2     |     lvl3
----------+-----------+-------------+---------------
 Leo Park | Dana Ruiz | Marcus Webb | Coretta Vance
```

Chapter 12's version of this same question — "walk from any node to the
root" — needed `WITH RECURSIVE` because it works at *any* depth without
knowing it in advance. This version only works because 3 was chosen
ahead of time; a different employee at a different org level needs a
differently-shaped query. That tradeoff is exactly what the rest of
this chapter is about.

Where `GRAPH_TABLE` earns its keep even at fixed depth is queries whose
*shape*, not just their depth, is naturally graph-like. Compare "every
employee whose skip-level manager reports directly to the Mayor" — a
2-hop pattern that reads close to the English sentence describing it:

```sql
SELECT * FROM GRAPH_TABLE (city_org_graph
    MATCH (a IS employee) -[IS reports_to]-> (b IS employee) -[IS reports_to]-> (c IS employee)
    COLUMNS (a.name AS employee, a.title, b.name AS skip_level_manager, c.name AS director)
) WHERE director = 'Coretta Vance'
ORDER BY employee;
```

```
    employee    |              title              | skip_level_manager |   director
----------------+---------------------------------+--------------------+---------------
 Colin Marsh    | Budget Analyst                  | Julian Ostrowski   | Coretta Vance
 Dana Ruiz      | Streets & Sanitation Supervisor | Marcus Webb        | Coretta Vance
 Felix Wren     | Parks Maintenance Supervisor    | Aisha Bonner       | Coretta Vance
 Grace Halloway | Senior Permit Reviewer          | Helena Cross       | Coretta Vance
 Hugo Petrakis  | Database Administrator          | Wendell Achebe     | Coretta Vance
 Marcus Reilly  | Patrol Captain                  | Diane Okonjo       | Coretta Vance
 Paula Mensah   | Records Sergeant                | Diane Okonjo       | Coretta Vance
 Ray Castellano | Building Inspector              | Helena Cross       | Coretta Vance
```

A self-join written by hand to answer this — `city_org a JOIN city_org b
ON a.manager_id = b.id JOIN city_org c ON b.manager_id = c.id` — returns
the identical rows. Whether the pattern-matching form is actually
*more* readable than that join is genuinely a judgment call; it's at
least no worse, and it stops looking like an accident of how the join
happened to be written.

---

### Exercise 4 — The Wall: Variable-Length Paths Aren't Supported Yet

This is the exercise the original chapter outline assumed would work,
and the actual finding worth this whole chapter existing: **SQL/PGQ's
quantified path patterns — the `{m,n}` repetition syntax that makes
"walk zero-or-more/one-or-more hops" possible — are not implemented in
PostgreSQL 19 beta2.** Two different attempts, two different real
errors:

```sql
MATCH (a IS employee WHERE a.name = 'Leo Park') (-[IS reports_to]->(IS employee)){1,10} (root IS employee)
-- ERROR:  unsupported element pattern kind: "nested path pattern"

MATCH (a IS employee WHERE a.name = 'Leo Park') -[IS reports_to]->{1,10} (root IS employee)
-- ERROR:  element pattern quantifier is not supported
```

Both forms the SQL:2023 standard defines for repeating a path — a
quantified nested group, and a quantifier directly on an edge pattern —
are parsed far enough to be recognized and then explicitly rejected as
unsupported. This isn't a syntax mistake on this book's part; it's a
real, verified gap in what's shipped so far in this beta.

The practical consequence: **Chapter 12's recursive CTEs are still the
only tool in PostgreSQL 19 beta2 that can walk a graph to an unknown
depth.** "Walk any node to the root," "find the shortest path with no
upper bound on hops," and "detect a cycle by construction" — all three
of Chapter 12's headline capabilities — have no `GRAPH_TABLE`
equivalent yet, no matter how the pattern is phrased. Whether that
changes before PostgreSQL 19's actual GA release is worth checking
directly against a later beta or release candidate, the same way this
finding itself was reached: by running the query, not by reading the
standard.

---

### Exercise 5 — The Road Network: Undirected Edges and a Bounded-Hop Workaround

A second property graph, over the real road network:

```sql
CREATE PROPERTY GRAPH road_graph
    VERTEX TABLES ( intersections KEY (id) LABEL intersection PROPERTIES ALL COLUMNS )
    EDGE TABLES (
        road_segments AS segment
            KEY (id)
            SOURCE KEY (from_intersection) REFERENCES intersections (id)
            DESTINATION KEY (to_intersection) REFERENCES intersections (id)
            LABEL road
            PROPERTIES ALL COLUMNS
    );
```

Roads are two-way, but `road_segments` only stores one direction per
row (`from_intersection` → `to_intersection`) — the same directionality
question Chapter 12 handled with a `UNION` of both directions.
`GRAPH_TABLE` has a cleaner answer built in: an edge pattern with no
arrowhead, `-[ ]-`, matches the edge in either direction:

```sql
SELECT * FROM GRAPH_TABLE (road_graph
    MATCH (a IS intersection WHERE a.name = 'Harbour Walk & Anchor Lane') -[r IS road]- (b IS intersection)
    COLUMNS (a.name AS from_x, b.name AS to_x, r.road_name, r.length_m)
);
```

```
           from_x            |             to_x             |  road_name   | length_m
-----------------------------+------------------------------+--------------+----------
 Harbour Walk & Anchor Lane  | Portside Drive & Anchor Lane |  Anchor Lane |    445.0
 Harbour Walk & Anchor Lane  | Harbour Walk & Ring Road     | Harbour Walk |   1554.2
```

Real, correct, no `UNION` needed — a genuine, verified win over the
Chapter 12 approach for this specific piece.

Chapter 12 Exercise 5 found a real fewest-hops-vs-shortest-distance
divergence using unbounded BFS. That's off the table here (Exercise
4), but a *bounded* version — "how far can I get in exactly 2 hops" —
still works, by chaining two fixed edge patterns and summing their
properties:

```sql
SELECT * FROM GRAPH_TABLE (road_graph
    MATCH (a IS intersection WHERE a.name = 'Harbour Walk & Anchor Lane')
          -[r1 IS road]- (b IS intersection)
          -[r2 IS road]- (c IS intersection)
    COLUMNS (a.name AS start_x, c.name AS end_x, r1.length_m + r2.length_m AS total_m)
)
WHERE end_x <> start_x
ORDER BY total_m;
```

```
          start_x            |           end_x            | total_m
------------------------------+----------------------------+---------
 Harbour Walk & Anchor Lane   | Portside Drive & Ring Road |  1998.1
 Harbour Walk & Anchor Lane   | Portside Drive & Ring Road |  1999.1
 Harbour Walk & Anchor Lane   | Dock Road & Ring Road      |  7665.6
```

A real, small, genuinely interesting result: two *different* 2-hop
routes reach the same intersection, 1 meter apart — exactly the kind of
near-tie a shortest-path query needs to break correctly, which
`ORDER BY total_m LIMIT 1` does here without incident. But notice what
this query *is*: one fixed depth, hand-written. Going to 3 hops means
writing a third copy of the pattern; there's no way to ask for "up to N
hops" in one query the way Chapter 12's recursive CTE does natively.
This is Exercise 4's wall again, in a second dataset.

---

## Decision Guide: Recursive CTE vs. `GRAPH_TABLE`, as of PostgreSQL 19 Beta2

| Need | Use |
|---|---|
| Traversal to an unknown or unbounded depth (walk to root, true shortest path, cycle detection) | Chapter 12's `WITH RECURSIVE` — still the only thing that works |
| A fixed-depth, pattern-shaped query (skip-level lookups, "friend of a friend," a specific N-hop join) | `GRAPH_TABLE` — genuinely more declarative than the equivalent self-join, and undirected (`-[ ]-`) edges are a real, clean win over hand-written `UNION` |
| Everything needs to stay inside one cluster, no new storage | Either — both query existing tables directly |
| A workload that's *fundamentally* graph-shaped at production scale (millions of nodes, deep unbounded traversal as the primary access pattern) | Neither, necessarily — this is the point in the decision tree where a dedicated graph database (Neo4j and similar) starts to be worth the operational cost of running a second system, though nothing in this chapter's small, in-memory-sized dataset actually demonstrates that threshold being crossed |

The honest summary: PostgreSQL 19 beta2 ships real, working
infrastructure for declaring and pattern-matching property graphs, and
for the specific class of fixed-depth queries it supports, it's a
genuine readability improvement over hand-written joins. It does not
yet replace recursive CTEs for anything Chapter 12 actually needed them
for. That could easily change before general availability — quantified
path patterns are explicitly part of the SQL:2023 standard this feature
implements, and "not yet supported" read from a beta's own error
message is a very different claim than "not supported," worth
re-verifying against whatever release you're actually running.

---

<img src="imgs/ch21_query_model_wall.svg" alt="Diagram contrasting two query models over the same city_org and road_segments tables. Left path: Chapter 12's WITH RECURSIVE CTE, unbounded depth, working today for walk-to-root, shortest-path, and cycle detection. Right path: PostgreSQL 19 beta2's CREATE PROPERTY GRAPH and GRAPH_TABLE, which succeeds for fixed-depth pattern matches and undirected edges, but hits a wall at quantified variable-length path patterns, marked with the two real captured errors: unsupported element pattern kind nested path pattern, and element pattern quantifier is not supported."/>

---

## Summary — What You Should Now Know

| Tool | What it's actually for |
|---|---|
| `CREATE PROPERTY GRAPH` | Declares existing tables as a labeled graph — no new storage, a view over what you already have |
| `GRAPH_TABLE` with fixed-depth patterns | A genuinely more declarative way to write a known-depth traversal or self-join |
| `-[ ]-` (undirected edge pattern) | A real, clean replacement for a hand-written `UNION` of both directions |
| Quantified path patterns (`{m,n}`) | Standard-defined, but **not implemented in PostgreSQL 19 beta2** — verified via two distinct real errors, not assumed |
| Chapter 12's `WITH RECURSIVE` | Still the only working tool in this release for any traversal of unknown or unbounded depth |
| A second, disposable Docker cluster | The right way to try a beta major version without touching a cluster carrying real cumulative state |

**The key design insight** from this chapter is less about SQL/PGQ
itself than about how to evaluate a beta feature honestly: read what
the standard promises, then verify against the actual release what's
really there, and report the difference plainly rather than writing the
chapter the outline assumed would be true. Every other chapter in this
book got to lean on a stable, GA PostgreSQL; this one is a reminder
that "run the real thing" sometimes means the real thing tells you
"not yet."

---

*Going further: Chapters 22 and 23 return to graph-shaped data from a
completely different angle — RDF triples and SPARQL via `pg-ripple`,
rather than SQL/PGQ's property-graph model over relational tables. It's
worth holding this chapter's central finding in mind going in: a young
extension or a beta feature is worth exactly what you can verify about
it live, not what its README or its standard promises.*
