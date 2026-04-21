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

## Appendices

- **A — Environment Setup:** Docker Compose file spinning up PostgreSQL 16 with all required extensions pre-installed.
- **B — Synthetic Data Generation Scripts:** Documented `psql` and Python scripts for seeding each chapter's dataset.
- **C — Extension Installation Reference:** `CREATE EXTENSION` commands and version notes for each extension used.
- **D — Index Decision Guide:** A decision tree for choosing between B-tree, GIN, GiST, BRIN, and HNSW indexes.
- **E — Further Reading:** Official docs, papers, and blog posts for each topic.

---

## Conventions Used in This Book

- SQL blocks use uppercase keywords and lowercase identifiers.
- `-- ✎ exercise` marks lines the reader should write themselves.
- `-- ✔ expected` marks reference output for verification.
- Each chapter opens with a **Why this matters** paragraph connecting the technique to real engineering problems.
- Each chapter closes with a **Going further** section pointing to production considerations not covered in the exercises.
- All code is written in **Python 3.12**.
- Installation instructions target **Debian-based Linux** (`apt` / `apt-get`).
