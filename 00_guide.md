# PostgreSQL Beyond Relational: A Lab Book

## Overview

This lab book explores PostgreSQL's extended capabilities through hands-on exercises. Each chapter introduces a feature area, builds synthetic data to explore it, and walks through progressively complex exercises. The theme running through all chapters is a fictional **urban data platform** for the city of Portsmith — a mid-sized city with neighborhoods, businesses, events, documents, and infrastructure. This shared domain lets each chapter's data feel connected even as the techniques diverge.

---

## Chapter Map

### Chapter 1 — JSONB: Semi-Structured Data Without a Schema Tax

**Concept:** Store, index, and query nested JSON documents alongside relational columns. Explore GIN indexing, path operators, and `jsonb_path_query`.

**Synthetic data:** A `businesses` table with a fixed relational spine (id, name, address) and a `details` JSONB column holding heterogeneous metadata — hours, tags, amenities, ratings, social links — that varies by business category.

**Exercises:**
1. Insert documents with varying schemas into the same column.
2. Query with `->`, `->>`, `@>`, `?`, and `#>>` operators.
3. Create a GIN index and confirm it is used via `EXPLAIN ANALYZE`.
4. Use `jsonb_set` and `jsonb_insert` to patch documents in place.
5. Flatten JSONB arrays into rows with `jsonb_array_elements`.
6. Write a `jsonb_path_query` to find businesses open on Sundays after 5 PM.

---

### Chapter 2 — PostGIS: Geospatial Queries on Real Geometry

**Concept:** Store points, polygons, and line strings. Run proximity, containment, and routing queries with spatial indexes.

**Synthetic data:** Portsmith neighborhood polygons (`neighborhoods`), business point locations (extends Chapter 1), a `city_infrastructure` table with roads as linestrings, and a `parks` table with polygon geometry.

**Exercises:**
1. Load neighborhood polygons with `ST_GeomFromText` / WKT.
2. Find all businesses within 500 meters of a given point using `ST_DWithin`.
3. Determine which neighborhood each business falls in using `ST_Within` / `ST_Contains`.
4. Compute the area of each neighborhood in square kilometers.
5. Find the nearest park to each business using `ST_Distance` + lateral join.
6. Create a GIST index and verify spatial query plans.

---

### Chapter 3 — Job Queues: `FOR UPDATE SKIP LOCKED`

**Concept:** Build a reliable, concurrent job queue inside PostgreSQL — no external broker required. Explore locking semantics, worker concurrency, and dead-letter handling.

**Synthetic data:** A `jobs` table with status, payload (JSONB), priority, created/claimed/completed timestamps, and a retry counter. Seed with synthetic work items representing city permit applications.

**Exercises:**
1. Design the queue schema with proper indexes.
2. Write the atomic `SELECT … FOR UPDATE SKIP LOCKED LIMIT 1` claim query.
3. Simulate concurrent workers in multiple `psql` sessions; observe that no two workers claim the same row.
4. Implement a heartbeat/timeout mechanism to reclaim stalled jobs.
5. Add a dead-letter table for jobs that exceed max retries.
6. Benchmark throughput at various worker counts using `pgbench`.

---

### Chapter 4 — Full-Text Search: `tsvector`, Stopwords, and Ranking

**Concept:** Build a full-text search engine inside PostgreSQL. Learn how documents are tokenized, how stopwords are removed, and how results are ranked with `ts_rank`.

**Synthetic data:** A `city_documents` table holding council meeting minutes, zoning ordinances, and public notices. Plain-text `body` column, metadata columns for date and document type.

**Exercises:**
1. Convert `body` to `tsvector` using `to_tsvector('english', body)`.
2. Inspect how stopwords are removed; compare raw tokens to the vector.
3. Add a generated `tsvector` column and a GIN index.
4. Query with `to_tsquery` and `plainto_tsquery`; understand operator differences.
5. Rank results with `ts_rank` and `ts_rank_cd`; display highlighted snippets with `ts_headline`.
6. Create a custom text search configuration that adds domain-specific stop words (e.g., "portsmith", "city", "council").

---

### Chapter 5 — Fuzzy Matching: `pg_trgm`

**Concept:** Find records that *approximately* match a query — misspellings, OCR errors, name variants. Explore trigram similarity, distance, and the `%` operator.

**Synthetic data:** A `residents` table with names that include intentional misspellings and variant spellings, plus a `business_names` lookup. Extends Chapter 1 data.

