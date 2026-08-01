# Chapter 8 — Declarative Partitioning and BRIN Indexes

> *"A table doesn't get slow because it's big. It gets slow because every
> query has to consider all of it — partitioning doesn't shrink the table,
> it shrinks the part any single query has to look at."*

---

## Background

Every chapter so far has reached for an extension — `pg_trgm`, `pgvector`,
`ip4r` — to get a data type or index PostgreSQL doesn't ship with. This
chapter is different: declarative partitioning (since PostgreSQL 10) and
BRIN indexes (since PostgreSQL 9.5) are both built-in core features. No
`CREATE EXTENSION` anywhere in this chapter. What they solve isn't "how do
I store this," it's "how do I keep a table that never stops growing from
turning every query, every index, and every maintenance operation into a
scan of everything that has ever happened."

**Partitioning** splits one logical table into many physical ones, each
holding a slice of the rows — by date range, by category, by hash — while
every query still just says `SELECT ... FROM sensor_readings`. The
planner decides, before it reads a single row, which physical partitions
could possibly contain a match and skips the rest entirely. That's
**partition pruning**, and it's the entire value proposition: a query
asking for one month of data out of a year doesn't pay for the other
eleven months, not even to rule them out.

**BRIN** (Block Range INdex) is a different kind of index for a specific
shape of data: values that are large in volume but naturally correlated
with physical storage order. A B-tree index stores an entry for every
single row and costs roughly proportional to the row count. A BRIN index
stores one small summary — just a min and max — per range of physical
disk pages (128 pages by default), and costs almost nothing regardless of
how many rows are in the table. The catch, and it's a real one: BRIN only
helps if physical order and value order actually correlate. For a table
where rows are inserted in timestamp order and essentially never updated
— exactly what an append-only sensor log looks like — the correlation is
close to perfect, and that's the case this chapter builds.

---

## The Scenario

Portsmith has quietly wired up 120 sensors across the city — temperature
sensors, traffic counters, and air quality monitors — all reporting on a
schedule, all day, every day. A year of this is over ten million rows,
and it only grows. The data starts life the way most time-series data
actually starts: as one plain, unpartitioned table, because nobody
provisions a partitioning scheme before they have a problem. This chapter
is that problem arriving, and fixing it.

| Table                       | Purpose                                                                 |
|------------------------------|--------------------------------------------------------------------------|
| `sensors`                    | Metadata for all 120 sensors — type, label, neighborhood/street          |
| `sensor_readings_staging`    | ~10.5 million raw readings for 2024, as one unpartitioned table          |
| `sensor_readings`            | *(built in this chapter)* the same data, partitioned by month            |
| `sensor_readings_by_type`    | *(built in this chapter)* a second copy, partitioned by type *and* month |

`sensor_readings_staging` is the state the data starts in. Building
`sensor_readings` from it — deciding the scheme, creating the partitions,
backfilling — is the exercise, not something handed to you already done.

---

## Exercise Goals

By the end of this chapter you will be able to:

- Design and create a range-partitioned table, and understand why the
  partition key has to be chosen before the first row is loaded, not
  after.
- Backfill a partitioned table from an existing unpartitioned one and
  confirm that PostgreSQL routes every row to the correct partition
  automatically.
- Read an `EXPLAIN` plan well enough to tell the difference between a
  query that touches one partition and one that touches all of them.
- Build a BRIN index and explain, using real numbers, why it can be
  hundreds of times smaller than a B-tree on the same column — and what
  it gives up to get there.
- Drop a month of data in milliseconds via `DROP TABLE` on a partition,
  and see exactly what that avoids compared to `DELETE` on an
  unpartitioned table.
- Combine two partitioning strategies — `LIST` over `RANGE` — into one
  table, and confirm the planner prunes on *both* dimensions at once.

---

## Installation

Nothing to install. `PARTITION BY` and `USING BRIN` are both part of core
PostgreSQL — if `psql --version` says 10 or later for partitioning, or
9.5 or later for BRIN, you already have everything this chapter uses.
(The Portsmith cluster is PostgreSQL 16, well past both.)

---

## Loading the Data

### Run the seed script

```bash
python data/ch08_seed.py
```

Expected output (the exact seconds will vary with your machine; the row
counts will not):

```
Connecting to: dbname=portsmith
Creating schema …
Inserting 120 sensors …
Generating and loading readings (this takes a few minutes) …
  generated January 2024 — 892,800 rows
  generated February 2024 — 835,200 rows
  generated March 2024 — 892,800 rows
  generated April 2024 — 864,000 rows
  generated May 2024 — 892,800 rows
  generated June 2024 — 864,000 rows
  generated July 2024 — 892,800 rows
  generated August 2024 — 892,800 rows
  generated September 2024 — 864,000 rows
  generated October 2024 — 892,800 rows
  generated November 2024 — 864,000 rows
  generated December 2024 — 892,800 rows
Indexing staging table on recorded_at (mirrors a typical pre-partitioning table) …
Done — 10,540,800 rows in sensor_readings_staging (131.3s to generate + load), 120 sensors.
```

