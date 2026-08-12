# Chapter 20 — `pg_stat_statements` and Query Performance

> *"It's slow" is a feeling. "This queryid has a mean execution time of
> 440ms across 964,800 rows touched, up from 47ms last week" is a fact
> — and only one of those is actionable.*

---

## Background

Every chapter so far has looked at PostgreSQL from the perspective of
what it can store and how to query it correctly. This chapter asks a
different question of the exact same database: not *is this query
right*, but *is this query fast, and if not, why not, and how would
you know before a user told you*. Three tools, working together:

- **`pg_stat_statements`** — every statement PostgreSQL runs, normalized
  (literal values replaced with `$1`, `$2`, ...) and aggregated: call
  count, total time, mean time, rows, buffers. The answer to "what's
  actually slow, in aggregate, right now."
- **`EXPLAIN (ANALYZE, BUFFERS)`** — the answer to "why," for one
  specific query: the plan PostgreSQL actually chose, with real timing
  and real I/O counts, not just the planner's estimate.
- **`auto_explain`** — the same `EXPLAIN` output, captured automatically
  for any query slower than a threshold you set, without needing to
  already suspect which query to go looking for.

Chapter 19 treated `cron.job_run_details` as a first-class thing to
monitor rather than just read once by hand. This chapter applies the
same discipline to query performance: not a one-time diagnosis, but an
ongoing signal worth checking after every deploy.

---

## The Scenario

This chapter intentionally introduces the three classic shapes of slow
query against tables already built by earlier chapters — nothing new
seeded, everything real:

| Problem | Where |
|---------|--------|
| An implicit cast defeating an index | `businesses.id` (Chapter 1) |
| A missing index on a large table | `sensor_readings` (Chapter 8, 9.6M rows) |
| A plan regression after a schema change | The same `sensor_readings` index, deliberately dropped and restored |

---

## Exercise Goals

By the end of this chapter you will be able to:

- Find the queries actually costing the most aggregate time in a real
  system, not just the ones that feel slow.
- Read a full `EXPLAIN (ANALYZE, BUFFERS)` plan node by node.
- Recognize an implicit cast defeating an index from its plan shape
  alone.
- Diagnose a sequential scan on a large table — and know that "add an
  index" isn't automatically the fix; the *right* index, matching how
  the table is actually queried, is what matters.
- Use `auto_explain` to capture slow-query plans without needing to
  already know which query to chase.
- Build a before/after snapshot comparison to catch a plan regression
  the moment it happens, not weeks later.

---

## Installation

`pg_stat_statements` and `auto_explain` were already added to
`shared_preload_libraries` alongside `pg_cron` back in Chapter 19's
setup, and `pg_stat_statements` was created as an extension at the same
time:

```sql
-- as postgres, in portsmith — already done in Chapter 19's setup
CREATE EXTENSION pg_stat_statements;
```

Two functions this chapter needs are both revoked from `PUBLIC` by
default — worth granting up front rather than mid-exercise:

```sql
-- as postgres
GRANT EXECUTE ON FUNCTION pg_stat_statements_reset(oid, oid, bigint) TO chris;
GRANT EXECUTE ON FUNCTION pg_reload_conf() TO chris;
```

The first attempt at the reset grant is worth knowing about even though
it's avoided here: `pg_stat_statements_reset()` — no arguments — doesn't
exist in current versions; the real signature takes three optional
filter arguments (`userid`, `dbid`, `queryid`, all defaulting to `0`,
meaning "reset everything"). `\df pg_stat_statements_reset` is the fast
way to check a signature before writing a `GRANT` for it, instead of
guessing.

---

## Exercises

---

### Exercise 1 — Finding What's Actually Slow

```sql
SELECT pg_stat_statements_reset();
```

A representative mix of real queries against this book's data — some
run often and cheap, one run rarely but expensive:

```sql
SELECT query, calls, round(total_exec_time::numeric, 2) AS total_ms,
       round(mean_exec_time::numeric, 3) AS mean_ms, rows
FROM   pg_stat_statements
ORDER  BY total_exec_time DESC
LIMIT  10;
```