**Exercises:**
1. Enable `pg_trgm` and compute `similarity()` between string pairs.
2. Use the `%` operator to find near-matches with a configurable threshold.
3. Use `word_similarity()` for partial-string matching (substring fuzzy search).
4. Create a GIN trigram index and confirm it accelerates `LIKE '%term%'` queries.
5. Build a "did you mean?" query: given a misspelled business name, return the top 5 closest matches by similarity score.
6. Compare trigram matching vs. full-text search for short, keyword-style inputs.

---

### Chapter 6 — Vector Search: `pgvector` for Embeddings

**Concept:** Store and query high-dimensional vector embeddings for semantic search over documents, images, and other media. Understand ANN indexes (IVFFlat, HNSW).

**Synthetic data:** Pre-computed embeddings (384-dimensional, from a sentence-transformer model) for `city_documents` from Chapter 4, plus image embeddings for a `city_photos` table (synthetic float arrays).

**Exercises:**
1. Install `pgvector`, create a `vector(384)` column.
2. Insert embeddings and query exact nearest neighbors with `<->` (L2), `<#>` (inner product), `<=>` (cosine).
3. Build an IVFFlat index; tune `lists` and `probes` parameters.
4. Build an HNSW index; compare recall and build time vs. IVFFlat.
5. Implement semantic search: embed a query string (pre-computed), find the top-10 most similar documents.
6. Hybrid search: combine `ts_rank` (keyword) with cosine distance (semantic) using a weighted score.

---

### Chapter 7 — IP and Network Filtering: `ip4r`

**Concept:** Store IPv4/IPv6 addresses and CIDR blocks natively. Perform fast containment and overlap queries using range-optimized GiST indexes.

**Synthetic data:** A `network_events` table (login attempts, API calls) with source IP, timestamp, and event type. A `blocklists` table with CIDR ranges representing known bad actors, corporate subnets, and ISP blocks.

**Exercises:**
1. Enable `ip4r`; compare storage and operators vs. built-in `inet`/`cidr` types.
2. Check whether a given IP falls inside any blocklist CIDR using `>>` / `<<=`.
3. Find all events from IPs within a given netblock using a GiST index.
4. Aggregate events by /24 subnet using `network()` and `masklen()`.
5. Identify IPs that appear in both an allowlist and blocklist (overlap detection).
6. Build a real-time "is this IP blocked?" function using a GiST-indexed lookup.

---

### Chapter 8 — Declarative Partitioning and BRIN Indexes

**Concept:** Partition large tables by range or list for manageability and query pruning. Use BRIN indexes for append-only, naturally ordered data where B-tree overhead is unwarranted.

**Synthetic data:** A `sensor_readings` table with IoT-style timestamped readings from city infrastructure sensors (temperature, traffic count, air quality). Tens of millions of rows generated with `generate_series`.

**Exercises:**
1. Create a range-partitioned table by month; attach child partitions.
2. Insert data and observe automatic partition routing.
3. Query with a date filter; use `EXPLAIN` to confirm partition pruning.
4. Create a BRIN index on the timestamp column of one partition; compare to B-tree.
5. Drop an old partition (instant); contrast with `DELETE` on an unpartitioned table.
6. Add a list partition for sensor type; combine range + subpartitioning.

---

### Chapter 9 — Materialized Views

**Concept:** Pre-compute expensive aggregations and store them as physical tables. Explore refresh strategies, incremental patterns, and when to use views vs. materialized views vs. summary tables.

**Synthetic data:** Aggregations over previous chapters' data — daily business activity summaries, neighborhood statistics, document search hit counts.

**Exercises:**
1. Create a materialized view summarizing sensor readings by day and sensor type.
2. Query the view; compare execution time to the raw aggregate.
3. `REFRESH MATERIALIZED VIEW CONCURRENTLY` — understand the `UNIQUE` index requirement.
4. Simulate a nightly refresh job using `pg_cron` (or a scheduled psql call).
5. Chain materialized views: a daily rollup feeding a monthly rollup.
6. Detect staleness: write a query that checks `pg_matviews.last_refresh` and warns if older than N hours.

---

### Chapter 10 — PostgREST: A Web-Native REST API from Your Schema

**Concept:** Expose PostgreSQL tables, views, and functions as a RESTful HTTP API with zero application code. Learn role-based access, row-level security, and computed columns.