Months vary in row count because February is shorter and because
temperature/traffic sensors report every 5 minutes while air quality
sensors report every 15 — not a bug, just three sensor types on three
different schedules, same as a real deployment would have.

### Pin the session timezone before you do anything else

```sql
SET timezone = 'UTC';
```

This matters more than it looks like it should. `TIMESTAMPTZ` values are
stored as absolute instants, but a bound like `'2024-01-01'` in a
`CREATE TABLE ... PARTITION OF ... FOR VALUES FROM (...)` clause gets
interpreted relative to the session's timezone *at the moment the
partition is created*. Two people creating "the same" January partition
in two different session timezones will get two different absolute
boundaries. Run every example in this chapter in a UTC session — this
`SET` at the top of each `psql` session is enough — and the partition
boundaries and the displayed timestamps will both match what's printed
below exactly.

### Verify the load

**Check 1 — the metadata table:**

```sql
\d sensors
```

```
                 Table "public.sensors"
    Column    |  Type   | Collation | Nullable | Default
--------------+---------+-----------+----------+---------
 id           | integer |           | not null |
 sensor_type  | text    |           | not null |
 label        | text    |           | not null |
 neighborhood | text    |           | not null |
Indexes:
    "sensors_pkey" PRIMARY KEY, btree (id)
Check constraints:
    "sensors_sensor_type_check" CHECK (sensor_type = ANY (ARRAY['temperature'::text, 'traffic'::text, 'air_quality'::text]))
Referenced by:
    TABLE "sensor_readings_staging" CONSTRAINT "sensor_readings_staging_sensor_id_fkey" FOREIGN KEY (sensor_id) REFERENCES sensors(id)
```

**Check 2 — the staging table structure:**

```sql
\d sensor_readings_staging
```

```
                             Table "public.sensor_readings_staging"
    Column     |           Type           | Collation | Nullable |           Default
---------------+--------------------------+-----------+----------+------------------------------
 id            | bigint                   |           | not null | generated always as identity
 sensor_id     | integer                  |           | not null |
 sensor_type   | text                     |           | not null |
 reading_value | double precision         |           | not null |
 recorded_at   | timestamp with time zone |           | not null |
Indexes:
    "idx_sensor_readings_staging_recorded_at" btree (recorded_at)
Check constraints:
    "sensor_readings_staging_sensor_type_check" CHECK (sensor_type = ANY (ARRAY['temperature'::text, 'traffic'::text, 'air_quality'::text]))
Foreign-key constraints:
    "sensor_readings_staging_sensor_id_fkey" FOREIGN KEY (sensor_id) REFERENCES sensors(id)
```

Note this table already has a B-tree index on `recorded_at` — a
perfectly ordinary choice for "the column I filter on," and exactly what
a lot of real unpartitioned time-series tables look like right up until
someone asks why disk usage keeps climbing.

**Check 3 — sensor and reading counts by type:**

```sql
SELECT sensor_type, COUNT(*) FROM sensors GROUP BY sensor_type ORDER BY sensor_type;
```

```
 sensor_type | count
-------------+-------
 air_quality |    30
 temperature |    50
 traffic     |    40
(3 rows)
```

```sql
SELECT sensor_type, COUNT(*) FROM sensor_readings_staging GROUP BY sensor_type ORDER BY sensor_type;
```

```
 sensor_type |  count
-------------+---------
 air_quality | 1054080
 temperature | 5270400
 traffic     | 4216320
(3 rows)
```

If these match, proceed to the exercises.

---

## Exercises

---

### Exercise 1 — Designing and Creating the Partitioned Table

**1.1 — Choose the partition key up front**

Partitioning isn't something you bolt onto an existing table — `PARTITION
BY` is part of `CREATE TABLE` and can't be added with `ALTER TABLE`
afterward. That means the decision has to be made before a single row is
loaded into the partitioned structure, based on how the table will
actually be queried. `sensor_readings` is queried almost exclusively by
time range ("show me last week," "roll up by month"), so `RANGE
(recorded_at)`, monthly, is the natural key — coarse enough to keep the
partition count manageable, fine enough that most queries touch only one
or two partitions.

**1.2 — Create the partitioned table and its monthly partitions**

```sql
CREATE TABLE sensor_readings (
    id            BIGINT GENERATED ALWAYS AS IDENTITY,
    sensor_id     INTEGER NOT NULL REFERENCES sensors(id),
    sensor_type   TEXT NOT NULL
                      CHECK (sensor_type IN ('temperature', 'traffic', 'air_quality')),
    reading_value DOUBLE PRECISION NOT NULL,
    recorded_at   TIMESTAMPTZ NOT NULL
) PARTITION BY RANGE (recorded_at);

