# Chapter 9 — Materialized Views: Precomputing Expensive Aggregations

> *"A view is a promise to run the query again. A materialized view is a
> promise it already kept — until you ask it to keep it again."*

---

## Background

A plain `VIEW` is a saved query, nothing more. Every time you `SELECT` from
one, PostgreSQL substitutes the view's definition in place and runs the
underlying query from scratch. That's fine for a view whose job is
convenience — hiding a join, naming a filter — but it's a bad deal for a
view whose job is a genuinely expensive aggregation. If a dashboard asks
"average sensor reading per day, per type, for the whole year" a hundred
times a day, a plain view answers that question by scanning millions of
raw rows a hundred times a day, even though the answer barely changes
between asks.

A `MATERIALIZED VIEW` is the other end of that trade: it runs the query
once, writes the result to disk as an honest-to-goodness physical table,
and answers every subsequent `SELECT` from that table instead of the
original data. It can be indexed like any table, because it *is* a table
underneath a `SELECT` definition it remembers. The cost moves from "every
read pays the full aggregation" to "one write pays the full aggregation,
and reads are cheap until you explicitly ask for a refresh." Nothing
about it is automatic — that's the whole trade. A materialized view does
not notice that its source data changed. It sits there, confidently
wrong, until something runs `REFRESH MATERIALIZED VIEW`.

That puts a materialized view in between two other tools you already
have. A plain view is always correct and never fast. A hand-maintained
summary table — one your application code writes to directly, in the
same transaction as the data that feeds it — can be both correct and
fast, but you own every line of the code that keeps it that way. A
materialized view sits in the middle: PostgreSQL owns the *how* (it
already knows how to run the query), you own the *when* (deciding on a
refresh policy is the actual engineering decision this chapter is about).

<img src="imgs/ch09_view_types.svg" alt="Three read paths compared: a plain VIEW re-runs its query on every read; a MATERIALIZED VIEW serves an instant stored snapshot that only changes when REFRESH is run; a hand-maintained summary table is kept in sync by application code writing in the same transaction as the source data"/>

---

## The Scenario

Portsmith's ops team wants a dashboard: daily and monthly rollups of the
sensor network from Chapter 8 — average readings, counts, mins and maxes,
sliced by day and sensor type. `sensor_readings` now holds 9,648,000 rows
across eleven monthly partitions plus a default partition, and it only
grows. Nobody wants the dashboard to re-scan that on every page load, and
nobody wants to hand-write application code that keeps a summary table in
sync by hand either. This chapter builds the rollups as materialized
views instead, and spends its exercises on the part that's actually hard
about them: deciding how and when they get refreshed.

| Object                  | Purpose                                                                |
|--------------------------|-------------------------------------------------------------------------|
| `sensor_readings`        | *(from Chapter 8)* 9,648,000 partitioned sensor readings, Feb–Dec 2024 |
| `mv_sensor_daily`         | *(built in this chapter)* one row per day per sensor type              |
| `mv_sensor_monthly`       | *(built in this chapter)* `mv_sensor_daily` rolled up one level further |
| `matview_refresh_log`     | *(built in this chapter)* tracks when each matview was last refreshed  |

---

## Exercise Goals

By the end of this chapter you will be able to:

- Create a materialized view, understand `WITH DATA` vs. `WITH NO DATA`,
  and explain why querying an unpopulated one raises an error instead of
  silently returning nothing.
- Measure, with real `EXPLAIN ANALYZE` numbers, exactly what a
  materialized view saves compared to the raw aggregate it replaces.
- Add the unique index `REFRESH MATERIALIZED VIEW CONCURRENTLY` requires,
  and prove — with two open sessions — what it actually buys you over a
  plain `REFRESH`.
- Automate a refresh on a schedule, and know when to reach for that
  approach versus Chapter 19's `pg_cron`.
- Chain one materialized view off another, and see firsthand that
  refreshing the base view does **not** cascade to the one built on top
  of it.
- Detect a stale materialized view — after discovering that
  `pg_matviews`, PostgreSQL's own catalog for the object, has no column
  that tells you when one was last refreshed.

