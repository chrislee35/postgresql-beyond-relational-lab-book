# Chapter 24 — `pgColumnar`: Storing Data by Column Instead of by Row

> *Ask a heap table to add up one column, and it still has to carry
> every other column past you on the way to the answer. A table built
> column by column only ever picks up the column you asked for.*

---

## Background

Since Chapter 8, Portsmith's sensor network has been writing readings
into `sensor_readings` — temperature, traffic counts, air quality —
one row at a time, every few minutes, from well over a hundred sensors
around the city. By now the table holds more than 9.6 million rows.
That was always the right way to store it for *writing*: a new reading
comes in, one row goes in, done.

But lately the questions being asked of that table have changed shape.
Public Works doesn't want one row anymore — they want the big picture.
"How many readings do we actually have?" "What's the average air
quality reading been, city-wide?" "Show me a monthly rollup for every
sensor type." Every one of those questions only really cares about one
or two of the table's five columns, but answering them today means
PostgreSQL has to read through nearly 700 megabytes of row-by-row
storage — every column of every row — to get there. The queries still
work. They've just gotten slow enough that people notice.

**Here's the underlying idea worth having in your head before anything
else in this chapter:** think of `sensor_readings` as a filing cabinet
of index cards, one card per reading, each card listing all five
fields — sensor, type, value, time, id. Asking "what's the average
reading value?" means pulling out *every card* and reading past four
fields you don't care about just to get to the fifth. Now imagine
instead you kept five separate folders — one holding nothing but every
`reading_value` ever recorded, another holding nothing but every
`sensor_type`, and so on. That same question now means opening exactly
one folder. You never touch the other four at all. That second
arrangement — organizing storage **by column instead of by row** — is
what this chapter is about, and it's a genuinely different tool from
anything else in this book, not just a faster version of the same
thing.

**`pgColumnar`** is a free, open-source extension that adds this
second storage style directly inside PostgreSQL. Concretely, it adds a
new **table access method** — PostgreSQL's name for "the actual way a
table's rows are physically arranged on disk." Every table you've
built so far in this book used the default access method, called
`heap`, which is the filing-cabinet arrangement above: each row's
values sit together, in insertion order. `pgColumnar` adds a second
option, `USING pgcolumnar`, which stores the same data in the
folder-by-column arrangement instead — still a real PostgreSQL table,
still queried with ordinary `SELECT`, just organized differently
underneath.

It also has a second, separate feature: reading and writing files in
**Parquet** format, the same file format Chapter 17 exported
`sensor_readings` into by hand. That looked, at first, like it might
finally close a loose end Chapter 17 left open — Exercise 6 there
stopped short of actually querying an exported Parquet file back
*through* PostgreSQL, because the extension that would have done it
was too hard to build from source. This chapter tries `pgColumnar`'s
version of that instead. It's worth one section later on, with an
honest result — but it isn't the main event here. The main event is
the folder-by-column idea above, and whether it delivers for Portsmith
in practice. It does, clearly and measurably, and that's most of what
follows.

One real setup story, worth knowing before you follow this chapter's
own steps: the first attempt to install `pgColumnar` used the same
`ALTER SYSTEM SET` approach Chapters 19–20 already used for `pg_cron`
and `pg_stat_statements`, directly against the shared PostgreSQL 16
host every earlier chapter runs on. It went wrong in a way neither of
us expected — `ALTER SYSTEM` silently wrote a corrupted value into
PostgreSQL's config, and the *entire* cluster refused to start
afterward, taking down every chapter's live data for about twenty
minutes while it got diagnosed and fixed by hand. Nothing about
`pgColumnar` itself caused that; it was a real, narrow PostgreSQL
pitfall in how one specific kind of setting gets updated live. The
practical upshot, and the reason this chapter runs in its own
container instead: see this chapter's Environment Setup section for
exactly what happened and the one-line fix that avoids it entirely.

---

## The Scenario

| Object                          | Lives in                          | Purpose                                                         |
|----------------------------------|--------------------------------------|---------------------------------------------------------------------|
| `sensor_readings_columnar`         | `portsmith24` (a new container)      | A column-organized copy of Chapter 8/17's `sensor_readings` — same data, same 9.6M+ rows, stored the other way |
| `/tmp/sensor_readings.parquet`      | Container filesystem              | A Parquet export of that same data, produced by `pgColumnar` itself, for the "what about Chapter 17's files" section |
| `sensor_readings_pq`                | `portsmith24`                        | A foreign table over that Parquet file — this chapter's attempt to finish what Chapter 17 Exercise 6 left undone |

