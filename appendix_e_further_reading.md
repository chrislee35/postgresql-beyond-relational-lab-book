# Appendix E — Further Reading

Official documentation and project sources for every chapter — not
blog posts or opinion, deliberately. Each chapter's own exercises are
the place for "how it actually behaves"; these are the primary sources
for the parts a single lab exercise can't cover.

| Chapter | Topic | Source |
|---|---|---|
| 1 | JSONB | [postgresql.org/docs/current/datatype-json.html](https://www.postgresql.org/docs/current/datatype-json.html) |
| 2 | PostGIS | [postgis.net/documentation](https://postgis.net/documentation/) |
| 3 | `FOR UPDATE`/`SKIP LOCKED` | [postgresql.org/docs/current/sql-select.html](https://www.postgresql.org/docs/current/sql-select.html) — locking clause section |
| 4 | Full-text search | [postgresql.org/docs/current/textsearch.html](https://www.postgresql.org/docs/current/textsearch.html) |
| 5 | `pg_trgm` | [postgresql.org/docs/current/pgtrgm.html](https://www.postgresql.org/docs/current/pgtrgm.html) |
| 6 | pgvector | [github.com/pgvector/pgvector](https://github.com/pgvector/pgvector) |
| 6 (bonus) | Sentence embeddings / Ollama | [sbert.net](https://www.sbert.net/), [ollama.com](https://ollama.com/) |
| 7 | `ip4r` | [github.com/RhodiumToad/ip4r](https://github.com/RhodiumToad/ip4r) |
| 8 | Partitioning | [postgresql.org/docs/current/ddl-partitioning.html](https://www.postgresql.org/docs/current/ddl-partitioning.html) |
| 8 | BRIN indexes | [postgresql.org/docs/current/brin-intro.html](https://www.postgresql.org/docs/current/brin-intro.html) |
| 9 | Materialized views | [postgresql.org/docs/current/rules-materializedviews.html](https://www.postgresql.org/docs/current/rules-materializedviews.html) |
| 10 | PostgREST | [postgrest.org](https://postgrest.org/) |
| 11 | Window functions | [postgresql.org/docs/current/tutorial-window.html](https://www.postgresql.org/docs/current/tutorial-window.html) |
| 12 | Recursive CTEs | [postgresql.org/docs/current/queries-with.html](https://www.postgresql.org/docs/current/queries-with.html) |
| 13 | `LISTEN`/`NOTIFY` | [postgresql.org/docs/current/sql-notify.html](https://www.postgresql.org/docs/current/sql-notify.html) |
| 14 | Advisory locks | [postgresql.org/docs/current/explicit-locking.html](https://www.postgresql.org/docs/current/explicit-locking.html) — advisory locks section |
| 15 | Types, domains, enums | [postgresql.org/docs/current/sql-createtype.html](https://www.postgresql.org/docs/current/sql-createtype.html), [sql-createdomain.html](https://www.postgresql.org/docs/current/sql-createdomain.html) |
| 16 | Generated columns | [postgresql.org/docs/current/ddl-generated-columns.html](https://www.postgresql.org/docs/current/ddl-generated-columns.html) |
| 17 | `postgres_fdw` / `file_fdw` | [postgresql.org/docs/current/postgres-fdw.html](https://www.postgresql.org/docs/current/postgres-fdw.html), [file-fdw.html](https://www.postgresql.org/docs/current/file-fdw.html) |
| 17 | DuckDB (independent Parquet verification) | [duckdb.org](https://duckdb.org/) |
| 17 | MinIO | [min.io](https://min.io/) |
| 18 | Logical replication | [postgresql.org/docs/current/logical-replication.html](https://www.postgresql.org/docs/current/logical-replication.html) |
| 19 | `pg_cron` | [github.com/citusdata/pg_cron](https://github.com/citusdata/pg_cron) |
| 20 | `pg_stat_statements` | [postgresql.org/docs/current/pgstatstatements.html](https://www.postgresql.org/docs/current/pgstatstatements.html) |
| 20 | `auto_explain` | [postgresql.org/docs/current/auto-explain.html](https://www.postgresql.org/docs/current/auto-explain.html) |
| 21 | `CREATE PROPERTY GRAPH` / SQL/PGQ | [postgresql.org/docs/current/sql-create-property-graph.html](https://www.postgresql.org/docs/current/sql-create-property-graph.html) — check the version-specific docs, not just "current," since this feature is new as of PostgreSQL 19 |
| 22 | `pg-ripple` | [github.com/trickle-labs/pg-ripple](https://github.com/trickle-labs/pg-ripple) |
| 22 | SPARQL 1.1 | [w3.org/TR/sparql11-query](https://www.w3.org/TR/sparql11-query/) |
| 22 | Turtle (RDF syntax) | [w3.org/TR/turtle](https://www.w3.org/TR/turtle/) |
| 22 | SHACL | [w3.org/TR/shacl](https://www.w3.org/TR/shacl/) |
| 23 | RDF Schema (RDFS) | [w3.org/TR/rdf-schema](https://www.w3.org/TR/rdf-schema/) |
| 23 | OWL 2 Web Ontology Language | [w3.org/TR/owl2-overview](https://www.w3.org/TR/owl2-overview/) |
| 24 | `pgColumnar` | [github.com/commandprompt/pgcolumnar](https://github.com/commandprompt/pgcolumnar) |
| 24 | Apache Parquet format | [parquet.apache.org/docs](https://parquet.apache.org/docs/) |

## A note on reading these versus running the exercises

This book's own recurring finding, most sharply in Chapters 21–23:
official documentation and a specification describe what a feature is
*meant* to do, not necessarily what a specific version actually does
today. PostgreSQL 19's own SQL/PGQ documentation describes quantified
path patterns as part of the feature; PostgreSQL 19 beta2 itself
rejects them. `pg-ripple`'s README describes working RDFS reasoning
and CLK Bloom-filter record linkage; this book's own testing found the
former corrupts data and the latter misses real duplicates at default
settings. None of that is a reason to skip the documentation — it's
the reason every exercise in this book is written to run something
real and check the actual output against it, rather than trust either
source alone.