---

## Installation

Nothing to install. `CREATE MATERIALIZED VIEW` and `REFRESH MATERIALIZED
VIEW` have been part of core PostgreSQL since version 9.3. This chapter
uses no extensions.

---

## Loading the Data

This chapter doesn't seed new data — it builds directly on the
`sensor_readings` table Chapter 8 left behind. That matters for two
specific reasons, both consequences of exercises Chapter 8 already ran:

1. **January 2024 is gone.** Chapter 8, Exercise 5 dropped
   `sensor_readings_2024_01` on purpose, to demonstrate instant partition
   drop. `sensor_readings` now covers February through December 2024
   only.
2. **Sensor 17 has a year-late tail.** 1,152 of its temperature readings
   are timestamped in late December **2025**, not 2024 — a deliberate
   clock-drift bug from Chapter 8, sitting in `sensor_readings_default`.
   Nothing in this chapter removes them, and Exercise 5 runs directly
   into why that matters for a rollup.

If you're picking this chapter up in the same database you used for
Chapter 8, you already have everything you need. If not, run Chapter 8's
seed script and its exercises through at least Exercise 5 first — this
chapter assumes that exact end state, anomalies included.

### Pin the session timezone

```sql
SET timezone = 'UTC';
```

Same reason as Chapter 8: date boundaries in this chapter's `GROUP BY`
clauses are computed with `date_trunc`, which resolves relative to the
session timezone. Run every example here in a UTC session.

### Verify you're starting from the expected state

```sql
SELECT tableoid::regclass AS partition, COUNT(*)
FROM   sensor_readings
GROUP  BY tableoid
ORDER  BY 1;
```

```
        partition        |  count
--------------------------+---------
 sensor_readings_2024_02 |  835200
 sensor_readings_2024_03 |  892800
 sensor_readings_2024_04 |  864000
 sensor_readings_2024_05 |  892800
 sensor_readings_2024_06 |  864000
 sensor_readings_2024_07 |  892800
 sensor_readings_2024_08 |  892800
 sensor_readings_2024_09 |  864000
 sensor_readings_2024_10 |  892800
 sensor_readings_2024_11 |  864000
 sensor_readings_2024_12 |  891648
 sensor_readings_default |    1152
(12 rows)
```

Twelve partitions (no January), summing to 9,648,000 rows. If your counts
match, proceed.

---

## Exercises

---

### Exercise 1 — Creating a Daily Rollup

**1.1 — Build the materialized view**

```sql
CREATE MATERIALIZED VIEW mv_sensor_daily AS
SELECT
    date_trunc('day', recorded_at)::date AS reading_day,
    sensor_type,
    COUNT(*)                                  AS reading_count,
    round(AVG(reading_value)::numeric, 2)     AS avg_value,
    round(MIN(reading_value)::numeric, 2)     AS min_value,
    round(MAX(reading_value)::numeric, 2)     AS max_value
FROM   sensor_readings
GROUP  BY 1, 2
WITH DATA;
```

```
SELECT 1010
Time: 6821.437 ms (00:06.821)
```

Syntactically this is `CREATE TABLE AS` with a memory: the `SELECT` that
built it is stored alongside the data, which is what makes `REFRESH`
possible later. `WITH DATA` (the default) runs the query immediately and
populates the view. 1,010 rows is 335 days × 3 sensor types (February
through December 2024) plus 5 extra rows for sensor 17's stray December
**2025** dates — already visible in the row count, before you've even
looked at the data.

**1.2 — `WITH NO DATA`, and the error it sets up**

```sql
CREATE MATERIALIZED VIEW mv_sensor_daily_empty AS
SELECT date_trunc('day', recorded_at)::date AS reading_day, sensor_type, COUNT(*)
FROM   sensor_readings
GROUP  BY 1, 2
WITH NO DATA;

SELECT * FROM mv_sensor_daily_empty LIMIT 1;
```

```
CREATE MATERIALIZED VIEW
Time: 8.213 ms
ERROR:  materialized view "mv_sensor_daily_empty" has not been populated
HINT:  Use the REFRESH MATERIALIZED VIEW command.
```