**Synthetic data:** Uses all prior tables. Adds a `api` schema with curated views designed for public consumption.

**Exercises:**
1. Install and configure PostgREST; connect it to the Portsmith database.
2. `GET /businesses` — filter, paginate, and sort via query parameters.
3. `POST /jobs` — insert a new permit application through the API.
4. Create a database role with limited privileges; verify PostgREST enforces it.
5. Enable Row Level Security on `residents`; verify tenants only see their own rows.
6. Expose an RPC endpoint: a stored function that runs a fuzzy business-name search and returns ranked results.

---

### Chapter 11 — Window Functions: Analytics Beyond GROUP BY

**Concept:** Perform calculations across a set of rows related to the current row — without collapsing them into a single output row. Covers `OVER()`, `PARTITION BY`, `ORDER BY` inside a window, frame clauses, and the most useful window functions: `ROW_NUMBER`, `RANK`, `DENSE_RANK`, `LAG`, `LEAD`, `FIRST_VALUE`, `LAST_VALUE`, and running aggregates.

> **Note:** This chapter builds the mental model from first principles before introducing syntax. If window functions are new to you, read the concept sections carefully before attempting the exercises.

**Synthetic data:** Uses `sensor_readings` (Chapter 8) for time-series patterns, `businesses` (Chapter 1) for ranking within categories, and `network_events` (Chapter 7) for session detection.

**Exercises:**
1. Understand the mental model: visualize the "window frame" row-by-row with a small hand-crafted dataset.
2. Rank businesses within each neighborhood by rating using `RANK()` and `DENSE_RANK()`; observe how ties are handled differently.
3. Compute a 7-day rolling average of sensor readings using a frame clause (`ROWS BETWEEN 6 PRECEDING AND CURRENT ROW`).
4. Use `LAG()` and `LEAD()` to detect day-over-day changes in sensor readings.
5. Detect login sessions in `network_events` using the "gaps and islands" pattern with `ROW_NUMBER()`.
6. Compute a running total and a percentage-of-partition-total in a single query over business revenue data.

---

### Chapter 12 — Recursive CTEs: Graphs and Hierarchies

**Concept:** Query tree structures and graphs using `WITH RECURSIVE`. Traverse parent-child relationships, find shortest paths, and flatten arbitrary-depth hierarchies — all in SQL.

**Synthetic data:** A `city_org` table representing Portsmith's departmental hierarchy (recursive self-join). A `road_segments` table representing road connectivity as a graph (for pathfinding). Extends the PostGIS road data from Chapter 2.

**Exercises:**
1. Write a recursive CTE to walk the org chart from any node to the root.
2. Find all employees (direct and indirect) under a given department head.
3. Compute the depth of each node and render an indented tree with `repeat('  ', depth)`.
4. Detect cycles in a graph using the cycle-detection clause (`CYCLE … SET … USING`).
5. Find the shortest path between two road intersections using a breadth-first recursive CTE.
6. Flatten a category hierarchy for use in a faceted search (all ancestors of a leaf node).

---

### Chapter 13 — `LISTEN` / `NOTIFY`: Database-Native Pub/Sub

**Concept:** Emit and receive real-time notifications directly from PostgreSQL, without a message broker. Use triggers to publish change events; subscribe from Python clients using `psycopg`.

**Synthetic data:** Uses the `jobs` table from Chapter 3. Adds a `notifications` log table. A trigger fires `NOTIFY` when a job changes status.

**Exercises:**
1. Send a manual `NOTIFY` from one `psql` session and receive it in another with `LISTEN`.
2. Write a trigger that calls `pg_notify()` with a JSON payload on job status changes.
3. Subscribe from a Python 3.12 script using `psycopg`'s async notification support.
4. Fan out to multiple channels: one per job type.
5. Implement a simple debounce: suppress notifications fired within 1 second of the previous one (using a state table).
6. Compare `LISTEN/NOTIFY` throughput limits to when you'd graduate to a dedicated broker.

---

### Chapter 14 — Advisory Locks: Distributed Coordination

**Concept:** Use PostgreSQL's application-level locking API to coordinate across processes without touching any rows — leader election, singleton cron jobs, named critical sections.

**Synthetic data:** No new tables required. Uses the `jobs` table from Chapter 3 and simulates multiple Python worker processes.

