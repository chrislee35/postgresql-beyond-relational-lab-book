# The Portsmith Papers

### A Hands-On Tour of PostgreSQL Beyond the Relational Model

Most PostgreSQL tutorials stop at `SELECT`, `JOIN`, and `GROUP BY`. This lab
book starts where they end.

Each chapter tackles a real engineering problem faced by the fictional city of
**Portsmith** — a shared dataset that grows across all twenty chapters. You
will store heterogeneous documents in JSONB, query geospatial data with
PostGIS, build a job queue with no message broker, run semantic search with
vector embeddings, expose a REST API with zero application code, and more.
Every chapter generates its own synthetic data and then walks you through a
set of hands-on exercises. The exercises are meant to be done, not just read.

---

## What You Will Need

- PostgreSQL 16 on a Debian-based Linux system
- Python 3.12
- Basic SQL familiarity (`SELECT`, `INSERT`, `JOIN`, `GROUP BY`)

Setup instructions are in [Appendix A](00_guide.md#appendix-a) of the guide,
or at the top of each chapter's **Installation** section.

---

## Start Here

→ **[00_guide.md](00_guide.md)** — chapter map, exercise outline, and
conventions used throughout the book.

---

## Chapter Index

| # | Chapter | Key technique |
|---|---------|---------------|
| 1 | [JSONB: Semi-Structured Data Without a Schema Tax](ch01_jsonb.md) | `->`, `@>`, GIN indexes, `jsonb_path_query` |
| 2 | PostGIS: Geospatial Queries on Real Geometry | `ST_DWithin`, `ST_Within`, GIST indexes |
| 3 | Job Queues: `FOR UPDATE SKIP LOCKED` | Atomic claim, dead-letter, `pgbench` |
| 4 | Full-Text Search: `tsvector`, Stopwords, and Ranking | `to_tsvector`, `ts_rank`, custom configs |
| 5 | Fuzzy Matching: `pg_trgm` | `similarity()`, trigram GIN index |
| 6 | Vector Search: `pgvector` for Embeddings | IVFFlat, HNSW, hybrid search |
| 7 | IP and Network Filtering: `ip4r` | CIDR containment, blocklist lookups |
| 8 | Declarative Partitioning and BRIN Indexes | Range partitions, partition pruning |
| 9 | [Materialized Views](ch09_materialized_views.md) | Concurrent refresh, chained rollups |
| 10 | [PostgREST: A Web-Native REST API](ch10_postgrest.md) | RLS, RPC endpoints, role-based access |
| 11 | [Window Functions: Analytics Beyond `GROUP BY`](ch11_window_functions.md) | `RANK`, `LAG`, rolling averages, gaps & islands |
| 12 | [Recursive CTEs: Graphs and Hierarchies](ch12_recursive_ctes.md) | Tree traversal, shortest path, cycle detection |
| 13 | `LISTEN` / `NOTIFY`: Database-Native Pub/Sub | Triggers, `pg_notify`, async Python clients |
| 14 | Advisory Locks: Distributed Coordination | Leader election, session vs. transaction locks |
| 15 | Custom Types, Domains, and Enums | Schema-level business rules |
| 16 | Generated Columns | Derived values without triggers |
| 17 | Foreign Data Wrappers: PostgreSQL as a Data Hub | `postgres_fdw`, `file_fdw` |
| 18 | Logical Replication and Change Data Capture | Publications, subscriptions, Debezium |
| 19 | `pg_cron`: Scheduled Jobs Inside PostgreSQL | Idempotency, overlap prevention |
| 20 | `pg_stat_statements` and Query Performance | `EXPLAIN ANALYZE`, slow query diagnosis |

Chapters 2–20 are in progress. See [00_guide.md](00_guide.md) for the full
exercise outline of each upcoming chapter.

---

## Repository Layout

```
book/
├── README.md           — this file
├── LICENSE.md          — CC BY-NC-SA 4.0 + AI training restriction
├── 00_guide.md         — chapter map and conventions
├── cover.md            — book cover page
├── cover.svg           — cover illustration (concept art)
├── ch01_jsonb.md       — Chapter 1
├── data/
│   └── ch01_seed.py    — seed script for Chapter 1
└── ...                 — further chapters added iteratively
```

---

## Contributing

Contributions are welcome and encouraged. The most useful things you can do:

- **Run the exercises** and report anything that does not work as described —
  wrong query output, a step that fails on a stock Debian install, a typo, or
  an explanation that left you more confused than when you started.
- **Improve an explanation** — if a concept clicked for you only after reading
  something outside the book, a pull request adding that context is valuable.
- **Add an exercise variation** — each chapter closes with a *Going further*
  note; concrete extra exercises there are always welcome.

### How to contribute

1. Fork the repository.
2. Create a branch named for your change: `fix/ch01-gin-index-note` or
   `improve/ch03-dead-letter-explanation`.
3. Make your changes. Keep commits focused — one logical change per commit.
4. Open a merge request against `main` with a short description of what you
   changed and why.

Please do not open merge requests that:

- Add entirely new chapters (discuss in an issue first so we can coordinate
  with the chapter roadmap).
- Rewrite large sections of existing prose without a corresponding issue.
- Change the seed data in a way that breaks expected query outputs in the
  exercises.

All contributions are made under the same
[CC BY-NC-SA 4.0 + no-AI-training](LICENSE.md) license as the rest of the
book. By opening a merge request you agree that your contribution may be
included under those terms.

---

## License

This work is licensed under
[Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International](LICENSE.md)
with an additional restriction prohibiting use for AI or machine learning
training. See [LICENSE.md](LICENSE.md) for the full terms.

Copyright © 2026 Chris Lee.
