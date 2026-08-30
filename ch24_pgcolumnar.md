# Chapter 24 — `pgColumnar`: Native Columnar Storage vs. Parquet-on-S3

> *A foreign data wrapper reaches out to a file that lives somewhere
> else, every time it's asked. A table access method never leaves —
> the columns just live in a different shape once they're inside.*

---

## Background

Chapter 17 ended with a real, honest loose end. Exercise 6 exported
`sensor_readings` to Parquet on MinIO — a genuinely measured 46x size
reduction, 772 MB down to 16.7 MB — and then stopped short of the last
piece: actually querying that Parquet data back *through PostgreSQL*,
via `parquet_s3_fdw`. The extension was real, but hard enough to build
from source that the chapter left it as "the pattern, discussed, not
run" and moved on. That gap sat there through twenty-three more
chapters.

**`pgColumnar`** looked, on paper, like the tool to finally close it —
and like something genuinely new besides. It's not one thing but two,
bundled into a single MIT-licensed extension: a **native table access
method** (`CREATE TABLE t (...) USING pgcolumnar`, columns actually
stored column-wise inside PostgreSQL's own WAL-logged storage, no
external file at all) and, separately, a **Parquet-reading layer** —
`read_parquet()`, and a purpose-built `pgcolumnar_parquet` foreign data
wrapper — that promises exactly what Chapter 17 never got to prove:
row-group-level pruning of an external Parquet file, driven by the
query's own `WHERE` clause, with `EXPLAIN` showing the skip happening.

Getting there took a real detour first, worth knowing before you
follow this chapter's own steps. The first attempt installed
`pgColumnar` directly on the shared PostgreSQL 16 host every earlier
chapter runs against — reasonable, since (unlike Chapters 21–23)
nothing about `pgColumnar` requires beta software or a from-source Rust
build; PG15 through 18 are all in its tested matrix. Appending it to
`shared_preload_libraries` via `ALTER SYSTEM SET` looked routine — the
exact pattern Chapters 19–20 already used for `pg_cron` and
`pg_stat_statements`. It wasn't: `ALTER SYSTEM` silently wrote

```
shared_preload_libraries = '"pg_cron,pg_stat_statements,auto_explain,pgcolumnar"'
```

into `postgresql.auto.conf` — note the stray inner `"..."` wrapping the
*entire* comma-joined value as one double-quoted identifier, rather
than quoting each library name separately. On restart, PostgreSQL tried
to `dlopen` a single library literally named
`pg_cron,pg_stat_statements,auto_explain,pgcolumnar`, commas and all,
and refused to start — taking down every database this book depends on,
mid-book, for about twenty minutes while the actual `postgresql.auto.conf`
(which, on Debian, lives in the *data* directory, not `/etc/postgresql/`
— the same split Chapter 21 already documented) got tracked down and
hand-edited back to a plain, correctly single-quoted list. Real, cited
verbatim, not reconstructed: this is a genuine `ALTER SYSTEM` pitfall
for `GUC_LIST_QUOTE` parameters like `shared_preload_libraries`, not a
typo either of us made.

That's the real reason this chapter follows Chapters 21–22's pattern
and runs `pgColumnar` in an isolated container instead of the main
cluster, even though nothing here is beta software — Chapters 21–22
isolated *because* of beta/build risk they could only reason about in
advance; this chapter isolates because of a production outage that
already happened once, on this exact extension, on this exact book's
infrastructure. See `docker/ch24/` and this chapter's own Environment
Setup section.

---

## The Scenario

| Object                          | Lives in                          | Purpose                                                         |
|----------------------------------|--------------------------------------|---------------------------------------------------------------------|
| `sensor_readings_columnar`         | `portsmith24` (PG18 container)       | Columnar copy of Chapter 8/17's `sensor_readings` — same table, same 9.6M+ rows, migrated across live |
| `/tmp/sensor_readings_sorted.parquet` | Container filesystem              | Native `export_parquet()` output — the same data Chapter 17 exported by hand with pyarrow |
| `sensor_readings_pq`                | `portsmith24`, via `pgcolumnar_parquet` | Foreign table over that Parquet file — the piece Chapter 17 Exercise 6.3 never finished |
| `skip_repro` / `skip_repro_pq`       | `portsmith24`                        | A minimal, dataset-independent 1M-row table built specifically to file a clean upstream bug report |