**Exercises:**
1. Acquire and release a session-level advisory lock; observe that a second session blocks.
2. Use `pg_try_advisory_lock()` for non-blocking "is anyone else doing this?" checks.
3. Implement a leader-election pattern: N workers race for a lock; only one proceeds.
4. Use transaction-level advisory locks to guard a critical section within a job claim transaction.
5. Inspect held advisory locks via `pg_locks`; build a diagnostic query.
6. Demonstrate the pitfall of session locks in a connection pool and how to avoid it.

---

### Chapter 15 — Custom Types, Domains, and Enums

**Concept:** Push business rules down into the schema using PostgreSQL's type system. Enums prevent invalid states; domains add constraints to base types; composite types group related fields.

**Synthetic data:** Extends the `businesses`, `jobs`, and `residents` tables with typed columns: a `job_status` enum, a `us_zip` domain, a `contact_info` composite type.

**Exercises:**
1. Create a `job_status` enum; observe that invalid values are rejected at the DB level.
2. Add a new value to an existing enum with `ALTER TYPE … ADD VALUE`; understand ordering constraints.
3. Define a `positive_integer` domain; verify constraint enforcement.
4. Create a `contact_info` composite type; store and query it as a column.
5. Use a domain to enforce email format with a `CHECK` constraint and `~` regex.
6. Observe how PostgREST and `psycopg` automatically reflect enum values to application code.

---

### Chapter 16 — Generated Columns

**Concept:** Let PostgreSQL maintain derived values automatically — no triggers, no application sync logic. Covers stored generated columns, their interaction with indexes, and practical patterns.

**Synthetic data:** Extends `businesses` (Chapter 1) with a generated `search_vector tsvector` column, and `sensor_readings` (Chapter 8) with a generated `reading_date date` column extracted from the timestamp.

**Exercises:**
1. Add a stored generated column that extracts the date portion of a timestamp.
2. Create a generated `tsvector` column on `city_documents`; replace the manual approach from Chapter 4.
3. Index a generated column; verify the index is used transparently.
4. Observe that generated columns cannot be written to directly.
5. Use a generated column to normalize a phone number format for consistent querying.
6. Compare the generated column approach to triggers for keeping derived data in sync.

---

### Chapter 17 — Foreign Data Wrappers: PostgreSQL as a Data Hub

**Concept:** Query remote data sources — other PostgreSQL databases, CSV files, and S3/Parquet — as if they were local tables. No ETL pipeline required.

**Synthetic data:** A second "legacy" PostgreSQL database with older Portsmith records. A CSV file of census data. An S3-compatible store (MinIO, run locally) with Parquet files of historical sensor readings.

**Exercises:**
1. Install `postgres_fdw`; create a foreign server and user mapping; query a remote table.
2. Push down filters to the remote server; confirm with `EXPLAIN`.
3. Use `file_fdw` to query a CSV file as a table; join it against local data.
4. Import an entire remote schema with `IMPORT FOREIGN SCHEMA`.
5. Write through a foreign table: `INSERT` into a remote table via the FDW.
6. Discuss the `parquet_s3_fdw` pattern for querying data lake files — architecture overview and setup sketch.

---

### Chapter 18 — Logical Replication and Change Data Capture

**Concept:** Stream every row-level change out of PostgreSQL using logical replication slots. Understand the publication/subscription model, and how tools like Debezium sit on top of it.

**Synthetic data:** Uses the `businesses` and `jobs` tables. A second local PostgreSQL instance acts as the subscriber.

**Exercises:**
1. Configure `wal_level = logical`; create a publication on selected tables.
2. Create a subscription on a second instance; verify changes replicate in real time.
3. Inspect the replication slot and lag via `pg_replication_slots` and `pg_stat_replication`.
4. Filter publications by row (`WHERE` clause on `CREATE PUBLICATION`) to replicate only active businesses.
5. Consume the logical replication stream directly from Python using `psycopg`'s replication protocol support.
6. Discuss the Debezium architecture: how it consumes a replication slot and produces Kafka events.

---

### Chapter 19 — `pg_cron`: Scheduled Jobs Inside PostgreSQL

**Concept:** Schedule recurring SQL tasks without an external scheduler. Understand cron syntax in PostgreSQL, job safety (idempotency, overlap prevention), and monitoring.

**Synthetic data:** Uses materialized views from Chapter 9 and the dead-letter queue from Chapter 3.