CREATE TABLE sensor_readings_2024_01 PARTITION OF sensor_readings FOR VALUES FROM ('2024-01-01') TO ('2024-02-01');
CREATE TABLE sensor_readings_2024_02 PARTITION OF sensor_readings FOR VALUES FROM ('2024-02-01') TO ('2024-03-01');
CREATE TABLE sensor_readings_2024_03 PARTITION OF sensor_readings FOR VALUES FROM ('2024-03-01') TO ('2024-04-01');
CREATE TABLE sensor_readings_2024_04 PARTITION OF sensor_readings FOR VALUES FROM ('2024-04-01') TO ('2024-05-01');
CREATE TABLE sensor_readings_2024_05 PARTITION OF sensor_readings FOR VALUES FROM ('2024-05-01') TO ('2024-06-01');
CREATE TABLE sensor_readings_2024_06 PARTITION OF sensor_readings FOR VALUES FROM ('2024-06-01') TO ('2024-07-01');
CREATE TABLE sensor_readings_2024_07 PARTITION OF sensor_readings FOR VALUES FROM ('2024-07-01') TO ('2024-08-01');
CREATE TABLE sensor_readings_2024_08 PARTITION OF sensor_readings FOR VALUES FROM ('2024-08-01') TO ('2024-09-01');
CREATE TABLE sensor_readings_2024_09 PARTITION OF sensor_readings FOR VALUES FROM ('2024-09-01') TO ('2024-10-01');
CREATE TABLE sensor_readings_2024_10 PARTITION OF sensor_readings FOR VALUES FROM ('2024-10-01') TO ('2024-11-01');
CREATE TABLE sensor_readings_2024_11 PARTITION OF sensor_readings FOR VALUES FROM ('2024-11-01') TO ('2024-12-01');
CREATE TABLE sensor_readings_2024_12 PARTITION OF sensor_readings FOR VALUES FROM ('2024-12-01') TO ('2025-01-01');
CREATE TABLE sensor_readings_default PARTITION OF sensor_readings DEFAULT;
```

Each `FOR VALUES FROM (...) TO (...)` is a half-open interval — inclusive
of the lower bound, exclusive of the upper — so consecutive months tile
the year with no gap and no overlap. The last one,
`sensor_readings_default`, is not optional in any meaningful sense: without
it, any row whose `recorded_at` doesn't fall in one of the twelve defined
ranges is simply rejected at insert time. With it, such a row is accepted
and routed there instead — silently, unless you go looking. Exercise 2
finds a case where that's exactly what happens.

**1.3 — Confirm the structure**

```sql
\d sensor_readings
```

```
                           Partitioned table "public.sensor_readings"
    Column     |           Type           | Collation | Nullable |           Default
---------------+--------------------------+-----------+----------+------------------------------
 id            | bigint                   |           | not null | generated always as identity
 sensor_id     | integer                  |           | not null |
 sensor_type   | text                     |           | not null |
 reading_value | double precision         |           | not null |
 recorded_at   | timestamp with time zone |           | not null |
Partition key: RANGE (recorded_at)
Check constraints:
    "sensor_readings_sensor_type_check" CHECK (sensor_type = ANY (ARRAY['temperature'::text, 'traffic'::text, 'air_quality'::text]))
Foreign-key constraints:
    "sensor_readings_sensor_id_fkey" FOREIGN KEY (sensor_id) REFERENCES sensors(id)
Number of partitions: 13 (Use \d+ to list them.)
```

`sensor_readings` itself has no storage of its own — it's a routing
target. Every row you insert into it physically lands in exactly one of
the thirteen tables underneath.

---

### Exercise 2 — Backfilling and Watching Automatic Partition Routing

**2.1 — Backfill from staging**

```sql
INSERT INTO sensor_readings (sensor_id, sensor_type, reading_value, recorded_at)
SELECT sensor_id, sensor_type, reading_value, recorded_at
FROM   sensor_readings_staging;
```

```
INSERT 0 10540800
Time: 87814.162 ms (01:27.814)
```

One `INSERT ... SELECT`, no destination named beyond `sensor_readings`
itself — PostgreSQL evaluates each row's `recorded_at` against the
partition bounds and routes it to the matching child table. Nothing in
this statement says which of the thirteen tables any given row ends up
in.

**2.2 — Confirm the routing, per partition**

```sql
SELECT tableoid::regclass AS partition, COUNT(*)
FROM   sensor_readings
GROUP  BY tableoid
ORDER  BY 1;
```

```
        partition        | count
--------------------------+--------
 sensor_readings_2024_01 | 892800
 sensor_readings_2024_02 | 835200
 sensor_readings_2024_03 | 892800
 sensor_readings_2024_04 | 864000
 sensor_readings_2024_05 | 892800
 sensor_readings_2024_06 | 864000
 sensor_readings_2024_07 | 892800
 sensor_readings_2024_08 | 892800
 sensor_readings_2024_09 | 864000
 sensor_readings_2024_10 | 892800
 sensor_readings_2024_11 | 864000
 sensor_readings_2024_12 | 891648
 sensor_readings_default |   1152
(13 rows)
```

`tableoid` is a hidden system column every table has, and on a
partitioned table it tells you which physical partition a given row
actually lives in — the only reliable way to ask "where did this row
end up?" after the fact.

**2.3 — The row count that should stop you**

Every month has the row count you'd expect from Exercise 0's per-type
counts — except December, which is short exactly 1,152 rows, and
`sensor_readings_default`, which has exactly 1,152 rows in it. That's not
a coincidence:

```sql
SELECT sensor_id, MIN(recorded_at), MAX(recorded_at), COUNT(*)
FROM   sensor_readings
WHERE  tableoid = 'sensor_readings_default'::regclass
GROUP  BY sensor_id;
```

```
 sensor_id |          min           |          max           | count