`sensor_readings` itself never moves — it stays exactly where Chapter
8 built it, on the main PostgreSQL 16 cluster, still the table every
sensor keeps writing into. Everything in this chapter is a live copy,
piped across for analysis, the same "keep the operational table alone,
build a separate copy for reporting" instinct Chapter 9's materialized
views already taught.

---

## Exercise Goals

By the end of this chapter you will be able to:

- Explain, in plain terms, the difference between row-organized and
  column-organized storage, and why one favors writing single records
  quickly while the other favors answering questions about millions of
  records at once.
- Create a column-organized copy of a real table with `pgColumnar`,
  and measure exactly what changes — both storage size and query
  speed — against the same data stored the ordinary way.
- Understand why a column-organized table isn't automatically faster
  for every query, and what "sorting the data" actually buys you when
  it isn't.
- Know, from a real incident, why a new extension's startup
  configuration belongs in a config file before the database ever
  starts, not in a live command against a running one.
- Get an honest, tested answer to whether `pgColumnar` can also read
  Chapter 17's exported Parquet files efficiently from inside
  PostgreSQL — and know exactly what it can and can't do yet.

---

## Environment Setup — A Fourth Container

`docker/ch24/` — the same three-file shape as Chapters 21 and 22's
containers (`Dockerfile`, `entrypoint.sh`, `docker-compose.yml`), built
on PostgreSQL 18.

```bash
cd docker/ch24
docker compose up --build
```

Listens on host port **5435** (5432 = main cluster, 5433 = Chapter 21,
5434 = Chapters 22–23).

**The real incident, in full, since it's a useful lesson on its own.**
Loading a new extension into PostgreSQL requires listing it in a
setting called `shared_preload_libraries` — a comma-separated list of
libraries PostgreSQL loads the moment it starts. Chapters 19–20 added
to this same list for `pg_cron` and `pg_stat_statements` with `ALTER
SYSTEM SET`, run against an already-running server, and it worked
fine both times. Doing the same thing for `pgcolumnar` didn't:

```
shared_preload_libraries = '"pg_cron,pg_stat_statements,auto_explain,pgcolumnar"'
```

Look closely at that value: there's an extra pair of quotation marks
wrapped around the *whole* list. PostgreSQL read that as one single
library literally named
`pg_cron,pg_stat_statements,auto_explain,pgcolumnar` — commas and all
— tried to load it, failed, and refused to start at all. The whole
cluster was down until that stray pair of quotes was found and removed
by hand. This is a real, narrow bug in how `ALTER SYSTEM SET` handles
this particular kind of list-shaped setting — not something either of
us mistyped.

The fix this chapter's container uses instead: write the setting
straight into the config file *before* the database has ever started
for the first time, so there's no live update to get wrong:

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

One more small prerequisite, easy to miss: building `pgColumnar` needs
PostgreSQL's *development headers* (`postgresql-server-dev-18`), not
just the plain server package — without them the build fails
immediately looking for a missing file, `postgres.h`. Already handled
in `docker/ch24/Dockerfile`.

**Getting `sensor_readings` across.** No PostGIS, no generated columns
to worry about here:

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

### Exercise 1 — Building a Column-Organized Copy

```sql
CREATE TABLE sensor_readings_columnar (
    id             bigint,
    sensor_id      int,
    sensor_type    text,
    reading_value  double precision,
    recorded_at    timestamptz
) USING pgcolumnar;
```

That `USING pgcolumnar` is the entire difference from every `CREATE
TABLE` earlier in this book — everything else about the table (its
columns, its types, how you `INSERT` and `SELECT` from it) works
exactly the same. No extra permission needed to create or use it,
either; it's available the moment the extension exists.

**Storage, measured directly:**

```sql
SELECT pg_size_pretty(sum(pg_relation_size(inhrelid))) AS heap_table_only
FROM pg_inherits WHERE inhparent = 'sensor_readings'::regclass;
-- 708 MB

SELECT pg_size_pretty(pg_total_relation_size('sensor_readings_columnar'));
-- 18 MB
```

**708 MB down to 18 MB — a real, measured 40x smaller**, for exactly
the same 9,648,001 rows. Two things make that possible: values from
the same column tend to look alike (a `sensor_type` column only ever
holds one of three words), which compresses well once they're grouped
together — and, just as important, the folder-by-column layout means a
query never has to *read* the columns it doesn't need in the first
place, which is what the next exercise measures.

---

### Exercise 2 — The Easy Win: Answering Without Reading

The simplest possible question — "how many readings do we have?" —
turns out to be the clearest demonstration of what column storage
buys you.