`WITH NO DATA` creates the object and remembers its definition instantly
— useful when you want the structure to exist (so other DDL can
reference it) without paying the query cost yet — but leaves it in a
state where reading from it is an error, not an empty result set.
`pg_matviews.ispopulated` tracks exactly this:

```sql
SELECT matviewname, ispopulated FROM pg_matviews ORDER BY matviewname;
```

```
      matviewname       | ispopulated
-------------------------+-------------
 mv_sensor_daily         | t
 mv_sensor_daily_empty   | f
(2 rows)
```

```sql
DROP MATERIALIZED VIEW mv_sensor_daily_empty;
```

That was only to show the error — it isn't needed going forward.

**1.3 — Confirm it's a real table**

```sql
SELECT pg_size_pretty(pg_total_relation_size('mv_sensor_daily'));
```

```
 pg_size_pretty
----------------
 96 kB
```

1,010 rows of six columns, versus 9.6 million raw rows the query
underneath it scanned to produce them. That size difference is the whole
point, and Exercise 2 puts a number on what it means for query time.

---

### Exercise 2 — Matview vs. Raw Aggregate, Measured

**2.1 — Time the raw aggregate**

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT date_trunc('day', recorded_at)::date AS reading_day,
       sensor_type,
       COUNT(*)                              AS reading_count,
       round(AVG(reading_value)::numeric, 2) AS avg_value
FROM   sensor_readings
GROUP  BY 1, 2;
```

```
 Finalize HashAggregate  (cost=201448.99..201459.09 rows=1010 width=44) (actual time=693.128..701.845 rows=1010 loops=1)
   Group Key: (date_trunc('day'::text, recorded_at))::date, sensor_type
   Batches: 1  Memory Usage: 217kB
   Buffers: shared hit=612 read=71104
   ->  Gather  (cost=198328.11..201418.99 rows=3030 width=44) (actual time=210.442..688.910 rows=3030 loops=1)
         Workers Planned: 2
         Workers Launched: 2
         ->  Partial HashAggregate  (cost=197328.11..197359.21 rows=1010 width=44) (actual time=195.223..637.560 rows=1010 loops=3)
               Group Key: (date_trunc('day'::text, recorded_at))::date, sensor_type
               Batches: 1  Memory Usage: 217kB
               ->  Parallel Append  (cost=0.00..185004.00 rows=4022667 width=16) (actual time=0.028..312.744 rows=3216000 loops=3)
                     ->  Parallel Seq Scan on sensor_readings_2024_02 sensor_readings_1  ... (actual time=0.031..24.402 rows=278400 loops=1)
                     ->  Parallel Seq Scan on sensor_readings_2024_03 sensor_readings_2  ... (actual time=0.019..25.988 rows=297600 loops=1)
                     ->  Parallel Seq Scan on sensor_readings_2024_04 sensor_readings_3  ... (actual time=0.022..24.104 rows=288000 loops=1)
                     ->  Parallel Seq Scan on sensor_readings_2024_05 sensor_readings_4  ... (actual time=0.020..25.771 rows=297600 loops=1)
                     ->  Parallel Seq Scan on sensor_readings_2024_06 sensor_readings_5  ... (actual time=0.021..23.955 rows=288000 loops=1)
                     ->  Parallel Seq Scan on sensor_readings_2024_07 sensor_readings_6  ... (actual time=0.018..25.812 rows=297600 loops=1)
                     ->  Parallel Seq Scan on sensor_readings_2024_08 sensor_readings_7  ... (actual time=0.024..25.769 rows=297600 loops=1)
                     ->  Parallel Seq Scan on sensor_readings_2024_09 sensor_readings_8  ... (actual time=0.017..23.930 rows=288000 loops=1)
                     ->  Parallel Seq Scan on sensor_readings_2024_10 sensor_readings_9  ... (actual time=0.021..25.797 rows=297600 loops=1)
                     ->  Parallel Seq Scan on sensor_readings_2024_11 sensor_readings_10 ... (actual time=0.019..23.947 rows=288000 loops=1)
                     ->  Parallel Seq Scan on sensor_readings_2024_12 sensor_readings_11 ... (actual time=0.023..25.744 rows=297216 loops=1)
                     ->  Parallel Seq Scan on sensor_readings_default sensor_readings_12 ... (actual time=0.008..0.301 rows=384 loops=1)
 Planning Time: 3.912 ms
 Execution Time: 703.187 ms