```
                                            query                                             | calls | total_ms | mean_ms | rows
------------------------------------------------------------------------------------------------+-------+----------+---------+-------
 SELECT count(*) FROM sensor_readings WHERE sensor_type = $1                                    |     2 |   879.08 | 439.541 |     2
 SELECT * FROM businesses WHERE id = $1                                                          |    30 |   160.14 |   5.338 |    30
 SELECT * FROM sensor_readings WHERE sensor_id = $1 AND recorded_at >= $2 AND recorded_at < $3   |    15 |    55.18 |   3.678 | 23520
 SELECT * FROM businesses WHERE details @> $1                                                    |    10 |    46.31 |   4.631 |   150
 SELECT id FROM jobs WHERE status = $1 ORDER BY priority, created_at LIMIT $2 FOR UPDATE SKIP LOCKED |  25 |  2.26 |   0.090 |    25
```

Two real lessons sitting side by side. First, literal values are
normalized away (`$1`, `$2`) — every call to "look up one business by
id" collapses into a single row here regardless of *which* id, which is
exactly what makes aggregation meaningful instead of one row per unique
query text. Second, and the actual point of ranking by `total_exec_time`
rather than `mean_exec_time`: a query called only **twice** (an
unindexed `count(*)` over 9.6 million rows) costs more in aggregate
than a well-indexed lookup called **thirty times**. Frequency and
per-call cost are independent axes, and a rare expensive query hiding
behind a wall of cheap frequent ones is precisely what this view is
for catching.

---

### Exercise 2 — Reading a Full Plan

```sql
EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
SELECT * FROM sensor_readings WHERE sensor_id = 5;
```

```
 Gather  (cost=1000.00..151794.26 rows=97046 width=42) (actual time=12.772..300.728 rows=96480 loops=1)
   Workers Planned: 2
   Workers Launched: 2
   Buffers: shared hit=1812 read=88823
   ->  Parallel Append  (cost=0.00..141089.66 rows=40436 width=42) (actual time=13.683..273.244 rows=32160 loops=3)
         Buffers: shared hit=1812 read=88823
         ->  Parallel Seq Scan on sensor_readings_2024_03 sensor_readings_2  (cost=0.00..13034.00 rows=3608 width=42) (actual time=14.335..84.003 rows=8928 loops=1)
               Filter: (sensor_id = 5)
               Rows Removed by Filter: 883872
               Buffers: shared hit=129 read=8255
         ... (one Parallel Seq Scan per partition)
 Planning Time: 1.980 ms
 Execution Time: 338.496 ms
```

Node by node, outside in:

| Node | Meaning |
|------|----------|
| `Gather` | The parallel query's top: collects rows from worker processes back into one stream |
| `Workers Planned` / `Launched` | How many parallel workers PostgreSQL asked for vs. actually got — a mismatch here would itself be worth investigating (`max_parallel_workers` exhausted) |
| `Parallel Append` | Chapter 8's partitioning at work: each partition scanned independently, results appended |
| `Parallel Seq Scan on sensor_readings_2024_03` | One partition, scanned start to finish — no index used |
| `Filter: (sensor_id = 5)` | The condition applied *after* reading each row — the tell that no index narrowed things down first |
| `Rows Removed by Filter: 883872` | Nearly 884,000 rows read and discarded, in this partition alone, to find the ~9,000 that matched |
| `Buffers: shared hit=... read=...` | `hit` = found in PostgreSQL's own buffer cache; `read` = a real disk read — `read=88823` here means the bulk of this query's cost is genuine I/O, not CPU |
| `Execution Time: 338.496 ms` | The number that actually matters to whoever's waiting on this query |

`ANALYZE` runs the query for real and reports actual timing and row
counts alongside the planner's original estimates; `BUFFERS` adds the
I/O accounting. Without both, `EXPLAIN` alone only shows what
PostgreSQL *expected*, not what happened.

---

### Exercise 3 — An Implicit Cast Defeating an Index

```sql
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM businesses WHERE id = 5;
```

```
 Index Scan using idx_businesses_replident on businesses  (cost=0.14..8.16 rows=1 width=783) (actual time=0.191..0.192 rows=1 loops=1)
   Index Cond: (id = 5)
   Buffers: shared read=2
```

