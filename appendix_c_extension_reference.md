# Appendix C — Extension Installation Reference

Every `CREATE EXTENSION` this book actually ran, in one place. Package
names follow the PGDG `postgresql-<version>-<name>` convention; adjust
the version number for whichever cluster you're installing into (see
Appendix A for which chapters use which of the three).

## Main cluster (PostgreSQL 16, Chapters 1–20)

| Chapter | Extension | `apt` package | `CREATE EXTENSION` | Notes |
|---|---|---|---|---|
| 2 | PostGIS | `postgresql-16-postgis-3` | `postgis` | Needs superuser |
| 5 | `pg_trgm` | bundled (core/contrib) | `pg_trgm` | No separate package |
| 6 | pgvector | `postgresql-16-pgvector` | `vector` | Needs superuser |
| 7 | `ip4r` | `postgresql-16-ip4r` | `ip4r` | Needs superuser |
| 17 | `postgres_fdw` | bundled (core/contrib) | `postgres_fdw` | Needs superuser; `USAGE` grant needed for non-superuser roles |
| 17 | `file_fdw` | bundled (core/contrib) | `file_fdw` | Needs superuser; reading needs `pg_read_server_files` membership too |
| 17 (Ex6, sketch only) | `parquet_s3_fdw` | build from source | `parquet_s3_fdw` | Built against Apache Arrow C++; never actually run in this book — see Chapter 17's own honest account of why |
| 19 | `pg_cron` | `postgresql-16-cron` | `pg_cron` | Needs `shared_preload_libraries`; schema `cron` owned by `postgres` |
| 19/20 | `pg_stat_statements` | bundled (core/contrib) | `pg_stat_statements` | Needs `shared_preload_libraries`; `pg_stat_statements_reset()` revoked from `PUBLIC` by default |
| 19/20 | `auto_explain` | bundled (core/contrib) | *(none — loaded via config, not `CREATE EXTENSION`)* | `shared_preload_libraries` only; GUCs are superuser-only (`PGC_SUSET`) |

Required `postgresql.conf` settings, all needing a full restart, not
just a reload — set once, in Chapter 19, and left in place for the
rest of the book:

```conf
shared_preload_libraries = 'pg_cron,pg_stat_statements,auto_explain'
wal_level = logical
cron.database_name = 'portsmith'
```

## PostgreSQL 19 beta2 container (Chapter 21)

No extensions — `CREATE PROPERTY GRAPH`/`GRAPH_TABLE` (SQL/PGQ) are
core PostgreSQL 19 features, not an installable extension. The only
package needed beyond the server itself is PostGIS, and even that
turned out unnecessary — Chapter 21 sidesteps it by exporting
`intersections.geom` as plain `lon`/`lat` columns rather than pulling
PostGIS into a still-beta major version.

## PostgreSQL 18 / `pg-ripple` container (Chapters 22–23)

| Extension | Install | `CREATE EXTENSION` | Notes |
|---|---|---|---|
| `pg_ripple` | build from source (Rust + `pgrx 0.18.0` exactly, against PostgreSQL 18 server headers) | `pg_ripple` | See Appendix A for the exact version-pinning trap; needs `shared_preload_libraries = 'pg_ripple'` from first start for its background merge worker |

## A note on `GRANT`s, not just `CREATE EXTENSION`

Installing an extension is frequently the *easy* privilege gate in
this book, not the only one. Real walls hit and documented,
chapter by chapter, on the main cluster:

- `CREATE EXTENSION` itself always needs superuser.
- `postgres_fdw`/`file_fdw` need `GRANT USAGE ON FOREIGN DATA WRAPPER`
  to a non-superuser role separately from installing the extension.
- `file_fdw` additionally needs `pg_read_server_files` role membership
  — and even then, PostgreSQL reads server-side as the `postgres` OS
  user, so file permissions on disk matter independently of the SQL
  grant (Chapter 17's sharpest gotcha: a file under a `700` home
  directory was unreadable regardless of the file's own mode).
- `pg_cron`'s schema (`cron`) and `pg_stat_statements`'
  reset/reload functions are all revoked from `PUBLIC` by default —
  `GRANT EXECUTE`/`GRANT USAGE` explicitly, per database (both are
  per-database extensions, easy to grant into the wrong one by
  accident).
- `pg_cron` jobs run as the job-owning role, authenticated over a
  **fresh libpq connection** opened by the `postgres` OS user — a real,
  non-obvious consequence: that OS user needs its own `~postgres/
  .pgpass` entry for the job-owning role's password, or every
  scheduled job fails with `connection failed` and no corresponding
  entry in the server log.
- Chapter 24's `pgColumnar` needs its own `USAGE` grants beyond
  installing the extension, twice: `GRANT USAGE ON SCHEMA pgcolumnar` +
  `GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA pgcolumnar` before a
  non-superuser role can call any `pgcolumnar.*` maintenance function
  (creating and querying a table `USING pgcolumnar` needs neither), and
  a second, separate `GRANT USAGE ON FOREIGN DATA WRAPPER
  pgcolumnar_parquet` before that role can `CREATE SERVER` against it —
  the same shape of gate Chapter 17 already documented for
  `postgres_fdw`/`file_fdw`.

None of this is unique to this book's exact setup — it's the general
shape of PostgreSQL's privilege model, and the book's own experience
is that each of these gates was found by testing, one at a time, not
by reading the whole list in advance. Expect the same if you're
installing on a fresh cluster of your own.