-----------+-------------------------+-------------------------+-------
        17 | 2025-12-27 00:00:00+00 | 2025-12-31 23:55:00+00 |  1152
```

Sensor 17 — a temperature sensor — has a clock bug: for its last four
days of reporting, it stamped its readings a full year fast. Nothing
about the `INSERT` failed or warned; the rows are sitting exactly where
the schema said out-of-range data should go. This is precisely the
scenario a `DEFAULT` partition exists for, and precisely why "does the
default partition have anything in it?" is worth checking after any real
backfill, not just this synthetic one — it's the difference between a
sensor firmware bug you catch in five minutes and one you catch when
someone asks why a report is missing a device.

---

### Exercise 3 — Partition Pruning, Seen in `EXPLAIN`

**3.1 — A date-filtered query touches one partition**

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT sensor_type, COUNT(*), round(AVG(reading_value)::numeric, 2)
FROM   sensor_readings
WHERE  recorded_at >= '2024-06-01' AND recorded_at < '2024-07-01'
GROUP  BY sensor_type
ORDER  BY sensor_type;
```

```
 Finalize GroupAggregate  (cost=12411.99..12480.46 rows=200 width=72) (actual time=182.595..203.871 rows=3 loops=1)
   Group Key: sensor_readings.sensor_type
   Buffers: shared hit=106 read=7168, temp read=3264 written=3276
   ->  Gather Merge  (cost=12411.99..12473.96 rows=400 width=72) (actual time=152.757..203.835 rows=9 loops=1)
         Workers Planned: 2
         Workers Launched: 2
         ->  Partial GroupAggregate  (cost=11411.97..11427.77 rows=200 width=72) (actual time=98.794..149.785 rows=3 loops=3)
               Group Key: sensor_readings.sensor_type
               ->  Sort  (cost=11411.97..11415.42 rows=1380 width=40) (actual time=93.166..120.544 rows=288000 loops=3)
                     Sort Key: sensor_readings.sensor_type
                     Sort Method: external merge  Disk: 8720kB
                     ->  Parallel Seq Scan on sensor_readings_2024_06 sensor_readings  (cost=0.00..11340.00 rows=1380 width=40) (actual time=0.034..37.199 rows=288000 loops=3)
                           Filter: ((recorded_at >= '2024-06-01 00:00:00+00'::timestamp with time zone) AND (recorded_at < '2024-07-01 00:00:00+00'::timestamp with time zone))
 Planning Time: 6.417 ms
 Execution Time: 205.458 ms
```

The `GROUP BY sensor_type` on top adds a sort and some parallel-worker
bookkeeping that isn't the point here — the line that matters is
`Parallel Seq Scan on sensor_readings_2024_06`, singular. Eleven other
monthly partitions and the default partition exist; none of them appear
anywhere in this plan. The planner threw them out during planning, before
execution ever started, based purely on the `WHERE` clause matching only
June's range.

**3.2 — The same query, no date filter, for contrast**

```sql
EXPLAIN
SELECT sensor_type, COUNT(*)
FROM   sensor_readings
GROUP  BY sensor_type;
```

```
 Finalize GroupAggregate  (cost=156197.01..156247.68 rows=200 width=40)
   ->  Gather Merge  (cost=156197.01..156243.68 rows=400 width=40)
         ->  Sort  (cost=155196.99..155197.49 rows=200 width=40)
               ->  Partial HashAggregate  (cost=155187.34..155189.34 rows=200 width=40)
                     ->  Parallel Append  (cost=0.00..138351.15 rows=3367238 width=32)
                           ->  Parallel Seq Scan on sensor_readings_2024_01 sensor_readings_1  ...
                           ->  Parallel Seq Scan on sensor_readings_2024_03 sensor_readings_3  ...
                           ->  Parallel Seq Scan on sensor_readings_2024_05 sensor_readings_5  ...
                           ->  Parallel Seq Scan on sensor_readings_2024_07 sensor_readings_7  ...
                           ->  Parallel Seq Scan on sensor_readings_2024_08 sensor_readings_8  ...
                           ->  Parallel Seq Scan on sensor_readings_2024_10 sensor_readings_10 ...
                           ->  Parallel Seq Scan on sensor_readings_2024_12 sensor_readings_12 ...
                           ->  Parallel Seq Scan on sensor_readings_2024_04 sensor_readings_4  ...
                           ->  Parallel Seq Scan on sensor_readings_2024_06 sensor_readings_6  ...
                           ->  Parallel Seq Scan on sensor_readings_2024_09 sensor_readings_9  ...
                           ->  Parallel Seq Scan on sensor_readings_2024_11 sensor_readings_11 ...
                           ->  Parallel Seq Scan on sensor_readings_2024_02 sensor_readings_2  ...
                           ->  Parallel Seq Scan on sensor_readings_default sensor_readings_13 ...
```

With nothing to prune on, every one of the thirteen partitions shows up
as its own `Parallel Seq Scan` under a `Parallel Append`. This is the
direct, visible contrast: pruning isn't a performance optimization
happening invisibly under the hood, it's a specific number of `Seq Scan`
lines disappearing from the plan, and you can watch it happen by adding
or removing a date filter on the exact same query.