**Exercises:**
1. Install `pg_cron`; schedule a simple `REFRESH MATERIALIZED VIEW` every hour.
2. Inspect scheduled jobs and run history via `cron.job` and `cron.job_run_details`.
3. Prevent overlapping runs: use an advisory lock inside the scheduled function.
4. Schedule a dead-letter sweep: requeue stalled jobs older than 30 minutes.
5. Use `cron.schedule_in_database()` to scope a job to a specific database.
6. Unschedule and modify jobs; handle failures gracefully by checking `cron.job_run_details.status`.

---

### Chapter 20 — `pg_stat_statements` and Query Performance

**Concept:** Identify slow and high-frequency queries, read `EXPLAIN (ANALYZE, BUFFERS)` output, and apply targeted fixes. Treat observability as a first-class feature.

**Synthetic data:** Uses all prior tables. Intentionally introduces slow queries (missing indexes, implicit casts, N+1 patterns) to diagnose and fix.

**Exercises:**
1. Enable `pg_stat_statements`; find the top 10 queries by total execution time.
2. Read a full `EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)` plan; identify each node type.
3. Spot an implicit cast causing an index to be skipped; fix the query or the schema.
4. Diagnose and resolve a sequential scan on a large table by adding an appropriate index.
5. Use `auto_explain` to log slow query plans automatically.
6. Build a monitoring query: track plan regressions by comparing `pg_stat_statements` snapshots before and after a deploy.

---

### Chapter 21 — Graph Queries: PostgreSQL 19's Property Graphs

**Concept:** Query graph-structured data using PostgreSQL 19's native
property graph support (the SQL/PGQ standard — `CREATE PROPERTY GRAPH` and
`GRAPH_TABLE` pattern-matching queries), and contrast it directly with the
hand-rolled `WITH RECURSIVE` approach Chapter 12 already built. Written and
verified live against a real PostgreSQL 19 beta2 instance — and the real
finding is a genuine gap: quantified/variable-length path patterns
(`{m,n}`, nested groups) are not implemented yet in this beta, confirmed
via two distinct captured errors. `GRAPH_TABLE` is a real, working, more
declarative tool for *fixed-depth* pattern matches and undirected edges;
Chapter 12's recursive CTEs remain the only working tool in this release
for anything of unknown or unbounded depth — walk-to-root, true shortest
path, and cycle detection all still require Chapter 12's approach.

**Synthetic data:** Reuses `city_org` and `road_segments`/`intersections`
from Chapter 12 unchanged, migrated (via `\copy`, `intersections.geom`
flattened to plain `lon`/`lat` columns to avoid needing PostGIS in a
still-beta cluster) into an isolated PostgreSQL 19 beta2 Docker container
rather than the shared PostgreSQL 16 host every earlier chapter runs
against — see `docker/ch21/` and the chapter's own Environment Setup
section for the real packaging gotchas hit standing it up.

**Exercises:**
1. Stand up PostgreSQL 19 beta2 in an isolated Docker container (not the
   shared PG16 host) and confirm SQL/PGQ's catalog objects
   (`pg_propgraph_*`, `property_graphs`) are genuinely present.
2. Define `city_org_graph`, a self-referencing property graph over
   `city_org` (`manager_id` as the `reports_to` edge), with
   `CREATE PROPERTY GRAPH`.
3. Rewrite a *known-depth* slice of Chapter 12's "walk from any node to
   the root" query as a fixed-length `GRAPH_TABLE` pattern match, side by
   side with the `WITH RECURSIVE` version; also demonstrate a 2-hop
   "skip-level manager" pattern as a case where `GRAPH_TABLE` reads more
   declaratively than the equivalent self-join.
4. Attempt Chapter 12's actual variable-length traversal via quantified
   path patterns; document the two real "not supported" errors this beta
   returns and what that means for what SQL/PGQ can't yet replace.
5. Define `road_graph` over `intersections`/`road_segments`; use
   `GRAPH_TABLE`'s undirected edge pattern (`-[ ]-`) as a real, clean
   replacement for Chapter 12's `UNION`-of-both-directions approach, and a
   bounded (fixed 2-hop) shortest-path-shaped query as the closest
   available substitute for true BFS today.
6. Decision guide: recursive CTE (unbounded depth, still the only option)
   vs. `GRAPH_TABLE` (fixed-depth pattern shapes, today) vs. a dedicated
   graph database (Neo4j and similar) — what each is actually for, as of
   this specific beta.