`Index Cond`, two buffer reads — exactly what a primary-key lookup
should look like. Now the same lookup, with a value typed as `numeric`
instead of `integer` — the kind of thing a client library can do
silently (a JSON-decoded number, a Python `Decimal`, an ORM's default
type mapping for a "generic number" field):

```sql
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM businesses WHERE id = 5::numeric;
```

```
 Seq Scan on businesses  (cost=0.00..8.73 rows=1 width=783) (actual time=0.011..0.313 rows=1 loops=1)
   Filter: ((id)::numeric = '5'::numeric)
   Rows Removed by Filter: 47
   Buffers: shared hit=1 read=7
```

`Filter`, not `Index Cond` — PostgreSQL has wrapped the *column* in a
cast (`(id)::numeric`) to make the comparison type-consistent, and a
plain btree index on `id` (built on `integer` values) can't be used to
satisfy a condition on `id::numeric`. On a 49-row table the wall-clock
difference is invisible — both finish in under half a millisecond,
buried in connection overhead. The plan shape is identical, though, to
Exercise 4's `sensor_id` lookup before it had the right index: exactly
this bug against a multi-million-row table is how a sub-millisecond
primary-key lookup silently becomes a 300ms sequential scan, and
nothing about the query's *result* looks wrong — it just gets slower,
quietly, as the table grows.

The fix is whichever side of the comparison is easiest to control: cast
the *parameter* instead of leaving the column to be cast (`id =
$1::integer` at the application layer), or, if the value's type is
genuinely outside your control, an expression index on
`(id::numeric)` — though matching the parameter's type going in is
almost always the better fix.

---

### Exercise 4 — Diagnosing (and Correctly Fixing) a Sequential Scan

**4.1 — The baseline**

`sensor_readings` has no index on `sensor_id` at all — every lookup by
sensor scans every partition:

```sql
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM sensor_readings WHERE sensor_id = 5;
```

```
 Gather (actual time=12.772..300.728 rows=96480 loops=1)
   ->  Parallel Append ...
         (12 Parallel Seq Scans, one per partition)
 Execution Time: 338.496 ms
```

**4.2 — The obvious fix helps less than expected**

```sql
CREATE INDEX idx_sensor_readings_sensor_id ON sensor_readings (sensor_id);
```

```sql
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM sensor_readings WHERE sensor_id = 5;
```

```
 Append (actual time=1.629..401.335 rows=96480 loops=1)
   Buffers: shared hit=225 read=81071 written=35
   ->  Bitmap Heap Scan on sensor_readings_2024_02 ...
         Buffers: shared hit=131 read=6907
         ->  Bitmap Index Scan on sensor_readings_2024_02_sensor_id_idx ...
 Execution Time: 376.942 ms
```

**Slower**, not faster — a real, worth-understanding result, not a
mistake to paper over. Sensor 5 has 96,480 readings out of 9.6 million,
roughly one row in 120, spread essentially evenly across the whole
table's history — every month, every day, interleaved with every other
sensor's readings. A **Bitmap Heap Scan** still has to visit almost
every 8KB heap page, because at that scatter, virtually every page
contains at least one matching row. The index made the *search* for
matching rows cheap (`Bitmap Index Scan`) but did nothing about the
*fetch* cost, which dominates — and switching from a Parallel Seq Scan
to a plain Bitmap Heap Scan even gave up the free parallelism the
original plan had. An index is not automatically a win; it's a trade
worth actually measuring.

**4.3 — The query that was never realistic in the first place**

Nobody actually asks for "all of sensor 5's history, unbounded." A
real query narrows by time too — and Chapter 8's partitioning already
helps here, with no new index at all:

```sql
DROP INDEX idx_sensor_readings_sensor_id;

EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM sensor_readings
WHERE sensor_id = 5 AND recorded_at >= '2024-06-01' AND recorded_at < '2024-06-08';
```

```
 Gather (actual time=0.301..35.504 rows=2016 loops=1)
   ->  Parallel Seq Scan on sensor_readings_2024_06 sensor_readings
         Filter: (... AND sensor_id = 5)
         Rows Removed by Filter: 287328
 Execution Time: 35.671 ms
```