---

### Exercise 4 — BRIN vs. B-tree, With Real Numbers

**4.1 — Why this data is a good fit for BRIN**

BRIN's usefulness rests entirely on physical/value correlation — do rows
with nearby `recorded_at` values actually sit near each other on disk?
Since this data was generated and loaded in chronological order and never
updated, it should be close to perfectly correlated:

```sql
ANALYZE sensor_readings;

SELECT tablename, attname, correlation, n_distinct
FROM   pg_stats
WHERE  tablename = 'sensor_readings_2024_09' AND attname = 'recorded_at';
```

```
        tablename        |   attname   | correlation | n_distinct
--------------------------+-------------+-------------+------------
 sensor_readings_2024_09 | recorded_at |  0.99979776 |       8622
```

`correlation` ranges from -1 to 1; `0.9998` is as close to "physically
sorted by this column" as real data gets. This is the number that decides
whether BRIN is a good idea here — not the row count, not the table size.

**4.2 — Build both indexes on one partition, compare cost to build and size**

```sql
CREATE INDEX idx_sr_2024_09_brin  ON sensor_readings_2024_09 USING BRIN (recorded_at);
CREATE INDEX idx_sr_2024_09_btree ON sensor_readings_2024_09 USING BTREE (recorded_at);
```

```
CREATE INDEX
Time: 122.619 ms
CREATE INDEX
Time: 249.923 ms
```

```sql
SELECT relname, pg_size_pretty(pg_relation_size(oid)) AS index_size
FROM   pg_class
WHERE  relname IN ('idx_sr_2024_09_brin', 'idx_sr_2024_09_btree');
```

```
       relname        | index_size
-----------------------+------------
 idx_sr_2024_09_brin  | 24 kB
 idx_sr_2024_09_btree | 5800 kB
```

864,000 rows in this partition. The B-tree costs 5.8 MB — one entry per
row, roughly what you'd expect. The BRIN index costs 24 KB: **about 240
times smaller**, because it isn't storing one entry per row, it's storing
one min/max pair per 128-page block range — a few thousand summaries
instead of 864,000 index entries. It also built about twice as fast.
Neither number changes much if the table has a hundred million rows
instead of 864,000; a B-tree's cost scales with row count, BRIN's scales
with table *pages*, and pages-per-block-range is fixed.

**4.3 — What that size difference costs you at query time**

Force each index in turn and run the same narrow range query — one day
out of the month:

```sql
SET enable_seqscan = off;
DROP INDEX idx_sr_2024_09_btree;  -- isolate the BRIN index

EXPLAIN (ANALYZE, BUFFERS)
SELECT COUNT(*), round(AVG(reading_value)::numeric, 2)
FROM   sensor_readings_2024_09
WHERE  recorded_at >= '2024-09-15' AND recorded_at < '2024-09-16';
```

```
 Aggregate  (cost=7818.29..7818.30 rows=1 width=40) (actual time=7.350..7.351 rows=1 loops=1)
   Buffers: shared hit=9 read=384
   ->  Bitmap Heap Scan on sensor_readings_2024_09  (cost=19.27..7674.10 rows=28836 width=8) (actual time=0.635..5.708 rows=28800 loops=1)
         Recheck Cond: ((recorded_at >= '2024-09-15 00:00:00+00'::timestamp with time zone) AND (recorded_at < '2024-09-16 00:00:00+00'::timestamp with time zone))
         Rows Removed by Index Recheck: 17280
         Heap Blocks: lossy=384
         Buffers: shared hit=9 read=384
         ->  Bitmap Index Scan on idx_sr_2024_09_brin  (cost=0.00..12.06 rows=30322 width=0) (actual time=0.060..0.060 rows=3840 loops=1)
               Index Cond: ((recorded_at >= '2024-09-15 00:00:00+00'::timestamp with time zone) AND (recorded_at < '2024-09-16 00:00:00+00'::timestamp with time zone))
 Execution Time: 7.493 ms
```

`Heap Blocks: lossy=384` and `Rows Removed by Index Recheck: 17280` are
BRIN being honest about what it is: a **lossy** index. It doesn't know
which rows in a matching block range satisfy the condition, only that the
range's min/max *could* contain a match — so it hands back every block in
range and PostgreSQL rechecks the actual condition row by row once the
blocks are read. That recheck cost is real, and it's the trade for the
240x smaller index.

Now the B-tree, same query:

```sql
DROP INDEX idx_sr_2024_09_brin;
CREATE INDEX idx_sr_2024_09_btree ON sensor_readings_2024_09 USING BTREE (recorded_at);

EXPLAIN (ANALYZE, BUFFERS)
SELECT COUNT(*), round(AVG(reading_value)::numeric, 2)
FROM   sensor_readings_2024_09
WHERE  recorded_at >= '2024-09-15' AND recorded_at < '2024-09-16';
```

