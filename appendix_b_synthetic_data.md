# Appendix B — Synthetic Data Generation Scripts

Every chapter in this book follows the same rule: real, synthetic-but-
realistic data first, exercises against it second — nothing in the
exercises is invented on the spot or asserted without a live query
behind it. This appendix indexes every script that builds that data,
in `data/`, run against `dbname=portsmith` unless noted otherwise.

## Seed scripts (build a chapter's tables from scratch)

| Script | Chapter | Builds |
|---|---|---|
| `ch01_seed.py` | 1 — JSONB | `businesses`, with a heterogeneous `details` JSONB column varying by category |
| `ch02_seed.py` | 2 — PostGIS | `neighborhoods`, `city_infrastructure`, `parks`, and business point geometry |
| `ch03_seed.py` | 3 — Job Queues | `jobs`, synthetic permit-application work items |
| `ch04_seed.py` | 4 — Full-Text Search | `city_documents` (council minutes, zoning ordinances, public notices) |
| `ch05_seed.py` | 5 — Fuzzy Matching | `residents` (with 12 real seeded typo/duplicate pairs — see below) and `business_names` |
| `ch06_seed.py` | 6 — pgvector | `city_photos` and synthetic embedding scaffolding |
| `ch07_seed.py` | 7 — IP/Network | `network_events`, `blocklists` |
| `ch08_seed.py` | 8 — Partitioning & BRIN | `sensor_readings`, partitioned IoT data, ~9.6M rows |
| `ch11_seed.py` | 11 — Window Functions | `business_revenue` (48 businesses × 4 quarters) |
| `ch12_seed.py` | 12 — Recursive CTEs | `city_org` (invented org chart), `intersections`/`road_segments` (derived from Chapter 2's real geometry via `ST_Intersects`), `categories` (derived from Chapter 1's real category values) |

Chapters 9, 10, 13–20 deliberately seed nothing new — each reuses
tables earlier chapters already built, per the book's running
principle of building on real prior state rather than starting fresh
every chapter.

## Data-processing and demo scripts (not seeding — used within exercises)

| Script | Chapter | Purpose |
|---|---|---|
| `ch03_worker.py` | 3 | Simulates a concurrent job-queue worker claiming rows with `FOR UPDATE SKIP LOCKED` |
| `ch03_reclaim.py` | 3 | Reclaims stalled jobs past a timeout — later ported to SQL as Chapter 19's `sweep_stalled_jobs()` |
| `ch06_embed_documents.py` | 6 | Computes real `sentence-transformers` embeddings for `city_documents` |
| `ch06_semantic_search.py` | 6 | Semantic and hybrid (semantic + keyword) search over embedded documents |
| `ch06_rag_ingest.py` / `ch06_rag_chat.py` | 6 (bonus) | A small local RAG pipeline — chunk/embed/retrieve, then generate via Ollama |
| `ch13_listen.py` | 13 | A `psycopg` `LISTEN` client used across the `LISTEN`/`NOTIFY` exercises |
| `ch14_leader_election.py` | 14 | Multiprocessing leader-election race over `pg_try_advisory_lock` |
| `ch17_export_to_parquet.py` | 17 | Exports `sensor_readings` to Parquet in MinIO, partitioned by month |
| `ch17_query_parquet.py` | 17 | Verifies the Parquet export independently via DuckDB, no PostgreSQL involved |
| `ch17_census.csv` | 17 | Real CSV used for the `file_fdw` exercise |
| `ch18_replication_stream.py` | 18 | Consumes the logical replication stream directly via `psycopg`'s low-level `pgconn` API |
| `ch22_export_turtle.py` | 22 | Exports `businesses`/`neighborhoods` (plus real `ST_Touches`-derived adjacency) as Turtle triples |
| `ch23_export_ontology.py` | 23 | Exports Chapter 12's `categories` tree as an `rdfs:subClassOf` class hierarchy |
| `ch23_hybrid_retrieval.py` | 23 | Combines Chapter 6's `pgvector` search with the Chapter 22/23 graph — two databases, joined in Python |
| `ch23_entity_resolution.py` | 23 | Head-to-head: `pg_trgm` vs. `pg-ripple`'s `dice_similarity()` against real ground-truth duplicates |

## Worth knowing before you run any of these

- **Run seed scripts in chapter order.** Several later chapters'
  scripts assume earlier chapters' tables already exist (Chapter 12's
  road graph reads Chapter 2's real geometry live; Chapter 22's export
  reads Chapter 1/2's live, possibly-mutated data).
- **The live database reflects cumulative mutation, not just seed
  output.** Chapter 1 Exercise 5 bumps a rating via `jsonb_set`;
  Chapter 15 converts `jobs.status` from `TEXT` to an enum in place.
  Querying the seed script alone won't show you the database's actual
  current state — query the database.
- **Always set `SET timezone = 'UTC';`** before any verification query
  touching a timestamp column. This environment's default session
  timezone is not UTC, and several chapters (8, 9, 11) bucket rows by
  day on `TIMESTAMPTZ` columns — a non-UTC session silently groups a
  different set of rows per bucket.
- **Chapter 22/23 scripts connect to two different PostgreSQL
  instances** (the main cluster and the Chapter 22 container) — check
  the DSN each script uses before assuming "the database" means the
  same thing every time in this book.