---

### Chapter 22 — RDF Triple Stores: `pg-ripple`

**Concept:** Model data as RDF triples (subject–predicate–object facts)
instead of rows or documents, and query them with SPARQL — a genuinely
different data model from anything else in this book. Contrast directly
with Chapter 1's JSONB (schema-flexible, but still document-shaped) and
Chapters 12/21's graph traversal over relational tables. Written and
verified live against a real `pg-ripple` 0.128.0 build on PostgreSQL 18 —
and, continuing Chapter 21's pattern, hands-on testing found both a real
win (SPARQL property paths do the unbounded-depth traversal that
PostgreSQL 19 beta2's `GRAPH_TABLE` explicitly can't yet) and real gaps
(SHACL insert-time enforcement needs a second, uninstalled extension;
custom Datalog rule chaining across multiple body atoms produces a
reproducibly wrong result).

**Synthetic data:** Recast a slice of the existing Portsmith domain as
triples rather than new invented data — the 48 `businesses` (Chapter 1)
and 6 `neighborhoods` (Chapter 2), plus genuinely derived neighborhood
adjacency (`ST_Touches` against Chapter 2's real polygons, the same
technique Chapter 12 used for its road graph) — exported from the live
PostgreSQL 16 database by `data/ch22_export_turtle.py` and loaded into an
isolated PostgreSQL 18 container via `pg_ripple.load_turtle()`.

**Exercises:**
1. Build `pg-ripple` from source in an isolated PostgreSQL 18 Docker
   container (`docker/ch22/`) — real Rust/`pgrx` build, including the
   `cargo-pgrx`-must-exactly-match-`pgrx`-version trap that broke the
   first build attempt, and the same `shared_preload_libraries` gotcha
   Chapters 19/20 hit, this time for `pg-ripple`'s HTAP merge worker.
2. Export Portsmith businesses/neighborhoods/adjacency as Turtle and load
   with `load_turtle()`.
3. Run real SPARQL `SELECT` queries via `sparql()`, including `GROUP
   BY`/`COUNT` aggregation.
4. Property paths (`+`, and the undirected `(:p|^:p)+` combinator): a
   direct rerun of Chapter 21's variable-length-traversal wall, this time
   succeeding — plus a real, verified cycle found via the undirected
   combinator, echoing Chapter 12's cycle-detection lesson in SPARQL.
5. SHACL validation: a real, precise `shacl_score()`/`shacl_report_scored()`
   violation report against a deliberately malformed business — and the
   real finding that insert-time rejection (`enable_shacl_monitors()`)
   requires a separate extension (`pg_trickle`) not installed here.
6. Custom Datalog rules via `load_rules()`/`infer()`: real rule-syntax
   gotchas found by iterating on parser errors, and a reproduced,
   isolated-test-confirmed bug where multi-atom rule body chaining
   silently produces the wrong inferred triple, independent of body atom
   order.

---

### Chapter 23 — Ontologies and Knowledge Graphs for AI Workflows

**Concept:** Step back from `pg-ripple`'s mechanics (Chapter 22) to the
design layer: what an ontology actually is (a schema for *meaning* —
classes, hierarchies, relationships a machine can check), general prior
art (library classification, biomedical ontologies, `schema.org`), and
why AI workflows specifically — RAG grounding, agent context,
explainability, neuro-symbolic hybrids — lean on this. Written and
verified live against the same `pg-ripple` container Chapter 22 built.
The chapter's central, real finding is severe: `pg_ripple.infer('rdfs')`
does not merely fail to propagate instance types up a class hierarchy —
it was verified, on both an isolated test and the full real dataset, to
**overwrite existing correct classification data** with spurious,
nonsensical facts. The direct-query workaround (`rdfs:subClassOf*`
property paths, no `infer()` involved) works correctly and is what the
chapter's own hybrid-retrieval exercise actually uses.

**Synthetic data:** Chapter 12's real 48-row, 3-level `categories` tree,
reissued as an `rdfs:subClassOf` class hierarchy (`data/
ch23_export_ontology.py`), with every Chapter 1 business reclassified as
an instance of its specific category class rather than Chapter 22's flat
string. Chapter 6's `city_documents` embeddings (unchanged, still on
PostgreSQL 16) and Chapter 5's 12 real ground-truth duplicate resident
pairs (`residents.true_duplicate_of`) are reused, not re-seeded.