```
 Aggregate  (cost=1076.88..1076.89 rows=1 width=40) (actual time=5.781..5.782 rows=1 loops=1)
   Buffers: shared hit=384 read=27
   ->  Index Scan using idx_sr_2024_09_btree on sensor_readings_2024_09  (cost=0.42..932.69 rows=28836 width=8) (actual time=0.055..3.552 rows=28800 loops=1)
         Index Cond: ((recorded_at >= '2024-09-15 00:00:00+00'::timestamp with time zone) AND (recorded_at < '2024-09-16 00:00:00+00'::timestamp with time zone))
 Execution Time: 5.850 ms
```

5.85 ms for the B-tree against 7.49 ms for BRIN — the B-tree is
genuinely a bit faster here, exact and recheck-free by construction. But
look at what each one costs to get that: 5.8 MB of index versus 24 KB, on
*one month* of *one partition*. At the scale this chapter's title implies
— many partitions, much more than a year of data — a B-tree on every
partition's timestamp column stops being "a bit more disk" and starts
being a meaningful fraction of the table's own size, while BRIN stays
essentially free. For an append-only, time-correlated column like this
one, that trade is rarely close.

**4.4 — Keep the BRIN index, drop the comparison B-tree**

```sql
DROP INDEX idx_sr_2024_09_btree;
CREATE INDEX idx_sr_2024_09_brin ON sensor_readings_2024_09 USING BRIN (recorded_at);
RESET enable_seqscan;
```

Recreate this same `USING BRIN (recorded_at)` index on every other
monthly partition before moving on — Exercise 5 will drop one of them
whole, and Exercise 6 revisits the size question at the whole-table
level.

---

### Exercise 5 — Dropping a Partition vs. `DELETE`

**5.1 — Time the unpartitioned way: `DELETE`**

`sensor_readings_staging` is still sitting there, unpartitioned, exactly
as it was before this chapter touched anything. Delete a month's worth of
rows from it the only way an unpartitioned table allows:

```sql
DELETE FROM sensor_readings_staging
WHERE recorded_at >= '2024-01-01' AND recorded_at < '2024-02-01';
```

```
DELETE 892800
Time: 815.293 ms
```

**5.2 — Time the partitioned way: `DROP TABLE`**

```sql
DROP TABLE sensor_readings_2024_01;
```

```
DROP TABLE
Time: 17.489 ms
```

Same amount of data — the January 2024 slice, 892,800 rows either way —
and dropping the partition is roughly **47 times faster** than deleting
the equivalent rows. That gap isn't a fluke of this particular run: it's
two operations of fundamentally different cost. `DELETE` is an MVCC
operation — PostgreSQL has to visit every matching row, mark each one
dead, and write a WAL record for each one, transaction-safely, one row at
a time. `DROP TABLE` on a partition is a catalog operation — it removes
one entry saying "this table is part of that partition set" and unlinks
the file. No row is individually touched because no row was individually
anything; the whole partition was always one physical object.

**5.3 — The part `DELETE` doesn't finish**

```sql
SELECT n_live_tup, n_dead_tup, pg_size_pretty(pg_relation_size('sensor_readings_staging'))
FROM   pg_stat_user_tables
WHERE  relname = 'sensor_readings_staging';
```

```
 n_live_tup | n_dead_tup | pg_size_pretty
------------+------------+----------------
    9648230 |     892800 | 687 MB
```

892,800 dead tuples, exactly matching what was just deleted — and the
table is still 687 MB, unchanged, because `DELETE` doesn't reclaim disk
space, it just marks rows as no-longer-visible. Getting that space back
needs a `VACUUM` (or `VACUUM FULL` to actually shrink the file), which is
its own I/O-heavy pass over the table, usually running sometime later via
autovacuum rather than as part of the `DELETE` itself. `DROP TABLE`
skipped all of this — there is no bloat to vacuum, because there's no
table left to have any.

**5.4 — A gotcha worth knowing about before it surprises you**

```sql
SELECT pg_size_pretty(pg_total_relation_size('sensor_readings'));
```

```
 pg_size_pretty
----------------
 0 bytes
```

That's not an error and the data is not gone — `pg_total_relation_size()`
on a *partitioned* table reports only the parent's own storage, and a
partitioned table's parent has none; all the bytes live in the child
partitions. To get the real total, sum across the children:

```sql
SELECT pg_size_pretty(SUM(pg_total_relation_size(inhrelid))) AS total_size
FROM   pg_inherits
WHERE  inhparent = 'sensor_readings'::regclass;
```

```
 total_size
------------
 629 MB
```

**5.5 — Clean up the staging table**

It's done its job — everything from here on works from `sensor_readings`:

```sql
DROP TABLE sensor_readings_staging;
```

---

### Exercise 6 — Combining `LIST` and `RANGE`: Subpartitioning

**6.1 — Why one partition key isn't always enough**

`sensor_readings` prunes beautifully on date, but a query that also
filters on `sensor_type` — "just the traffic sensors" — still has to
scan a whole month's worth of every sensor type, because `sensor_type`
isn't part of the partition key at all. PostgreSQL allows a second level:
partition by `LIST (sensor_type)` at the top, then partition *each of
those* by `RANGE (recorded_at)` underneath — a partition of a partition,
usually called subpartitioning. Two routing decisions, made independently,
before a row ever reaches physical storage:

<img src="imgs/ch08_subpartitioning.svg" alt="Partition tree: sensor_readings_by_type partitioned by LIST(sensor_type) into three branches (temperature, traffic, air_quality), each further partitioned by RANGE(recorded_at) into three monthly leaf partitions"/>

The root and the three type branches hold no data of their own — they
exist purely to route a row one level further down. Only the nine boxes
at the bottom are real tables with real storage, and every one of this
chapter's rows lives in exactly one of them, decided first by
`sensor_type`, then by which month `recorded_at` falls in.

**6.2 — Build the two-level hierarchy**

```sql
CREATE TABLE sensor_readings_by_type (
    id            BIGINT GENERATED ALWAYS AS IDENTITY,
    sensor_id     INTEGER NOT NULL,
    sensor_type   TEXT NOT NULL
                      CHECK (sensor_type IN ('temperature', 'traffic', 'air_quality')),
    reading_value DOUBLE PRECISION NOT NULL,
    recorded_at   TIMESTAMPTZ NOT NULL
) PARTITION BY LIST (sensor_type);

CREATE TABLE srbt_temperature PARTITION OF sensor_readings_by_type
    FOR VALUES IN ('temperature') PARTITION BY RANGE (recorded_at);
CREATE TABLE srbt_traffic PARTITION OF sensor_readings_by_type
    FOR VALUES IN ('traffic') PARTITION BY RANGE (recorded_at);
CREATE TABLE srbt_air_quality PARTITION OF sensor_readings_by_type
    FOR VALUES IN ('air_quality') PARTITION BY RANGE (recorded_at);

-- Three months of subpartitions under each type branch:
CREATE TABLE srbt_temperature_2024_04 PARTITION OF srbt_temperature FOR VALUES FROM ('2024-04-01') TO ('2024-05-01');
CREATE TABLE srbt_temperature_2024_05 PARTITION OF srbt_temperature FOR VALUES FROM ('2024-05-01') TO ('2024-06-01');
CREATE TABLE srbt_temperature_2024_06 PARTITION OF srbt_temperature FOR VALUES FROM ('2024-06-01') TO ('2024-07-01');

CREATE TABLE srbt_traffic_2024_04 PARTITION OF srbt_traffic FOR VALUES FROM ('2024-04-01') TO ('2024-05-01');
CREATE TABLE srbt_traffic_2024_05 PARTITION OF srbt_traffic FOR VALUES FROM ('2024-05-01') TO ('2024-06-01');
CREATE TABLE srbt_traffic_2024_06 PARTITION OF srbt_traffic FOR VALUES FROM ('2024-06-01') TO ('2024-07-01');

CREATE TABLE srbt_air_quality_2024_04 PARTITION OF srbt_air_quality FOR VALUES FROM ('2024-04-01') TO ('2024-05-01');
CREATE TABLE srbt_air_quality_2024_05 PARTITION OF srbt_air_quality FOR VALUES FROM ('2024-05-01') TO ('2024-06-01');
CREATE TABLE srbt_air_quality_2024_06 PARTITION OF srbt_air_quality FOR VALUES FROM ('2024-06-01') TO ('2024-07-01');
```

Three months only, and only as a working example — building out all
twelve for all three types is the same pattern repeated, not a new idea,
and this chapter's disk budget would rather spend on data than on empty
demonstration partitions.

**6.3 — Backfill from `sensor_readings` and inspect the tree**

```sql
INSERT INTO sensor_readings_by_type (sensor_id, sensor_type, reading_value, recorded_at)
SELECT sensor_id, sensor_type, reading_value, recorded_at
FROM   sensor_readings
WHERE  recorded_at >= '2024-04-01' AND recorded_at < '2024-07-01';
```

```
INSERT 0 2620800
Time: 3389.698 ms (00:03.390)
```

```sql
SELECT relid::regclass AS relation, parentrelid::regclass AS parent, isleaf, level
FROM   pg_partition_tree('sensor_readings_by_type')
ORDER  BY level, 1;
```

```
         relation         |         parent          | isleaf | level
--------------------------+-------------------------+--------+-------
 sensor_readings_by_type  |                         | f      |     0
 srbt_air_quality         | sensor_readings_by_type | f      |     1
 srbt_temperature         | sensor_readings_by_type | f      |     1
 srbt_traffic             | sensor_readings_by_type | f      |     1
 srbt_air_quality_2024_04 | srbt_air_quality        | t      |     2
 srbt_air_quality_2024_05 | srbt_air_quality        | t      |     2
 srbt_air_quality_2024_06 | srbt_air_quality        | t      |     2
 srbt_temperature_2024_04 | srbt_temperature        | t      |     2
 srbt_temperature_2024_05 | srbt_temperature        | t      |     2
 srbt_temperature_2024_06 | srbt_temperature        | t      |     2
 srbt_traffic_2024_04     | srbt_traffic            | t      |     2
 srbt_traffic_2024_05     | srbt_traffic            | t      |     2
 srbt_traffic_2024_06     | srbt_traffic            | t      |     2
(13 rows)
```