Partition pruning alone — only `sensor_readings_2024_06` touched, not
all twelve — already beats Exercise 4.2's "fix." The right index closes
the rest of the gap:

```sql
CREATE INDEX idx_sensor_readings_sensor_time ON sensor_readings (sensor_id, recorded_at);
```

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM sensor_readings
WHERE sensor_id = 5 AND recorded_at >= '2024-06-01' AND recorded_at < '2024-06-08';
```

```
 Bitmap Heap Scan on sensor_readings_2024_06 sensor_readings  (actual time=0.587..7.534 rows=2016 loops=1)
   Recheck Cond: (sensor_id = 5 AND recorded_at >= ... AND recorded_at < ...)
   Heap Blocks: exact=1697
   Buffers: shared read=1708
   ->  Bitmap Index Scan on sensor_readings_2024_06_sensor_id_recorded_at_idx
         Buffers: shared read=11
 Execution Time: 7.878 ms
```

**7.9ms** — roughly 4.5x faster than pruning alone, roughly 43x faster
than the original unbounded query, and the honest conclusion of the
whole exercise: the single-column index in 4.2 wasn't wrong because
indexes are bad, it was wrong because it didn't match how the table is
actually queried. A compound index over both the filter column and the
range column, paired with a query shape that was already realistic,
is what actually won.

<img src="imgs/ch20_index_scatter_contrast.svg" alt="Two scenarios contrasted: a single-column index on sensor_id where matching rows are scattered roughly one in every hundred-twenty across the whole 9.6-million-row table, forcing a bitmap heap scan to visit nearly every page and giving up the seq scan's parallelism for a net loss; versus a compound index on (sensor_id, recorded_at) combined with a realistic time-bounded query, where partition pruning already narrows to one month and the index then narrows further within it, visiting a small fraction of the pages for a genuine multiple-times speedup"/>

---

### Exercise 5 — `auto_explain`: Catching Slow Queries Without Knowing to Look

`auto_explain` was proven working back in Chapter 19's environment
setup, logging *every* query at `log_min_duration = 0`. That's useful
for a five-minute test and useless in production — it would flood the
log. A realistic threshold, and turning it on requires nothing at the
session level (it's already preloaded cluster-wide):

```sql
-- as postgres
ALTER SYSTEM SET auto_explain.log_min_duration = 200;   -- milliseconds
```

Reloading config needs its own grant, same shape as
`pg_stat_statements_reset()` above:

```sql
GRANT EXECUTE ON FUNCTION pg_reload_conf() TO chris;
```

```sql
SELECT pg_reload_conf();
```

```sql
SELECT * FROM businesses WHERE id = 3;                                   -- fast — should stay silent
SELECT count(*) FROM sensor_readings WHERE sensor_type = 'air_quality';  -- slow — should log
```

The fast lookup produces nothing in the log. The slow one:

```
LOG:  duration: 374.630 ms  plan:
	Query Text: SELECT count(*) FROM sensor_readings WHERE sensor_type = 'air_quality';
	Finalize Aggregate  (actual time=367.286..374.621 rows=1 loops=1)
	  Buffers: shared hit=15377 read=75258
	  ->  Gather  (actual time=367.178..374.609 rows=3 loops=1)
	        Workers Planned: 2
	        Workers Launched: 2
	        ->  Partial Aggregate  (actual time=354.058..354.061 rows=1 loops=3)
	              ->  Parallel Append  (actual time=16.793..340.363 rows=321600 loops=3)
```

Captured automatically, no application code changed, no prior
suspicion needed about which query would be the slow one — exactly
`sensor_type` doing what Exercise 1's top-10 already flagged as the
single most expensive query in the whole workload, this time caught by
threshold instead of by manually going looking.

---

### Exercise 6 — Catching a Plan Regression Before It's a Production Incident

The point of watching query performance continuously rather than once:
catching a regression the moment a deploy introduces it, not weeks
later when someone complains. A minimal snapshot table and a real
before/after comparison:

**6.1 — Snapshot before a "deploy"**

```sql
CREATE TABLE query_stats_snapshot (
    snapshot_label TEXT,
    snapshot_at    TIMESTAMPTZ DEFAULT clock_timestamp(),
    queryid        BIGINT,
    query          TEXT,
    calls          BIGINT,
    mean_exec_time DOUBLE PRECISION
);