`sensor_readings` itself never moves — it stays exactly where Chapter 8
built it, on the main PostgreSQL 16 cluster. Everything in this chapter
is a live copy, migrated across with a plain `\copy` pipe, the same
technique Chapter 21 used to get Chapter 12's data into its own
isolated container.

---

## Exercise Goals

By the end of this chapter you will be able to:

- Stand up `pgColumnar` in an isolated PostgreSQL 18 container, and
  understand — from a real incident, not a hypothetical — why a young
  extension's `shared_preload_libraries` setting belongs in
  `postgresql.conf` before the first start, not in a live `ALTER
  SYSTEM SET`.
- Create a native columnar table, load real data into it, and measure
  what changes: storage size, and the shape of query speed, against
  the exact same table as a heap.
- Reproduce Chapter 20's central lesson in a new setting: an unsorted
  columnar table's chunk-group skip can lose to a plain heap scan, and
  sorting fixes it — at a real, measured cost to compression.
- Export a columnar table to Parquet and know precisely what that
  export does and doesn't preserve, compared to Chapter 17's hand-built
  pyarrow pipeline.
- Tell apart two different claims about reading external Parquet from
  inside PostgreSQL — "decodes only the columns you ask for" versus
  "skips whole row groups your `WHERE` clause rules out" — and verify,
  with `EXPLAIN`, which one is actually true for which code path.
- Build a minimal, reproducible failing case for a real finding, and
  understand what it took to confirm it wasn't a fluke of this book's
  own environment (retested clean on a second PostgreSQL major) before
  reporting it upstream.

---

## Environment Setup — A Fourth Container