`pg_partition_tree()` is the built-in way to see this shape directly
instead of inferring it from table names: one root, three `LIST`
branches at level 1, nine `RANGE` leaves at level 2 — every row actually
lives in one of those nine leaf tables, never in an intermediate one.

**6.4 — Confirm pruning happens on both dimensions at once**

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT COUNT(*), round(AVG(reading_value)::numeric, 2)
FROM   sensor_readings_by_type
WHERE  sensor_type = 'traffic'
AND    recorded_at >= '2024-05-01' AND recorded_at < '2024-06-01';
```

```
 Finalize Aggregate  (cost=6794.58..6794.60 rows=1 width=40) (actual time=37.692..40.669 rows=1 loops=1)
   ->  Gather  (cost=6794.47..6794.58 rows=1 width=40) (actual time=37.612..40.655 rows=2 loops=1)
         Workers Planned: 1
         ->  Partial Aggregate  (cost=5794.47..5794.48 rows=1 width=40) (actual time=36.350..36.351 rows=1 loops=2)
               ->  Parallel Seq Scan on srbt_traffic_2024_05 sensor_readings_by_type  (cost=0.00..5794.45 rows=4 width=8) (actual time=0.018..26.204 rows=178560 loops=2)
                     Filter: ((recorded_at >= '2024-05-01 00:00:00+00'::timestamp with time zone) AND (recorded_at < '2024-06-01 00:00:00+00'::timestamp with time zone) AND (sensor_type = 'traffic'::text))
 Execution Time: 40.738 ms
```

One line, `Parallel Seq Scan on srbt_traffic_2024_05`, out of the nine
leaf partitions that exist. The `sensor_type = 'traffic'` predicate
pruned two of the three top-level branches before the range predicate
even got involved, and the range predicate then pruned two of that
branch's three months. Both partition keys did real work on this single
query, independently, in the same plan.

---

## Summary — What You Should Now Know

| Tool | What it does |
|------|---------------|
| `PARTITION BY RANGE (col)` | Split a table into physical children by value range on one column — the whole table stays queryable as one name |
| `FOR VALUES FROM (...) TO (...)` | Half-open interval defining one range partition's bounds |
| `... DEFAULT` partition | Catches any row that doesn't match a defined range — without one, out-of-range inserts are rejected outright |
| `tableoid::regclass` | Ask which physical partition a given row actually lives in |
| Partition pruning | The planner drops non-matching partitions from the plan *before* execution, visible as missing `Seq Scan` lines in `EXPLAIN` |
| `USING BRIN (col)` | Index storing one min/max summary per block range — tiny and cheap, but only useful when physical and value order correlate |
| `correlation` in `pg_stats` | The number that tells you whether BRIN is actually a good idea for a given column |
| `DROP TABLE` on a partition | Metadata-only, near-instant removal of a whole partition's worth of data — no per-row MVCC cost, no bloat to vacuum afterward |
| `pg_total_relation_size()` on a partitioned table | Reports the (empty) parent only — sum over `pg_inherits` for the real total |
| `PARTITION BY LIST` over `PARTITION BY RANGE` | Subpartitioning — two partition keys, pruned independently, in one query plan |
| `pg_partition_tree()` | Walk a partition hierarchy — root, branches, and leaves — as a query instead of by table-naming convention |

**The key design insight** from this chapter is that partitioning and
indexing solve different halves of the same problem, and BRIN sits
exactly at their intersection. Partition pruning throws away whole
partitions the planner can prove are irrelevant, cutting the search space
by orders of magnitude before a single row is touched. BRIN then
indexes what's left almost for free, precisely because append-only,
time-ordered data — the same shape of data that makes range partitioning
by date the obvious choice — is also the shape that makes a
physically-correlated, lossy index a good trade instead of a bad one.
Neither technique is really "for time-series data" in the abstract; both
are for data whose physical order already tells you something true about
its values, and this chapter's sensor readings happen to be exactly that.

---

*Going further: hand-writing twelve `CREATE TABLE ... PARTITION OF`
statements a year, forever, is exactly the kind of recurring
maintenance that Chapter 19's `pg_cron` is suited to automate — schedule
a monthly job that creates next month's partition before it's needed and,
if a retention policy allows it, drops the oldest one the same way
Exercise 5 did by hand. In production this whole
lifecycle — creation, retention, even the migration of aging partitions
to cheaper storage — is usually handled by the `pg_partman` extension
rather than bespoke scripts; everything in this chapter is what
`pg_partman` is automating under the hood, which is worth knowing before
reaching for it, not instead of. `sensor_readings` also isn't done being
useful: Chapter 9's materialized views roll it up into daily summaries
without re-scanning raw readings each time, Chapter 11's window functions
compute rolling averages and day-over-day deltas across it, and Chapter
16 adds a generated `reading_date` column to make date-only grouping
cheaper still. And a caution in the other direction — BRIN is not a
free upgrade for every index. A column with low correlation (a randomly-
assigned `sensor_id`, say, rather than an ever-increasing timestamp)
gets none of BRIN's benefit and most of a sequential scan's cost, because
every block range ends up spanning the entire value domain. Check
`correlation` before reaching for BRIN, the same way Exercise 4 did here
— it's a bet on the physical shape of your data, not a strictly smaller
B-tree.*