```sql
EXPLAIN (ANALYZE) SELECT count(*) FROM sensor_readings;          -- the original, row-organized table
-- Execution Time: 562.7 ms

EXPLAIN (ANALYZE) SELECT count(*) FROM sensor_readings_columnar; -- the column-organized copy
```

```
 Custom Scan (PgColumnarScan)  (actual time=0.019..0.019 rows=1 loops=1)
   Columnar Vectorized Aggregates: 1
 Execution Time: 0.065 ms
```

**562.7 ms down to 0.065 ms — roughly 8,700 times faster.** Nothing
was decoded and nothing was scanned. `pgColumnar` keeps a running row
count for each stored group of data as a side note, the way a librarian
might keep a running tally of how many books are on a shelf instead of
counting them fresh every time someone asks. `count(*)` with no filter
is answered straight from that tally — the same reason Chapter 9's
materialized views win: the answer was already sitting there, computed
once, not recomputed from scratch on every query.

---

### Exercise 3 — A Realistic Query: Why "Faster" Isn't Automatic

Public Works rarely wants a citywide total — they want it broken down.
"What's the average reading from our *temperature* sensors?" is a much
more typical question, and this is where column storage stops being
an automatic win.

```sql
EXPLAIN (ANALYZE, BUFFERS) SELECT count(*), avg(reading_value)
FROM sensor_readings WHERE sensor_type = 'temperature';          -- original table
-- Execution Time: 486.6 ms

EXPLAIN (ANALYZE, BUFFERS) SELECT count(*), avg(reading_value)
FROM sensor_readings_columnar WHERE sensor_type = 'temperature'; -- columnar copy
```

```
 ->  Custom Scan (PgColumnarScan) on sensor_readings_columnar
       Filter: (sensor_type = 'temperature'::text)
       Columnar Chunk Groups Total: 65
       Columnar Chunk Groups Removed by Filter: 0
 Execution Time: 1459.5 ms
```

**The columnar copy is slower here — 1459.5 ms against the original's
486.6 ms.** `pgColumnar` stores rows in large batches called **chunk
groups** (think: which folder each index card's fields ended up
filed into, in the order they arrived), and it keeps a note of the
lowest and highest value each chunk group holds for each column — a
**zone map** — so it can sometimes skip a whole chunk group without
reading it, if the value you're filtering for can't possibly be in
that range. Here, `"Columnar Chunk Groups Removed by Filter: 0"` — none
were skipped. Readings from every sensor type arrive continuously, all
day, every day, so a chunk group built from "whatever came in this
hour" ends up with temperature, traffic, *and* air-quality readings
mixed together — every group's range looks the same as every other
group's, so the zone map has nothing useful to rule out.

---

### Exercise 4 — Fixing It, and What It Costs

`pgColumnar` can physically re-sort a table's stored data around a
chosen column, which rebuilds those chunk groups so each one holds a
narrower range of values instead of an even mix:

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

**370.3 ms — now genuinely faster than the original table's 486.6
ms**, with 32 of 43 chunk groups skipped entirely. But storage moved
too:

```sql
SELECT pg_size_pretty(pg_total_relation_size('sensor_readings_columnar'));
-- 27 MB   (up from 18 MB)
```

Sorting by `sensor_type` shuffled the arrival-time order that made
`recorded_at` compress so well in Exercise 1 — every column shares the
same physical row order in a column-organized table, so improving one
column's ability to skip data can cost another column's compression.
**This is the same lesson Chapter 20 already taught with an ordinary
index: the "obvious" fix isn't free, and the only way to know whether
it's worth the tradeoff is to measure both sides — which is exactly
what deciding whether, and how, to sort a real `pgColumnar` table for
Public Works' actual dashboard queries would require.**

<img src="imgs/ch24_pgcolumnar_findings.svg" alt="Side-by-side comparison: the original heap-organized sensor_readings table at 708 megabytes, where every column of every row is stored together, taking 562.7 milliseconds to count all rows and 486.6 milliseconds to average a filtered subset; against the columnar copy at 18 to 27 megabytes, where each column is stored and compressed separately, answering an unfiltered count in 0.065 milliseconds from metadata alone and a filtered, sorted average in 370.3 milliseconds by skipping most of the data entirely"/>

---

### Exercise 5 — What About the Parquet Files From Chapter 17?

`pgColumnar` can also export a table to Parquet, and read Parquet
files back — the same file format Chapter 17 used, and worth checking
honestly, since it's the closest thing this book has found yet to
finishing Chapter 17 Exercise 6's unfinished last step.