SELECT pg_stat_statements_reset();
-- ... run representative traffic ...

INSERT INTO query_stats_snapshot (snapshot_label, queryid, query, calls, mean_exec_time)
SELECT 'before_deploy', queryid, query, calls, mean_exec_time
FROM   pg_stat_statements
WHERE  query LIKE 'SELECT * FROM sensor_readings WHERE sensor_id%';
```

**6.2 — Simulate the incident: a deploy accidentally drops the index**

```sql
SELECT pg_stat_statements_reset();
DROP INDEX idx_sensor_readings_sensor_time;   -- Exercise 4's fix, reverted "by accident"
-- ... same representative traffic again ...

INSERT INTO query_stats_snapshot (snapshot_label, queryid, query, calls, mean_exec_time)
SELECT 'after_deploy', queryid, query, calls, mean_exec_time
FROM   pg_stat_statements
WHERE  query LIKE 'SELECT * FROM sensor_readings WHERE sensor_id%';
```

**6.3 — Compare**

```sql
SELECT b.mean_exec_time AS before_ms, a.mean_exec_time AS after_ms,
       round((a.mean_exec_time / b.mean_exec_time)::numeric, 1) AS slowdown_factor
FROM   query_stats_snapshot b
JOIN   query_stats_snapshot a ON a.queryid = b.queryid AND a.snapshot_label = 'after_deploy'
WHERE  b.snapshot_label = 'before_deploy';
```

```
 before_ms | after_ms | slowdown_factor
-----------+-----------+------------------
     3.678 |    34.195 |              9.3
```

A real, measured **9.3x** regression, caught by comparing two
snapshots — the same `queryid` (PostgreSQL's normalization from
Exercise 1 making this possible at all: the query text is identical
before and after, so the join above is exact, not a fuzzy text match).
This is deliberately the shape of check worth scheduling — Chapter 19's
`pg_cron` running this comparison nightly, alerting past some threshold
slowdown factor, is the natural next step, closing the loop between
these two chapters. Restore the real fix once satisfied:

```sql
CREATE INDEX idx_sensor_readings_sensor_time ON sensor_readings (sensor_id, recorded_at);
```

---

## Summary — What You Should Now Know

| Tool | What it answers |
|------|-------------------|
| `pg_stat_statements` | *What's* slow, in aggregate — ranked by total time, not just per-call time |
| `EXPLAIN (ANALYZE, BUFFERS)` | *Why* one specific query is slow — real timing, real I/O, node by node |
| `Filter` vs `Index Cond` in a plan | The tell for an implicit cast (or any condition) that isn't reaching an index |
| `auto_explain` | Slow-query capture without needing to already suspect which query |
| Buffer counts (`hit` vs `read`) | Whether a query's cost is CPU or genuine disk I/O |
| A single-column index | Not automatically a win — matching the *scatter* of matching rows to physical pages matters as much as the row count |
| Partition pruning + a compound index | Often the actual fix, when a naive single-column index barely moves the needle |
| `queryid`-matched snapshot comparison | Catches a plan regression by measurement, the same day a deploy causes it |

**The key design insight** from this chapter is that every tool in it
answers a narrower question than it first appears to: `pg_stat_statements`
tells you *what*, not *why*; `EXPLAIN` tells you *why*, for one query,
after the fact; `auto_explain` removes the need to already know
*which* query. None of them, alone, is "the performance tool" — the
actual skill this chapter built is knowing which one answers the
question you're currently asking, and reaching for a real measurement
instead of a guess at every step, including the step where the "fix"
turns out not to help.

---

*Going further: this closes out the book's run through PostgreSQL's
extension and operational surface — Chapter 21, once PostgreSQL 19's
property graph support (`SQL/PGQ`) is out of beta, returns to Chapter
12's recursive CTEs with a genuinely different query model for the
same graph problems. In the meantime, the three tools this chapter
built — `pg_stat_statements`, `EXPLAIN (ANALYZE, BUFFERS)`, and
`auto_explain` — are worth running against every earlier chapter's own
exercises; several of this book's own "real, verified" numbers were
found exactly this way.*