**Exercises:**
1. Design the ontology by hand in Turtle (a short sample), then generate
   the real 48-class hierarchy and business reclassification from the
   live database — including correctly resolving Chapter 12's real
   `"pub"` name collision (it exists under both `restaurant` and
   `entertainment`) by scoping the lookup per business.
2. Load it into the Chapter 22 container; verify the class hierarchy
   itself is correct and reflexive via a direct `rdfs:subClassOf*`
   property-path query.
3. Test `pg_ripple.infer('rdfs')` (discovering the real built-in rule-set
   names — `rdfs`, `owl-rl`, `owl-el`, `owl-ql`, `skos`, and others — from
   a real error message) on an isolated 3-triple example first, then on
   the full dataset; document the real, reproducible data corruption this
   version's RDFS reasoner causes, and the safe direct-query workaround.
4. Hybrid retrieval: a real Python script (`data/
   ch23_hybrid_retrieval.py`) combining Chapter 6's `pgvector` semantic
   search (finds the relevant policy document) with graph queries built
   from the verified-safe primitives (finds the precise, named list of
   real businesses that document actually affects) — two independent
   PostgreSQL instances, joined in application code.
5. Entity resolution: a real head-to-head (`data/
   ch23_entity_resolution.py`) between Chapter 5's `pg_trgm` and
   `pg-ripple`'s CLK Bloom-filter `dice_similarity`/`bloom_encode()`
   against all 12 of Chapter 5's real ground-truth duplicate pairs — a
   complete, one-sided real result, not a cherry-picked example.
6. Decision guide: a four-row table (JSONB / pgvector / recursive CTEs /
   RDF+ontologies), each with the real limitation this book actually
   found for it, tying together Chapters 1, 6, 12, 21, 22, and 23 as one
   running data-modeling spectrum.

---

### Chapter 24 — `pgColumnar`: Native Columnar Storage vs. Parquet-on-S3

**Concept:** Return to Chapter 17's real, unfinished loose end —
Exercise 6 exported `sensor_readings` to Parquet and stopped short of
querying it back through PostgreSQL, since `parquet_s3_fdw` was too
hard to build. `pgColumnar` looked like the tool to finish that: a
native columnar table access method *and* a purpose-built
`pgcolumnar_parquet` foreign data wrapper claiming exactly the
row-group pruning Chapter 17 never proved. Written and verified live
against a real `pgColumnar` 1.0-alpha3 build, first attempted directly
on the shared PostgreSQL 16 host — where a genuine `ALTER SYSTEM SET`
bug (a `GUC_LIST_QUOTE` parameter silently mis-quoted into one
double-quoted identifier) took the entire cluster down, the concrete,
lived reason this chapter follows Chapters 21-22 into an isolated
container instead. The chapter's findings split cleanly: the native
columnar table's compression (40.4x) and speed (up to ~8,700x on
metadata-only aggregates) are real and reproduce Chapter 20's
scatter-vs-sorted lesson in a new engine; the `pgcolumnar_parquet`
FDW's row-group skip — the piece that would have actually closed
Chapter 17's loop — does not fire under textbook-documented conditions,
verified on both PostgreSQL 16 and 18, and filed upstream as
[commandprompt/pgcolumnar#850](https://github.com/commandprompt/pgcolumnar/issues/850).
Retesting once that issue resolves is a standing, queued task, not
closed out by this chapter.

**Synthetic data:** No new data — a live copy of Chapter 8/17's
`sensor_readings` (9,648,001 rows as of this writing), piped directly
from the main PostgreSQL 16 cluster into an isolated PostgreSQL 18
container via `\copy`, the same migration technique Chapter 21 used.

**Exercises:**
1. Stand up `pgColumnar` in an isolated PostgreSQL 18 Docker container
   (`docker/ch24/`) — real gotchas: `postgresql-server-dev-18` is
   required and easy to miss, and `shared_preload_libraries` must be
   written into `postgresql.conf` before the first start, never as a
   live `ALTER SYSTEM SET`, per the Background section's real incident.
2. Create a native columnar table, load `sensor_readings` into it, and
   measure real storage (708 MB heap -> 18 MB columnar, 40.4x) and
   `count(*)` speed (562.7ms -> 0.065ms, metadata-only).
3. A filtered aggregate on unsorted columnar data is *slower* than the
   heap (1459.5ms vs. 486.6ms, 0 of 65 chunk groups skipped) — the same
   scatter problem Chapter 20 found for `sensor_id`, now in
   `pgColumnar`'s own zone maps. `vacuum_sorted` fixes it (370.3ms, 32
   of 43 groups skipped) at a real, measured compression cost (18MB ->
   27MB).