```

Every partition shows up — this query has no `WHERE` clause, so nothing
gets pruned, exactly as Chapter 8, Exercise 3.2 predicted. It still
finishes in under a second, thanks to partition-parallel `HashAggregate`,
but that's 703 ms paid **every time** someone asks this question.

**2.2 — Time the same question against the matview**

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT reading_day, sensor_type, reading_count, avg_value
FROM   mv_sensor_daily
WHERE  reading_day >= '2024-06-01' AND reading_day < '2024-07-01'
ORDER  BY reading_day, sensor_type;
```

```
 Sort  (cost=8.51..8.74 rows=90 width=44) (actual time=0.041..0.043 rows=90 loops=1)
   Sort Key: reading_day, sensor_type
   Sort Method: quicksort  Memory: 32kB
   Buffers: shared hit=3
   ->  Index Scan using idx_mv_sensor_daily_day_type on mv_sensor_daily  (cost=0.28..5.61 rows=90 width=44) (actual time=0.014..0.028 rows=90 loops=1)
         Index Cond: ((reading_day >= '2024-06-01'::date) AND (reading_day < '2024-07-01'::date))
 Planning Time: 0.187 ms
 Execution Time: 0.061 ms
```

(This uses the unique index built in Exercise 3 — build it first if
you're running this out of order.) 0.061 ms against 703 ms is roughly
**11,500 times faster**, and the gap only widens as `sensor_readings`
grows: the matview query's cost is a function of how many days you ask
for, not how many raw rows exist behind them. That's the entire value
proposition of this chapter in one comparison.

---

### Exercise 3 — Concurrent Refresh and What It Actually Buys You

**3.1 — Add the unique index `CONCURRENTLY` requires**

```sql
CREATE UNIQUE INDEX idx_mv_sensor_daily_day_type
    ON mv_sensor_daily (reading_day, sensor_type);
```

```
CREATE INDEX
Time: 12.847 ms
```

`REFRESH MATERIALIZED VIEW CONCURRENTLY` needs a unique index covering
every row, with no `WHERE` clause and no non-immutable expressions — it's
what PostgreSQL uses to diff the old contents against the new ones row by
row instead of throwing everything away and starting over. Without one,
`CONCURRENTLY` simply refuses to run:

```sql
-- hypothetically, before 3.1's index exists:
-- ERROR:  cannot refresh materialized view "mv_sensor_daily" concurrently
-- HINT:  Create a unique index with no WHERE clause on one or more columns of the materialized view.
```

**3.2 — Watch a plain `REFRESH` block a reader**

Open two `psql` sessions. In **Session A**, start a read and leave the
transaction open:

```sql
-- Session A
BEGIN;
SELECT reading_day, sensor_type, avg_value
FROM   mv_sensor_daily
WHERE  sensor_type = 'traffic'
ORDER  BY reading_day
LIMIT  5;
```

That `SELECT` returns instantly, but the open transaction holds an
`ACCESS SHARE` lock on `mv_sensor_daily` until it commits. In **Session
B**, run a plain refresh:

```sql
-- Session B (Session A's transaction is still open)
REFRESH MATERIALIZED VIEW mv_sensor_daily;
```

Session B does not return. A third session shows why:

```sql
-- Session C, while B is blocked
SELECT pid, mode, granted
FROM   pg_locks
WHERE  relation = 'mv_sensor_daily'::regclass;
```

```
  pid  |         mode          | granted
-------+------------------------+---------
 41822 | AccessShareLock        | t
 41960 | AccessExclusiveLock    | f
(2 rows)
```

A plain `REFRESH` needs `ACCESS EXCLUSIVE` — the strictest lock
PostgreSQL has, compatible with nothing, not even another reader's
`ACCESS SHARE`. It queues up and waits. Commit Session A and Session B
completes immediately:

```sql
-- Session A
COMMIT;
```

```
-- Session B, unblocks right after A's COMMIT
REFRESH MATERIALIZED VIEW
Time: 9482.311 ms (00:09.482)
```

That 9.48 seconds is mostly wait time — the actual rebuild of a
1,010-row view takes a fraction of that. From Session B's side, it's
indistinguishable from a slow refresh; from Session A's side, every
query against `mv_sensor_daily` that started after B's `REFRESH` was
queued up behind it too.

**3.3 — Same setup, `CONCURRENTLY` instead**

Repeat 3.2, Session A holding the same open `BEGIN; SELECT ...`
transaction. This time, Session B runs:

```sql
-- Session B
REFRESH MATERIALIZED VIEW CONCURRENTLY mv_sensor_daily;
```

```
REFRESH MATERIALIZED VIEW
Time: 421.933 ms
```

<img src="imgs/ch09_refresh_lock.svg" alt="Sequence diagram: with a plain REFRESH, Session B blocks waiting for Session A's AccessShareLock to release because REFRESH needs an AccessExclusiveLock; with REFRESH CONCURRENTLY, Session B's ExclusiveLock is compatible with Session A's AccessShareLock, so neither session blocks"/>

No wait, despite Session A's transaction still being open. `CONCURRENTLY`
takes an `EXCLUSIVE` lock rather than `ACCESS EXCLUSIVE` — one step down
— and `EXCLUSIVE` is the one lock mode in PostgreSQL that does **not**
conflict with `ACCESS SHARE`. Readers keep reading the pre-refresh
contents right up until the new data is merged in; nobody blocks, and
nobody sees a half-updated table either. The trade for that is real
extra work: instead of one clean table rewrite, PostgreSQL builds the new
result set in a temporary table, diffs it row-by-row against the old one
using the unique index from 3.1, and issues targeted `INSERT`/`UPDATE`/
`DELETE`s for just the rows that changed — 421 ms of real work here
against what a plain rewrite of the same 1,010 rows would cost in the
tens of milliseconds. For a small rollup like this one, that overhead is
noise. For a materialized view with tens of millions of rows, it stops
being noise, and "does anyone need to read this while it refreshes"
becomes the question that decides which `REFRESH` variant you reach for.

---

### Exercise 4 — Automating the Refresh

**4.1 — A refresh script**

```bash
#!/usr/bin/env bash
# refresh_daily.sh — nightly rollup refresh
psql -d portsmith -c "REFRESH MATERIALIZED VIEW CONCURRENTLY mv_sensor_daily;"
```

```bash
chmod +x refresh_daily.sh
./refresh_daily.sh
```

```
REFRESH MATERIALIZED VIEW
```

**4.2 — Schedule it with OS-level cron**

```bash
crontab -e
```

```
0 2 * * * /home/chris/portsmith/refresh_daily.sh >> /var/log/portsmith_matview_refresh.log 2>&1
```

Every night at 02:00, outside business hours, the rollup catches up on
whatever landed in `sensor_readings` during the day.

**4.3 — Why this is the "poor man's" version**

This works, but it has the usual problems of anything scheduled outside
the database: it depends on a specific machine's crontab existing and
being correct, its failures show up in a log file nobody's watching
instead of a table you can query, and nothing stops two overlapping runs
if a refresh ever takes longer than the interval between them. Chapter
19 covers `pg_cron`, which runs scheduled jobs *inside* PostgreSQL
itself — schedule tracked in a table, run history queryable with SQL,
overlap prevention available via the same advisory locks Chapter 14
covers. Everything from here forward in this chapter still works with
either approach; Exercise 6 revisits this exact script once there's
something better than a raw `REFRESH` worth putting in it.

---

### Exercise 5 — Chaining Rollups: Daily Feeds Monthly

**5.1 — Build the monthly view from the daily one, not from raw data**

```sql
CREATE MATERIALIZED VIEW mv_sensor_monthly AS
SELECT
    date_trunc('month', reading_day)::date AS reading_month,
    sensor_type,
    SUM(reading_count)                                          AS reading_count,
    round((SUM(avg_value * reading_count) / SUM(reading_count))::numeric, 2) AS avg_value,
    round(MIN(min_value)::numeric, 2)                           AS min_value,
    round(MAX(max_value)::numeric, 2)                           AS max_value
FROM   mv_sensor_daily
GROUP  BY 1, 2
WITH DATA;

CREATE UNIQUE INDEX idx_mv_sensor_monthly_month_type
    ON mv_sensor_monthly (reading_month, sensor_type);
```

```
SELECT 34
Time: 41.209 ms
```

Two things worth noticing before moving on. First, `avg_value` is
computed as `SUM(avg_value * reading_count) / SUM(reading_count)` — a
**weighted** average — not `AVG(avg_value)`. A plain average of 28 or 31
daily averages silently assumes every day carries equal weight, which
is wrong the moment days have different reading counts (they do here,
since `sensor_readings_2024_12` has fewer temperature readings than a
full month — 1,152 of sensor 17's got shifted out of it, straight into
the anomaly the next step finds). Second, building `mv_sensor_monthly`
`FROM mv_sensor_daily` instead of `FROM sensor_readings` means its
refresh cost is a function of 1,010 pre-aggregated rows, not 9.6 million
raw ones — a materialized view chain is allowed to build on another
materialized view exactly like a regular view can.

**5.2 — The row that shouldn't be there**

```sql
SELECT reading_month, sensor_type, reading_count, avg_value
FROM   mv_sensor_monthly
ORDER  BY reading_month DESC, sensor_type
LIMIT  3;
```

```
 reading_month | sensor_type | reading_count | avg_value
---------------+-------------+---------------+-----------
 2025-12-01    | temperature |          1152 |     29.84
 2024-12-01    | air_quality |         89280 |     34.51
 2024-12-01    | temperature |        445248 |     41.02
(3 rows)
```

A `2025-12-01` row, for one sensor type only, with a suspiciously round
1,152-row count. This is Chapter 8's sensor-17 clock bug, now one layer
removed from where it was first found: it landed in `sensor_readings`,
propagated automatically into `mv_sensor_daily` as five stray 2025 dates,
and propagated automatically again into `mv_sensor_monthly` as a whole
extra month that shouldn't exist on Portsmith's 2024 dashboard. A
materialized view has no opinion about the quality of the data it
summarizes — it faithfully aggregates whatever is in the base table,
bad timestamps included, which is exactly why Chapter 8 flagged this
row as worth checking for in every chapter that touches
`sensor_readings` downstream. Any dashboard query built on
`mv_sensor_monthly` should filter to the expected year explicitly
(`WHERE reading_month >= '2024-01-01' AND reading_month < '2025-01-01'`)
rather than assume the view only ever contains what it was "supposed" to.

<img src="imgs/ch09_matview_pipeline.svg" alt="Pipeline diagram: sensor_readings feeds mv_sensor_daily via GROUP BY day and type, which feeds mv_sensor_monthly via GROUP BY month and type; sensor 17's bad 2025 rows flow through both stages unfiltered, ending in a spurious 2025-12 row in mv_sensor_monthly; refreshing mv_sensor_daily does not automatically cascade to mv_sensor_monthly, which must be refreshed as an explicit second step"/>

**5.3 — Prove refreshes don't cascade**

Simulate a late-arriving reading — a traffic sensor that reported an
hour behind schedule:

```sql
INSERT INTO sensor_readings (sensor_id, sensor_type, reading_value, recorded_at)
VALUES (51, 'traffic', 99, '2024-06-15 12:00:00+00');
```

```sql
REFRESH MATERIALIZED VIEW CONCURRENTLY mv_sensor_daily;

SELECT reading_count FROM mv_sensor_daily
WHERE  reading_day = '2024-06-15' AND sensor_type = 'traffic';
```

```
 reading_count
---------------
         11521
```

`mv_sensor_daily` sees the new row — up from the usual 11,520. Now check
the monthly view, without refreshing it:

```sql
SELECT reading_count FROM mv_sensor_monthly
WHERE  reading_month = '2024-06-01' AND sensor_type = 'traffic';
```

```
 reading_count
---------------
         345600
```

Still the old total. `mv_sensor_monthly`'s definition says `FROM
mv_sensor_daily`, but PostgreSQL doesn't track that dependency the way
it tracks, say, a foreign key — refreshing one materialized view never
triggers a refresh of anything built on top of it. It has to be done in
order, explicitly:

```sql
REFRESH MATERIALIZED VIEW CONCURRENTLY mv_sensor_monthly;

SELECT reading_count FROM mv_sensor_monthly
WHERE  reading_month = '2024-06-01' AND sensor_type = 'traffic';
```

```
 reading_count
---------------
         345601
```

Now it matches. Any refresh job for a chain of materialized views has to
encode this ordering itself — daily before monthly, and so on up the
chain — because PostgreSQL won't infer it from the `FROM` clause on your
behalf.

---

### Exercise 6 — Detecting Staleness (Without a Column That Doesn't Exist)

**6.1 — Check what `pg_matviews` actually tracks**

It's tempting to assume the catalog that lists materialized views also
records when each one was last refreshed. Check directly:

```sql
\d pg_matviews
```

```
                View "pg_catalog.pg_matviews"
    Column    | Type | Collation | Nullable | Default
--------------+------+-----------+----------+---------
 schemaname   | name |           |          |
 matviewname  | name |           |          |
 matviewowner | name |           |          |
 tablespace   | name |           |          |
 hasindexes   | boolean |        |          |
 ispopulated  | boolean |        |          |
 definition   | text |           |          |
```

No timestamp, anywhere. `ispopulated` tells you whether a `WITH NO DATA`
view has ever been refreshed at all — a one-time boolean, not a "how
recent" answer. PostgreSQL genuinely does not track refresh recency for
materialized views; anything resembling "this view is N hours stale" has
to be built by hand.

**6.2 — Build the tracking table and a helper to keep it honest**

```sql
CREATE TABLE matview_refresh_log (
    matview_name TEXT PRIMARY KEY,
    refreshed_at TIMESTAMPTZ NOT NULL
);

CREATE OR REPLACE PROCEDURE refresh_and_log(p_matview regclass)
LANGUAGE plpgsql AS $$
BEGIN
    EXECUTE format('REFRESH MATERIALIZED VIEW CONCURRENTLY %s', p_matview);
    INSERT INTO matview_refresh_log (matview_name, refreshed_at)
    VALUES (p_matview::text, clock_timestamp())
    ON CONFLICT (matview_name) DO UPDATE SET refreshed_at = EXCLUDED.refreshed_at;
END;
$$;
```

`clock_timestamp()` rather than `now()` — `now()` is fixed for the whole
transaction, and a `CALL` to a procedure runs as one, so `now()` would
log the moment the procedure *started*, not the moment the `REFRESH`
inside it actually finished.

**6.3 — Refresh both views through the tracked path**

```sql
CALL refresh_and_log('mv_sensor_daily');
CALL refresh_and_log('mv_sensor_monthly');
```

```
CALL
CALL
```

**6.4 — The staleness query**

```sql
SELECT m.matviewname,
       l.refreshed_at,
       now() - l.refreshed_at AS age,
       CASE
           WHEN l.refreshed_at IS NULL              THEN 'NEVER REFRESHED (untracked)'
           WHEN now() - l.refreshed_at > interval '25 hours' THEN 'STALE'
           ELSE 'OK'
       END AS status
FROM   pg_matviews m
LEFT JOIN matview_refresh_log l ON l.matview_name = m.matviewname
WHERE  m.schemaname = 'public'
ORDER  BY m.matviewname;
```

```
   matviewname     |          refreshed_at         |      age      | status
--------------------+--------------------------------+----------------+--------
 mv_sensor_daily    | 2026-08-02 09:14:02.881204+00 | 00:00:04.113   | OK
 mv_sensor_monthly  | 2026-08-02 09:14:03.019552+00 | 00:00:03.975   | OK
(2 rows)
```

The `LEFT JOIN` matters: a materialized view that was created or
refreshed by hand — bypassing `refresh_and_log` entirely — shows up with
a `NULL` `refreshed_at` and the honest verdict "untracked," rather than
silently vanishing from the report or falsely reading as fresh. A 25-hour
threshold gives a nightly job a few hours of slack before it counts as
missed; adjust it to whatever your actual refresh cadence is.

**6.5 — Wire this back into Exercise 4's cron job**

```bash
#!/usr/bin/env bash
# refresh_daily.sh — nightly rollup refresh, now logged
psql -d portsmith -c "CALL refresh_and_log('mv_sensor_daily');"
psql -d portsmith -c "CALL refresh_and_log('mv_sensor_monthly');"
```

Same crontab entry from 4.2, same 02:00 schedule — but now a missed or
failed run is something the staleness query in 6.4 can actually catch,
instead of something that only shows up when someone notices the
dashboard looks wrong.

---

## Summary — What You Should Now Know

| Tool | What it does |
|------|---------------|
| `CREATE MATERIALIZED VIEW ... AS SELECT ...` | Runs a query once and stores the result as a real, indexable table |
| `WITH DATA` / `WITH NO DATA` | Populate immediately, or defer — an unpopulated view errors on `SELECT` until refreshed |
| `pg_matviews.ispopulated` | Whether a view has ever been refreshed — a one-time flag, not a timestamp |
| `REFRESH MATERIALIZED VIEW` | Full rewrite under an `ACCESS EXCLUSIVE` lock — blocks and is blocked by every reader |
| `REFRESH MATERIALIZED VIEW CONCURRENTLY` | Diff-based refresh under an `EXCLUSIVE` lock — doesn't block readers, but requires a unique index and costs more CPU/IO |
| Matview chaining (`FROM` another matview) | Legal and useful for cheap incremental rollups, but refreshes never cascade automatically |
| `matview_refresh_log` + `refresh_and_log()` | The hand-built pattern for tracking refresh recency, since PostgreSQL doesn't track it natively |

**The key design insight** from this chapter is that a materialized view
moves cost, it doesn't remove it — every millisecond Exercise 2 shaved
off read time was paid for up front, at refresh time, and the entire
rest of the chapter is really about where that payment lands. A plain
`REFRESH` pays it in a lock that every reader waits behind.
`CONCURRENTLY` pays it in extra diff work instead, in exchange for
readers never noticing a refresh happened. A chain of matviews pays it
once per level, in a specific order you have to enforce yourself. And a
matview that quietly inherits bad data from its source — as
`mv_sensor_monthly` did from sensor 17's clock bug — pays it in trust,
which is the one cost this chapter's tooling can't refresh away for you.

---

*Going further: `sensor_readings` still has more to give. Chapter 11's
window functions compute rolling averages and day-over-day deltas
directly against the raw partitioned table — a different tool for a
similar-sounding problem, worth contrasting with this chapter's
precomputed rollups once you've seen both. Chapter 16 adds a generated
`reading_date` column to `sensor_readings` itself, which would let
`mv_sensor_daily`'s `GROUP BY` key come from a stored column instead of
a `date_trunc` expression — a small efficiency this chapter left on the
table on purpose, to keep the expression-vs-generated-column comparison
intact for that chapter instead of pre-empting it here. Chapter 19 is
where the OS-cron approach from Exercise 4 gets replaced with the
in-database version, `cron.job_run_details` doing for schedule history
what `matview_refresh_log` did by hand in Exercise 6. And a caution
worth carrying forward: nothing in this chapter is *incremental*
materialized-view maintenance in the sense some other databases offer —
`REFRESH`, concurrent or not, always recomputes the full result set from
scratch each time; PostgreSQL just gives you two different ways to pay
for that recomputation. Extensions like `pg_ivm` exist specifically to
close that gap, keeping a matview updated row-by-row as its base tables
change instead of on a refresh schedule, but that's a different
trade-off than anything built here, and out of scope for this chapter.*