```sql
SELECT pgcolumnar.export_parquet('sensor_readings_columnar', '/tmp/sensor_readings.parquet');
```

```bash
$ ls -la /tmp/sensor_readings.parquet
-rw------- 1 postgres postgres 405515796 sensor_readings.parquet   -- 405 MB
```

That's noticeably bigger than Chapter 17's hand-built export of the
same table (16.7 MB) — the export function here doesn't compress the
file at all, unlike the compression `pgColumnar`'s own storage uses.
Worth knowing if you're choosing between the two: this export is fast
and simple, but Chapter 17's more deliberate, hand-tuned pyarrow
script still makes the smaller file.

Reading a Parquet file back works two ways. `read_parquet()` reads
the whole file every time, decoding only the columns you ask for — a
real, useful savings, but it doesn't skip rows based on a `WHERE`
clause, so it isn't a substitute for an index or a zone map. A second
way, a proper foreign table (`CREATE SERVER ... FOREIGN DATA WRAPPER
pgcolumnar_parquet`), is documented to skip whole chunks of the file
when a filter rules them out — the exact capability that would finish
Chapter 17's story. Testing it directly, on data confirmed sorted the
same way Exercise 4 sorted it, that skipping didn't happen in the
version tested here: `EXPLAIN` reported reading every chunk of the
file regardless of the filter, on both PostgreSQL 16 and a fresh
PostgreSQL 18 install.

**The honest takeaway: `pgColumnar`'s own storage — everything
Exercises 1 through 4 just measured — is the real, working half of
this chapter. Its ability to efficiently query Chapter 17's exported
files is not there yet**, at least not in the version tested. That's a
fine place to leave it — Chapter 17's pattern (export to Parquet, read
it with a tool built for that job, like DuckDB) is still the
dependable path for that specific need.

---

## Decision Guide: When to Reach for `pgColumnar`

| Situation | What to use |
|---|---|
| A table gets written to constantly, one row at a time (sensors, permit applications, orders) | An ordinary heap table — this is what it's built for |
| Big-picture questions over millions of existing rows — totals, averages, monthly rollups | A `pgColumnar` copy: real, measured wins here (40x smaller, up to ~8,700x faster on the right query) |
| You know which column you'll usually filter by | Sort the columnar copy on that column (`vacuum_sorted`) — but expect a real compression tradeoff, and measure before assuming it's worth it |
| Reading a Parquet file exported elsewhere, efficiently, from inside PostgreSQL | Not yet dependable here — use Chapter 17's export-and-read-with-DuckDB pattern instead |

---

## Summary — What You Should Now Know

| Concept | What it does |
|---------|----------------|
| Row storage vs. column storage | Row storage (the default) keeps a record's fields together — good for writing one row at a time. Column storage keeps each field together across every record — good for questions that only touch a few columns out of many |
| `CREATE TABLE ... USING pgcolumnar` | Adds a column-organized copy of a table, right inside PostgreSQL — no separate warehouse system |
| Real, measured wins | 708 MB → 18 MB (40x smaller); `count(*)` 562.7 ms → 0.065 ms (~8,700x) |
| Chunk groups and zone maps | Data is stored in batches, each with a note of its min/max values per column — lets a query skip a whole batch it can't match, but only if the filtered column is actually grouped that way |
| `vacuum_sorted` | Physically re-sorts a table around one column, so its zone maps become useful — at a real cost to how well *other* columns compress |
| `shared_preload_libraries` before first start | The safe way to load a new extension — a live `ALTER SYSTEM SET` on this particular kind of setting can silently corrupt the whole list |
| Reading Chapter 17's Parquet files back | Not yet a strength of this extension — its own native storage is the part worth using today |

**The key design insight** from this chapter is the one Public Works
actually needed answered: keep writing sensor readings the ordinary
way, one row at a time, and keep a second, column-organized copy
around specifically for the big questions. Neither storage style is
better in general — a heap table is still the right choice for
`sensor_readings` itself, exactly as Chapter 8 built it, and a
`pgColumnar` copy is the right choice for the reporting queries layered
on top of it. That's the same instinct behind Chapter 9's materialized
views, applied one level deeper: sometimes the fastest way to answer a
different *kind* of question isn't a smarter query — it's storing the
same data a second way.

---

*Going further: the Parquet-reading gap noted in Exercise 5 is worth
revisiting later, since `pgColumnar` is young, actively developed
software — what didn't work during this chapter's testing may well
work in a newer release. If you pick this chapter back up, it's worth
checking whether a newer `pgColumnar` version closes that gap before
assuming Chapter 17's DuckDB-based pattern is still the only option.*