4. Export to Parquet with `export_parquet()`: a real, undocumented gap
   — no compression parameter at all, producing 405MB against Chapter
   17's deliberately-Snappy-compressed 16.7MB for the same table.
5. Distinguish `read_parquet()` (projection pushdown only, confirmed via
   `EXPLAIN` showing a plain `Function Scan` that materializes the
   whole file first) from the `pgcolumnar_parquet` foreign data wrapper
   (which *should* push predicates down per its own documentation).
6. The chapter's central finding: even on a column verified fully
   sorted (`pgcolumnar.sort_status`) and correctly typed
   (`id < 942801::bigint`), the FDW's `Row Groups Skipped` stays at 0 —
   confirmed identical on PostgreSQL 16 and 18, isolated with a minimal
   dataset-independent repro, and filed as a new upstream issue after
   confirming it wasn't already reported.

---

## Appendices

- **A — Environment Setup:** Four separate PostgreSQL environments, not one — Chapters 1-20 run against a single PostgreSQL 16 cluster with all required extensions pre-installed (`DOCKER-REQUIREMENTS.md` documents the full extension/config list); Chapter 21 needs an isolated PostgreSQL 19 beta2 container (`docker/ch21/`); Chapters 22-23 need an isolated PostgreSQL 18 container with `pg-ripple` built from source via Rust/`pgrx` (`docker/ch22/`); Chapter 24 needs a second, separate PostgreSQL 18 container for `pgColumnar` (`docker/ch24/`), isolated after a real incident on the main cluster, not just a precaution. This appendix should document all four explicitly, including why the later three are kept separate from the main cluster, rather than presenting a single Compose file as if one environment covered the whole book.
- **B — Synthetic Data Generation Scripts:** Documented `psql` and Python scripts for seeding each chapter's dataset.
- **C — Extension Installation Reference:** `CREATE EXTENSION` commands and version notes for each extension used.
- **D — Index Decision Guide:** A decision tree for choosing between B-tree, GIN, GiST, BRIN, and HNSW indexes.
- **E — Further Reading:** Official docs, papers, and blog posts for each topic.
- **F — Syntax Quick Reference:** A per-chapter cheatsheet of the core commands/operators/functions this book actually used — JSONB operators (Ch1), PostGIS functions (Ch2), `FOR UPDATE SKIP LOCKED` (Ch3), `tsvector`/`tsquery` (Ch4), `pg_trgm` operators (Ch5), `pgvector` distance operators (Ch6), `ip4r` operators (Ch7), partitioning DDL (Ch8), `REFRESH MATERIALIZED VIEW` forms (Ch9), PostgREST/RLS grant patterns (Ch10), window function frame syntax (Ch11), `WITH RECURSIVE`/`CYCLE` (Ch12), `LISTEN`/`NOTIFY` (Ch13), advisory lock functions (Ch14), domain/enum/composite DDL (Ch15), generated column syntax (Ch16), FDW DDL (Ch17), logical replication DDL (Ch18), `cron.schedule` forms (Ch19), `EXPLAIN`/`pg_stat_statements` queries (Ch20), `CREATE PROPERTY GRAPH`/`GRAPH_TABLE` (Ch21), and SPARQL/SHACL/`pg_ripple` function signatures (Ch22-23) — one page per chapter, meant to be flipped to rather than read start to end, and a natural place to call out which syntax this book verified working versus verified broken (Ch21's unsupported quantifiers, Ch22's rule-chaining bug, Ch23's `infer()` data-corruption warning) so a reader skimming for syntax doesn't copy something this book already found doesn't work.

---

## Conventions Used in This Book

- SQL blocks use uppercase keywords and lowercase identifiers.
- `-- ✎ exercise` marks lines the reader should write themselves.
- `-- ✔ expected` marks reference output for verification.
- Each chapter opens with a **Why this matters** paragraph connecting the technique to real engineering problems.
- Each chapter closes with a **Going further** section pointing to production considerations not covered in the exercises.
- All code is written in **Python 3.12**.
- Installation instructions target **Debian-based Linux** (`apt` / `apt-get`).