`docker/ch24/` — the same three-file shape as Chapters 21 and 22's
containers (`Dockerfile`, `entrypoint.sh`, `docker-compose.yml`), built
on **PostgreSQL 18** (GA — `pgColumnar`'s own docs list 15 through 18 as
tested, 19 only validated against beta, so 18 is the newest fully
covered major, and the version this chapter's central finding was
double-checked against after first surfacing on the host's PG16).

```bash
cd docker/ch24
docker compose up --build
```

Listens on host port **5435** (5432 = main cluster, 5433 = Chapter 21,
5434 = Chapters 22–23). Two real things worth knowing, both already
folded into the Dockerfile:

**1. `postgresql-server-dev-18` is not optional, and it's easy to miss.**
`pgColumnar` builds via PGXS against an installed server's headers —
`make PG_CONFIG=/path/to/pg_config` fails immediately with `fatal
error: postgres.h: No such file or directory` without them. The plain
`postgresql-18` package doesn't include them; the first attempt at this
(on the host, before this container existed) hit exactly that error.

```dockerfile
RUN apt-get install -y --no-install-recommends \
    postgresql-18 postgresql-client-18 postgresql-server-dev-18
```

**2. `shared_preload_libraries` goes into `postgresql.conf` before the
first `pg_ctl start` — never as a live `ALTER SYSTEM SET` against a
running server.** This is the Background section's incident, turned
into a concrete rule: `entrypoint.sh` writes the setting directly into
the fresh cluster's config file, before the cluster has ever accepted a
connection, so there's no live GUC-list serialization step to get
wrong in the first place.

```bash
# entrypoint.sh, before the first pg_ctl start
echo "shared_preload_libraries = 'pgcolumnar'" >> "$PGDATA/postgresql.conf"
```

```
$ psql -h localhost -p 5435 -U chris -d portsmith24 -c "SELECT version();"
 PostgreSQL 18.6 (Debian 18.6-1.pgdg12+2) on x86_64-pc-linux-gnu, compiled by gcc (Debian 12.2.0-14+deb12u1) 12.2.0, 64-bit

$ psql -h localhost -p 5435 -U chris -d portsmith24 -c "SELECT extname, extversion FROM pg_extension WHERE extname='pgcolumnar';"
  extname   | extversion
------------+------------
 pgcolumnar | 1.0-alpha3
```

**Getting `sensor_readings` across.** No PostGIS, no generated columns
to worry about here — unlike Chapter 21's `intersections`, this table
travels as-is:

```bash
psql portsmith -t -A -c "\copy (SELECT id, sensor_id, sensor_type, reading_value, recorded_at FROM sensor_readings) TO STDOUT CSV" | \
  psql -h localhost -p 5435 -U chris -d portsmith24 -c "\copy sensor_readings_columnar FROM STDIN CSV"
```

```
COPY 9648001
```

A live pipe, host to container, no intermediate file — 9,648,001 rows
in about 12 seconds.

---

## Exercises

---

### Exercise 1 — Native Storage: What Changes

`sensor_readings_columnar` mirrors `sensor_readings` exactly, minus the
PostGIS-free table's one generated column (`reading_date`, which
`pgColumnar` doesn't need any more than a heap copy would):

```sql
CREATE TABLE sensor_readings_columnar (
    id             bigint,
    sensor_id      int,
    sensor_type    text,
    reading_value  double precision,
    recorded_at    timestamptz
) USING pgcolumnar;
```

No extra grant needed to create or use it — `USING pgcolumnar` is
available to any role the moment the extension exists, the same as
`USING heap` would be. (The `pgcolumnar.*` *maintenance* functions used
later in this chapter are a separate story — Exercise 3.)

**1.1 — Storage, real numbers**

```sql
SELECT pg_size_pretty(sum(pg_relation_size(inhrelid))) AS heap_table_only
FROM pg_inherits WHERE inhparent = 'sensor_readings'::regclass;
-- 708 MB   (742,481,920 bytes, table only, no indexes)

SELECT pg_size_pretty(pg_total_relation_size('sensor_readings_columnar'));
-- 18 MB    (18,374,656 bytes)
```

**708 MB down to 18 MB — a real, measured 40.4x**, on the exact table
Chapter 17 got 46x on with hand-picked Snappy Parquet. Different
mechanism, same order of magnitude, both real.

**1.2 — `count(*)`: the case metadata alone answers**

```sql
EXPLAIN (ANALYZE) SELECT count(*) FROM sensor_readings;         -- heap
-- Execution Time: 562.731 ms   (parallel seq scan across 12 partitions)

EXPLAIN (ANALYZE) SELECT count(*) FROM sensor_readings_columnar; -- columnar
```

```
 Custom Scan (PgColumnarScan)  (actual time=0.019..0.019 rows=1 loops=1)
   Columnar Vectorized Aggregates: 1
   Columnar Pushed-Down Filters: 0
 Execution Time: 0.065 ms
```

**562.7 ms down to 0.065 ms — roughly 8,700x.** Not decoding, not
scanning — `count(*)` with no filter is answered entirely from each
chunk group's own row-count metadata, the same reason Chapter 9's
materialized views win: the answer was already sitting there, computed
once, not recomputed per query.

---

### Exercise 2 — The Filtered Case: A Real Echo of Chapter 20

`count(*)` with no `WHERE` is the easy case. What happens with a real
filter is where this chapter's most useful lesson lives — and it isn't
"columnar is faster."

**2.1 — Slower, at first**

```sql
EXPLAIN (ANALYZE, BUFFERS) SELECT count(*), avg(reading_value)
FROM sensor_readings WHERE sensor_type = 'temperature';        -- heap
-- Execution Time: 486.6 ms

EXPLAIN (ANALYZE, BUFFERS) SELECT count(*), avg(reading_value)
FROM sensor_readings_columnar WHERE sensor_type = 'temperature'; -- columnar
```

```
 ->  Custom Scan (PgColumnarScan) on sensor_readings_columnar
       Filter: (sensor_type = 'temperature'::text)
       Columnar Chunk Groups Total: 65
       Columnar Chunk Groups Removed by Filter: 0
       Columnar Vectors Decoded: 965
 Execution Time: 1459.5 ms
```

**The columnar table is slower — 1459.5 ms against the heap's 486.6
ms.** Zero of 65 chunk groups got skipped. This is Chapter 20's
`sensor_id`-scatter finding again, in a new engine: `sensor_type` is
interleaved evenly through every chunk (confirmed directly — all 120
distinct `sensor_id` values already show up within the *first*
row-group-sized slice of rows), so every chunk group's min/max span the
same full range as every other one, and there's nothing for a zone map
to rule out.

**2.2 — Sorting fixes it, and costs something real**

```sql
SELECT pgcolumnar.vacuum_sorted('sensor_readings_columnar', 'sensor_type');
```

```sql
EXPLAIN (ANALYZE, BUFFERS) SELECT count(*), avg(reading_value)
FROM sensor_readings_columnar WHERE sensor_type = 'temperature';
```

```
 ->  Parallel Custom Scan (PgColumnarScan) on sensor_readings_columnar
       Columnar Chunk Groups Total: 43
       Columnar Chunk Groups Read: 11
       Columnar Chunk Groups Removed by Filter: 32
 Execution Time: 370.3 ms
```

**370.3 ms — now genuinely faster than the heap's 486.6 ms**, 32 of 43
groups pruned. But check storage again:

```sql
SELECT pg_size_pretty(pg_total_relation_size('sensor_readings_columnar'));
-- 27 MB   (up from 18 MB — ratio drops from 40.4x to 27.5x)
```

Sorting by `sensor_type` scrambled the time-ordering that made
`recorded_at` compress so well in the first place — every column shares
the same physical row order in a columnar table, so optimizing one
column's skip quality can cost another column's compression. **This
isn't a `pgColumnar` quirk — it's the same tradeoff Chapter 16's
generated columns and Chapter 20's index choice both already made you
confront: the "obvious" fix has a real cost, and the only way to know
if it's worth paying is to measure both sides.**

<img src="imgs/ch24_pgcolumnar_findings.svg" alt="Two-column contrast: verified working — native columnar table achieves 40.4x compression, sub-millisecond metadata-only count, and real chunk-group skip after vacuum_sorted (32 of 43 groups pruned); verified broken or missing — export_parquet has no compression option and produces a much larger file than Chapter 17's hand-tuned Snappy export, read_parquet only does projection pushdown despite documentation suggesting predicate pushdown, and the pgcolumnar_parquet foreign data wrapper's row-group skip stays at zero even on fully sorted, correctly-typed data, filed upstream as issue 850"/>

---

### Exercise 3 — Exporting to Parquet: What's Actually Different From Chapter 17

```sql
SELECT pgcolumnar.export_parquet('sensor_readings_columnar', '/tmp/sensor_readings.parquet');
-- 9648001
```

```bash
$ ls -la /tmp/sensor_readings.parquet
-rw------- 1 postgres postgres 405515796 sensor_readings.parquet
```

**405 MB.** Chapter 17's pyarrow script, exporting the same table,
explicitly requesting Snappy compression, produced **16.7 MB**. The
reason is in `pgcolumnar.export_parquet(rel, path)`'s own signature:
**there's no compression argument at all** — unlike `import_parquet`,
which reads Snappy/GZIP/ZSTD/LZ4_RAW pages, the export path writes
Parquet with no codec option, full stop. The size checks out arithmetically
too: roughly 9.6M rows × ~38 raw bytes/row lands right around 365–405
MB — this looks like genuinely uncompressed output, not a bug so much
as a real, undocumented asymmetry between what `pgColumnar` can *read*
and what it can *write*.

One more real, quiet difference, worth knowing if you round-trip
timestamps: `parquet_schema()` reports `recorded_at` — a `timestamptz`
in Postgres — as `timestamp without time zone` in the exported file.
Parquet has no exact equivalent of PostgreSQL's session-relative
`timestamptz`; the export just drops the distinction. Same running
timezone-gotcha thread as Chapters 8, 9, 11, and 16 — one more format
boundary where it quietly matters.

---

### Exercise 4 — Reading Parquet Back: Two Different Claims

`pgColumnar` offers two distinct ways to read an external Parquet file
without importing it, and they are **not** the same capability, however
similar the documentation makes them sound at a glance.

**4.1 — `read_parquet()`: projection pushdown only**

```sql
EXPLAIN (ANALYZE, BUFFERS) SELECT count(*)
FROM pgcolumnar.read_parquet('/tmp/sensor_readings.parquet')
  AS t(id bigint, sensor_id int, sensor_type text, reading_value double precision, recorded_at timestamptz)
WHERE sensor_id = 1;
```

```
 ->  Function Scan on read_parquet t
       Filter: (sensor_id = 1)
       Buffers: shared hit=12, temp read=63598 written=63598
 Execution Time: 2628.1 ms
```

A plain `Function Scan`, `temp read/written` in the tens of thousands
of pages — the *entire* file gets materialized into a tuplestore before
the `WHERE` clause ever runs. This is architecturally unavoidable, not
a bug: **PostgreSQL's planner never pushes a `WHERE` clause into an
ordinary set-returning function.** The authoritative SQL reference
actually says this precisely, once you read past the friendlier
features page: `read_parquet()` does projection pushdown (decodes only
the columns you declare) and nothing else. Predicate pushdown is a
different feature, described for a different object.

**4.2 — The `pgcolumnar_parquet` FDW: this is the one that matters**

```sql
CREATE SERVER pq FOREIGN DATA WRAPPER pgcolumnar_parquet;
```

```
ERROR:  permission denied for foreign-data wrapper pgcolumnar_parquet
```

The same wall Chapter 17 documented for `postgres_fdw`/`file_fdw` — a
fresh FDW needs explicit `USAGE` before a non-superuser can touch it:

```sql
GRANT USAGE ON FOREIGN DATA WRAPPER pgcolumnar_parquet TO chris;
```

```sql
CREATE FOREIGN TABLE sensor_readings_pq
  (id bigint, sensor_id int, sensor_type text, reading_value double precision, recorded_at timestamp)
  SERVER pq OPTIONS (path '/tmp/sensor_readings.parquet');
```

Unlike the plain function, a foreign table *is* something the planner
can push quals into — this is the actual analog of Chapter 17's unbuilt
`parquet_s3_fdw`, and the documentation for it is explicit:
"row groups whose min/max statistics exclude the query's predicate are
skipped." `EXPLAIN` reports the counters directly:

```sql
EXPLAIN (ANALYZE, COSTS OFF) SELECT count(*) FROM sensor_readings_pq WHERE sensor_id = 1;
```

```
 ->  Foreign Scan on sensor_readings_pq
       Filter: (sensor_id = 1)
       Row Groups: 148
       Row Groups Skipped: 0
       Row Groups Decoded: 148
 Execution Time: 1274.9 ms
```

Zero skipped — but `sensor_id` has the exact same scatter problem
Exercise 2 already found for `sensor_type`, so this alone doesn't prove
anything is wrong. The real test needs data that's *actually* clustered
on the filtered column.

---

### Exercise 5 — The Wall: Row-Group Skip Doesn't Fire Even When It Should

**5.1 — Build the fair test**

Sort the columnar table by `id` — a real, verified, complete sort, not
an assumption:

```sql
SELECT pgcolumnar.vacuum_sorted('sensor_readings_columnar', 'id');
SELECT * FROM pgcolumnar.sort_status('sensor_readings_columnar');
```

```
 sort_key | sorted_kind   | total_groups | sorted_groups | appended_groups
----------+---------------+--------------+----------------+------------------
 {id}     | lexicographic |           65 |             65 |                0
```

Fully sorted — no unsorted tail. Re-export, and confirm the file itself
preserves that order:

```sql
SELECT pgcolumnar.export_parquet('sensor_readings_columnar', '/tmp/sensor_readings_sorted.parquet');
```

```sql
SELECT id FROM sensor_readings_pq_sorted LIMIT 5;  -- 892801, 892802, 892803, 892804, 892805
```

**5.2 — The test that should work, and doesn't**

```sql
EXPLAIN (ANALYZE, COSTS OFF) SELECT count(*)
FROM sensor_readings_pq_sorted WHERE id < 942801::bigint;
```

```
 ->  Foreign Scan on sensor_readings_pq_sorted
       Filter: (id < '942801'::bigint)
       Row Groups: 148
       Row Groups Skipped: 0
       Row Groups Decoded: 148
 Execution Time: 1348.7 ms
```

Every documented condition is met: a genuinely, fully sorted `bigint`
column, a plain `column < constant` comparison, the constant explicitly
typed to match (`::bigint`, visible right there in the `Filter:` line —
no cross-type mismatch hiding anywhere). **Zero row groups skipped
anyway.**

**5.3 — Ruling out "maybe this needs a newer PostgreSQL"**

`pgColumnar`'s own docs gate several *other* features behind PostgreSQL
17 — `read_stream` prefetch, `MERGE`'s `WHEN NOT MATCHED BY SOURCE`,
`ALTER TABLE ... SET ACCESS METHOD` on a partitioned table. None of
those notes actually mention the Parquet FDW's skip logic, but it was a
reasonable hypothesis worth eliminating cheaply — which is exactly what
this chapter's own container was built for. The identical test, run
fresh on PostgreSQL 18.6 instead of the host's PostgreSQL 16, with a
brand-new install and a freshly sorted, freshly exported file:

```
 Row Groups: 148
 Row Groups Skipped: 0
 Row Groups Decoded: 148
 Execution Time: 1348.689 ms
```

**Identical result, both majors.** Not a PG16 artifact, not
version-gated — a real gap between this build's own documentation and
its own `EXPLAIN` output.

**5.4 — A minimal repro, and reporting it**

Chapter 17's 9.6-million-row table is not a fair thing to hand a
maintainer as a bug report. A clean, dataset-independent repro, built
and verified before filing anything:

```sql
CREATE TABLE skip_repro (id bigint, val int) USING pgcolumnar;
INSERT INTO skip_repro SELECT g, (random()*1000)::int FROM generate_series(1, 1000000) g;
SELECT pgcolumnar.vacuum_sorted('skip_repro', 'id');
SELECT pgcolumnar.export_parquet('skip_repro', '/tmp/skip_repro.parquet');
CREATE SERVER pq_repro FOREIGN DATA WRAPPER pgcolumnar_parquet;
CREATE FOREIGN TABLE skip_repro_pq (id bigint, val int)
  SERVER pq_repro OPTIONS (path '/tmp/skip_repro.parquet');
```

```sql
-- control: the native table, same sorted data
EXPLAIN (ANALYZE, COSTS OFF) SELECT count(*) FROM skip_repro WHERE id < 5000::bigint;
--   Columnar Chunk Groups Removed by Filter: 6 (of 7)
--   Execution Time: 0.994 ms

-- the FDW, identical predicate, exported moments earlier
EXPLAIN (ANALYZE, COSTS OFF) SELECT count(*) FROM skip_repro_pq WHERE id < 5000::bigint;
--   Row Groups Skipped: 0 (of 16)
--   Execution Time: 127.201 ms
```

The control proves the skip *machinery* works fine in this build — it's
isolated to the external-Parquet read path specifically. A search
across every open and closed issue in `commandprompt/pgcolumnar`
(a genuinely fast-moving tracker — hundreds of issues, most opened and
closed within hours) turned up close relatives — #620, an earlier
"reads the whole file before returning any row" bug in this exact FDW,
fixed well before this build — but nothing matching this specific
symptom. Filed as
**[commandprompt/pgcolumnar#850](https://github.com/commandprompt/pgcolumnar/issues/850)**,
with this minimal repro, the sort-status proof, and the PG16/PG18
cross-check.

---

## Decision Guide: Native Table vs. External Parquet, as Tested

| Need | Use | Verified here |
|---|---|---|
| Fast, compressed, query-time analytics fully inside PostgreSQL | `pgColumnar` native table (`USING pgcolumnar`) | 40.4x compression, ~8,700x on unfiltered aggregates, real chunk-group skip once sorted |
| Portable, engine-agnostic export other tools can read | Chapter 17's hand-rolled pyarrow + Snappy | 46x compression, genuinely smaller than `export_parquet()`'s uncompressed 405 MB output |
| Querying an external Parquet file's *columns* without importing | `pgcolumnar.read_parquet()` | Works exactly as documented — projection pushdown only, reads the whole file every time |
| Querying an external Parquet file with row-group-level `WHERE` pruning | `pgcolumnar_parquet` FDW | **Does not currently deliver this** — verified `Row Groups Skipped: 0` under textbook conditions, filed as #850 |

The honest bottom line: `pgColumnar`'s native storage is the real,
working half of this chapter's contrast with Chapter 17 — a genuinely
different, faster tool for keeping compressed analytics inside
PostgreSQL. Its Parquet-FDW half, the piece built specifically to
finish what Chapter 17 left open, does not yet do what its own
documentation says it does. Both conclusions came from running the
same kind of test — create real data, sort it, measure it, read
`EXPLAIN`'s own counters — not from trusting either the marketing page
or the pessimistic assumption that "it's alpha, so it probably doesn't
work."

---

## Summary — What You Should Now Know

| Concept | What it does |
|---------|----------------|
| `CREATE TABLE ... USING pgcolumnar` | Native columnar storage inside PostgreSQL — real WAL, real MVCC, no external file |
| `shared_preload_libraries` before first start | The safe way to load a new extension's library — a live `ALTER SYSTEM SET` on a `GUC_LIST_QUOTE` parameter can silently corrupt the whole list |
| Chunk-group skip, unsorted vs. sorted | Scattered filter columns get zero benefit from zone maps, exactly like Chapter 20's b-tree finding — `vacuum_sorted` fixes it, at a real compression cost to other columns |
| `pgcolumnar.export_parquet()` | No compression option — genuinely larger output than a deliberately-compressed hand-rolled export |
| `read_parquet()` vs. `pgcolumnar_parquet` FDW | Projection-only vs. (documented, not yet delivered) predicate pushdown — a plain SQL function can never receive a pushed-down qual, a foreign table can |
| `Row Groups Skipped` in `EXPLAIN` | The real, checkable proof of whether pruning happened — reads 0 here even on fully sorted, correctly-typed data (filed upstream, #850) |
| Cross-version retest before reporting a bug | Confirmed the finding on both PostgreSQL 16 and 18 before filing, ruling out a version-gating explanation the docs made plausible |

**The key design insight** from this chapter is the same discipline
Chapters 21 and 22 already established for young software, applied
this time to something with real production ambitions rather than
research-beta uncertainty: a well-documented, MIT-licensed extension
with an active issue tracker and hundreds of self-reported, fixed bugs
is still worth exactly what you can verify about it yourself, feature
by feature. `pgColumnar`'s native storage held up completely under
direct measurement. Its promise to finish what Chapter 17 started did
not — and the difference between those two verdicts was only visible
because this chapter tested both halves separately instead of taking
"it supports Parquet" as one claim.

---

*Going further: issue **#850** is open as of this writing — this
chapter's finding, not yet resolved upstream. The retest is a queued,
not-yet-done task: once the issue is closed (or the maintainer responds
with a reason it isn't a bug), Exercise 5 should be re-run against
whatever build fixes it, and this chapter's Decision Guide row for the
Parquet FDW updated to match — the same "verify again against whatever
release you're actually running" discipline Chapter 21 named explicitly
for PostgreSQL 19's own beta gap. Until then, treat `pgcolumnar_parquet`
as Chapter 17 Exercise 6.3 already implicitly did: a real, promising
pattern, not yet something to depend on for row-group pruning in
production.*
