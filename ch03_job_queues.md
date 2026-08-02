# Chapter 3 — Job Queues: `FOR UPDATE SKIP LOCKED`

> *"A queue is just a table that everyone is racing to read."*

---

## Background

Sooner or later almost every application needs a queue: a list of work
items that a pool of workers processes one at a time, safely, without two
workers ever grabbing the same item. The reflexive answer is to reach for a
message broker — Redis, RabbitMQ, SQS, Kafka. Those tools earn their keep at
serious scale. But if your data already lives in PostgreSQL, running a
second system just to hand out rows to workers is often unnecessary
complexity: another service to deploy, monitor, and keep consistent with
the database.

PostgreSQL can do this job itself. The `FOR UPDATE SKIP LOCKED` row-locking
clause, combined with an ordinary table, gives you an atomic "claim the next
item and don't let anyone else touch it" primitive — the same guarantee a
dedicated queue product sells you, built out of two SQL keywords. This
chapter builds a job queue from scratch: the schema, the atomic claim query,
concurrent worker behaviour, stalled-job recovery, and a dead-letter path
for jobs that keep failing.

This is not a toy exercise. This exact pattern — a status column, a claim
query, a heartbeat, a dead-letter table — is what libraries like [`river`](https://riverqueue.com/),
[`oban`](https://oban.hexdocs.pm/Oban.html) (Elixir), and countless in-house job runners implement on top of
PostgreSQL in production.

---

## The Scenario

Portsmith's permitting office processes a steady stream of permit
applications: building work, business licenses, public events, signage, and
demolitions. Each application needs to move through a review pipeline, and
the office wants that processing to happen asynchronously and reliably —
work should never be lost, never double-processed, and a crashed reviewer
process shouldn't leave an application stuck in limbo forever.

The `jobs` table models this as a queue. Every row is one permit
application awaiting review. A `status` column tracks its life cycle, a
`priority` column lets safety-critical work (demolitions) jump ahead of
routine work (sign permits), and a retry counter with a companion
`dead_letter_jobs` table handles applications whose processing keeps
failing.

| Column         | Purpose                                                        |
|----------------|-----------------------------------------------------------------|
| `status`       | `queued` → `in_progress` → `completed` (or back to `queued`, or dead-lettered) |
| `priority`     | 1 (most urgent — demolitions) to 5 (least urgent — sign permits) |
| `payload`      | JSONB — the permit application details                         |
| `attempts` / `max_attempts` | Retry bookkeeping                                 |
| `claimed_by` / `claimed_at` | Which worker has the job, and since when          |
| `heartbeat_at` | Updated periodically by the worker while it holds the job       |

The `status` column's life cycle, drawn out — this is what Exercises 2
through 5 each implement one piece of:

<img src="imgs/ch03_job_lifecycle.svg" alt="State diagram: queued transitions to in_progress on claim; in_progress transitions to completed on worker success, back to queued on a reclaim sweep if attempts are below max_attempts, or to dead_letter_jobs on a reclaim sweep if attempts are exhausted"/>

Every arrow here is a specific query you'll write by hand later in this
chapter — there's no hidden state machine enforcing this, just the
`status` column, the claim query, and the reclaim sweep agreeing on what
each value means.

No extensions are required for this chapter — everything here is built on
core PostgreSQL locking semantics.

---

## Exercise Goals

By the end of this chapter you will be able to:

- Design a queue table schema, including a partial index tuned for the
  claim query's access pattern.
- Write the atomic `UPDATE ... FROM (SELECT ... FOR UPDATE SKIP LOCKED)`
  claim query, and explain why naive two-step approaches race.
- Observe, with two concurrent `psql` sessions, that `SKIP LOCKED` lets
  workers proceed past rows another worker is holding — and contrast that
  with the blocking behaviour of plain `FOR UPDATE`.
- Implement a heartbeat/timeout mechanism that reclaims jobs abandoned by a
  crashed worker.
- Route jobs that exhaust their retries into a dead-letter table.
- Benchmark claim throughput at different concurrency levels with
  `pgbench`.

---

## Installation

This chapter needs nothing beyond what Chapter 1 already set up: PostgreSQL
16 and a Python 3.12 virtual environment with `psycopg`. If you skipped
Chapter 1, see its Installation section. You will also use `pgbench` for
Exercise 6, which ships with the standard PostgreSQL client tools
(`postgresql-client-16` on Debian/Ubuntu).

---

## Loading the Data

### Run the seed script

From the `book/` directory, with the virtual environment active:

```bash
python data/ch03_seed.py
```

Expected output:

```
Connecting to: dbname=portsmith
Creating schema …
Inserting 45 jobs …
Done — 45 rows in jobs, all queued.
```

The seed script is self-contained — it does not depend on Chapter 1 or 2's
data.

### Verify the load

Open `psql portsmith` and run these checks.

**Check 1 — table structure:**

```sql
\d jobs
```

```
                                        Table "public.jobs"
    Column    |           Type           | Collation | Nullable |             Default
--------------+--------------------------+-----------+----------+----------------------------------
 id           | bigint                   |           | not null | nextval('jobs_id_seq'::regclass)
 job_type     | text                     |           | not null |
 payload      | jsonb                    |           | not null |
 status       | text                     |           | not null | 'queued'::text
 priority     | smallint                 |           | not null | 5
 attempts     | integer                  |           | not null | 0
 max_attempts | integer                  |           | not null | 3
 created_at   | timestamp with time zone |           | not null | clock_timestamp()
 claimed_at   | timestamp with time zone |           |          |
 claimed_by   | text                     |           |          |
 heartbeat_at | timestamp with time zone |           |          |
 completed_at | timestamp with time zone |           |          |
 last_error   | text                     |           |          |
Indexes:
    "jobs_pkey" PRIMARY KEY, btree (id)
    "idx_jobs_claim_order" btree (priority, created_at, id) WHERE status = 'queued'::text
    "idx_jobs_status" btree (status)
Check constraints:
    "jobs_status_check" CHECK (status = ANY (ARRAY['queued'::text, 'in_progress'::text, 'completed'::text, 'failed'::text]))
```

**Check 2 — job counts by type and priority:**

```sql
SELECT job_type, priority, COUNT(*) AS jobs
FROM   jobs
GROUP  BY job_type, priority
ORDER  BY priority;
```

```
     job_type      | priority | jobs
-------------------+----------+------
 demolition_permit |        1 |    4
 business_license  |        2 |   12
 building_permit   |        3 |   15
 event_permit      |        4 |    8
 sign_permit       |        5 |    6
(5 rows)
```

**Check 3 — everything starts queued:**

```sql
SELECT status, COUNT(*) FROM jobs GROUP BY status;
```

```
 status | count
--------+-------
 queued |    45
(1 row)
```

If all three match, proceed to the exercises.

> **Note:** If you re-run `ch03_seed.py` at any point during the exercises
> to reset to a clean state, it drops and recreates both `jobs` and
> `dead_letter_jobs`.

---

## Exercises

---

### Exercise 1 — Designing the Queue Schema

**1.1 — Why a partial index**

The claim query (which you'll write in Exercise 2) only ever looks at rows
where `status = 'queued'`, ordered by `priority` then `created_at`. As the
queue runs, the vast majority of rows will end up `completed` — a normal
B-tree index on `(priority, created_at, id)` would faithfully index every
one of those settled rows even though the claim query never looks at them.

`idx_jobs_claim_order` is a **partial index** — it only indexes rows
matching `WHERE status = 'queued'`:

```sql
CREATE INDEX idx_jobs_claim_order
    ON jobs (priority, created_at, id)
    WHERE status = 'queued';
```

This keeps the index small regardless of how many historical jobs pile up
in `completed` or `failed` state, because settled rows are never in it.

**1.2 — Why `id` is part of the sort key, not just `created_at`**

You might expect `ORDER BY priority, created_at` to be enough — oldest job
in the highest-priority bucket goes first. But timestamps are not always
unique. If two jobs are inserted in the same transaction, both can get an
identical `created_at` (more on this below), and `ORDER BY` over tied
values has no defined order. Appending the primary key, `id`, as a final
tiebreaker guarantees a deterministic order even when timestamps collide:

```sql
ORDER BY priority ASC, created_at ASC, id ASC
```

> **A gotcha worth knowing:** `now()` returns the **transaction's** start
> time, not the current wall-clock time — every call to `now()` inside the
> same transaction returns the same value. The seed script originally used
> `created_at TIMESTAMPTZ DEFAULT now()`, and because all 45 rows were
> inserted in one transaction, every single row ended up with an *identical*
> `created_at`. The fix is `clock_timestamp()`, which returns the actual
> current time at the moment it's evaluated, differing row to row even
> within one transaction. `jobs.created_at` uses `clock_timestamp()` for
> exactly this reason. This is the same family of surprise as the JSONB
> `null` vs. SQL `NULL` gotcha from Chapter 1: a function name that looks
> interchangeable with another is not.

**1.3 — Confirm the index is used**

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT id
FROM   jobs
WHERE  status = 'queued'
ORDER  BY priority ASC, created_at ASC, id ASC
FOR UPDATE SKIP LOCKED
LIMIT  1;
```

```
 Limit  (cost=0.14..6.17 rows=1 width=24) (actual time=0.022..0.022 rows=1 loops=1)
   Buffers: shared hit=3
   ->  LockRows  (cost=0.14..12.20 rows=2 width=24) (actual time=0.021..0.021 rows=1 loops=1)
         Buffers: shared hit=3
         ->  Index Scan using idx_jobs_claim_order on jobs  (cost=0.14..12.18 rows=2 width=24) (actual time=0.010..0.010 rows=1 loops=1)
               Filter: (status = 'queued'::text)
               Buffers: shared hit=2
```

Now drop the index and run the identical query again inside a transaction
you roll back (so the drop doesn't stick):

```sql
BEGIN;
DROP INDEX idx_jobs_claim_order;

EXPLAIN (ANALYZE, BUFFERS)
SELECT id
FROM   jobs
WHERE  status = 'queued'
ORDER  BY priority ASC, created_at ASC, id ASC
FOR UPDATE SKIP LOCKED
LIMIT  1;

ROLLBACK;
```

```
 Limit  (cost=9.51..9.53 rows=1 width=24) (actual time=0.071..0.072 rows=1 loops=1)
   ->  LockRows  (cost=9.51..9.54 rows=2 width=24) (actual time=0.070..0.071 rows=1 loops=1)
         ->  Sort  (cost=9.51..9.52 rows=2 width=24) (actual time=0.067..0.068 rows=1 loops=1)
               Sort Key: priority, created_at, id
               Sort Method: quicksort  Memory: 27kB
               ->  Bitmap Heap Scan on jobs  (cost=4.16..9.50 rows=2 width=24) (actual time=0.018..0.027 rows=45 loops=1)
                     Recheck Cond: (status = 'queued'::text)
                     ->  Bitmap Index Scan on idx_jobs_status  (cost=0.00..4.16 rows=2 width=0) (actual time=0.013..0.013 rows=45 loops=1)
                           Index Cond: (status = 'queued'::text)
```

Without `idx_jobs_claim_order`, PostgreSQL still finds the queued rows
(via `idx_jobs_status`), but it must then **sort all of them** to find the
one with the lowest `(priority, created_at, id)` — an extra `Sort` node.
With the tailored partial index, the rows are already stored in claim
order, so PostgreSQL walks the index and stops at the first match. On a
45-row table the difference is invisible; on a busy production queue with
a deep backlog, eliminating the sort on every single claim matters a
great deal.

---

### Exercise 2 — The Atomic Claim Query

**2.1 — Why a naive two-step claim races**

The tempting first approach is to `SELECT` a candidate row, then `UPDATE`
it in a second statement:

```sql
-- ⚠ Do not do this — it has a race condition
SELECT id FROM jobs WHERE status = 'queued' ORDER BY priority, created_at, id LIMIT 1;
-- ... application reads id = 7 ...
UPDATE jobs SET status = 'in_progress' WHERE id = 7;
```

Between the `SELECT` and the `UPDATE`, nothing stops a second worker from
running the exact same `SELECT`, reading the same `id = 7`, and also
issuing the `UPDATE`. Both workers now believe they own job 7. This is a
classic **check-then-act race condition** — the gap between reading and
acting is exactly where two workers can interleave.

**2.2 — `FOR UPDATE` closes the gap, but blocks**

Locking the row as part of the `SELECT` closes the race:

```sql
SELECT id FROM jobs WHERE status = 'queued' ORDER BY priority, created_at, id
FOR UPDATE LIMIT 1;
```

Now a second worker running the same query, in a separate transaction,
**blocks** until the first worker's transaction commits or rolls back —
correct, but it means every worker but one sits idle waiting for a lock
instead of moving on to a different job. Section 3.1 demonstrates this.

**2.3 — `SKIP LOCKED` lets workers move past each other**

Adding `SKIP LOCKED` tells PostgreSQL: if the next candidate row is already
locked by another transaction, don't wait for it — skip it and consider the
row after it.

```sql
SELECT id FROM jobs WHERE status = 'queued' ORDER BY priority, created_at, id
FOR UPDATE SKIP LOCKED LIMIT 1;
```

This is the piece that makes PostgreSQL usable as a concurrent queue: N
workers can run this query at the same instant and each will walk away
with a *different* row, with no blocking and no double-claims.

**2.4 — The full atomic claim: lock, update, and return in one statement**

Locking the row is only half the job — you still need to mark it
`in_progress` before releasing the lock, and you want the whole thing to
happen as a single round trip. Combine the `SELECT ... FOR UPDATE SKIP
LOCKED` with the `UPDATE` using a CTE:

```sql
WITH next_job AS (
    SELECT id
    FROM   jobs
    WHERE  status = 'queued'
    ORDER  BY priority ASC, created_at ASC, id ASC
    FOR UPDATE SKIP LOCKED
    LIMIT  1
)
UPDATE jobs
SET    status       = 'in_progress',
       claimed_at   = now(),
       claimed_by   = 'demo-worker',
       heartbeat_at = now(),
       attempts     = attempts + 1
FROM   next_job
WHERE  jobs.id = next_job.id
RETURNING jobs.id, jobs.job_type, jobs.payload ->> 'application_id' AS application_id,
          jobs.priority, jobs.attempts, jobs.status;
```

```
 id |     job_type      | application_id | priority | attempts |   status
----+-------------------+----------------+----------+----------+-------------
  1 | demolition_permit | DP-2024-0001   |        1 |        1 | in_progress
(1 row)
```

This single statement is the entire claim operation: find the best
candidate, skip anything locked, mark it claimed, and hand back its data —
atomically, with no window for a race. This is exactly the query
`data/ch03_worker.py` runs (see `CLAIM_SQL`). Run it again and the
demolition permit at `id = 2` comes back next — `id = 1` is now
`in_progress`, so it's no longer a candidate.

> Roll this back if you ran it directly in `psql` and want to keep the
> queue clean for later exercises: wrap it in `BEGIN; ... ROLLBACK;`.

---

### Exercise 3 — Simulating Concurrent Workers

**3.1 — `SKIP LOCKED` vs. plain `FOR UPDATE`, in two `psql` sessions**

Open two terminals with `psql portsmith` in each. In **Session A**, start a
transaction, claim 5 rows, and hold the transaction open (don't commit
yet):

```sql
-- Session A
BEGIN;
SELECT id, job_type FROM jobs WHERE status = 'queued'
ORDER BY priority, created_at, id
FOR UPDATE SKIP LOCKED LIMIT 5;
```

```
 id |     job_type
----+-------------------
  1 | demolition_permit
  2 | demolition_permit
  3 | demolition_permit
  4 | demolition_permit
  5 | business_license
(5 rows)
```

Leave that transaction open. In **Session B**, run the identical query:

```sql
-- Session B (Session A is still open, holding locks on ids 1-5)
BEGIN;
SELECT id, job_type FROM jobs WHERE status = 'queued'
ORDER BY priority, created_at, id
FOR UPDATE SKIP LOCKED LIMIT 5;
```

```
 id |    job_type
----+------------------
  6 | business_license
  7 | business_license
  8 | business_license
  9 | business_license
 10 | business_license
(5 rows)
```

Session B returns immediately with a **different** set of rows — it
silently skipped `1`–`5` because they were locked, and moved on to the next
five unlocked candidates. Commit or roll back both sessions to release the
locks:

```sql
COMMIT;   -- run in both sessions
```

**3.2 — Now try it with plain `FOR UPDATE` (no `SKIP LOCKED`)**

Repeat the same two-session experiment, but drop `SKIP LOCKED`:

```sql
-- Session A
BEGIN;
SELECT id, job_type FROM jobs WHERE status = 'queued'
ORDER BY priority, created_at, id
FOR UPDATE LIMIT 5;
-- (leave this transaction open)
```

```sql
-- Session B — this will hang
BEGIN;
SELECT id, job_type FROM jobs WHERE status = 'queued'
ORDER BY priority, created_at, id
FOR UPDATE LIMIT 5;
```

Session B does not return. It is blocked, waiting for Session A's row
locks to be released. Only once Session A runs `COMMIT` (or `ROLLBACK`)
does Session B's query complete — and when it does, it returns the *same*
five rows Session A had, now that they're unlocked again:

```
-- (Session B, after Session A commits)
 id |     job_type
----+-------------------
  1 | demolition_permit
  2 | demolition_permit
  3 | demolition_permit
  4 | demolition_permit
  5 | business_license
(5 rows)
```

This is the difference in one sentence: **plain `FOR UPDATE` serializes
workers through the lock; `SKIP LOCKED` lets them fan out across the
table.** For a job queue, you always want the latter — a blocked worker is
a wasted worker. Both runs side by side, as a timeline:

<img src="imgs/ch03_skip_locked.svg" alt="Sequence diagram: with FOR UPDATE SKIP LOCKED, Session A claims rows 1-5 and Session B immediately claims rows 6-10 with neither session blocking; with plain FOR UPDATE, Session B blocks after requesting rows 1-5 until Session A commits, then receives the same rows 1-5"/>

**3.3 — Real concurrent workers with `ch03_worker.py`**

Reset the data (`python data/ch03_seed.py`) if you ran the manual claim in
Exercise 2.4 without rolling it back. Then launch two workers in the
background, each capped to 10 jobs so they finish quickly:

```bash
python data/ch03_worker.py --worker-id w1 --max-jobs 10 --fail-rate 0 &
python data/ch03_worker.py --worker-id w2 --max-jobs 10 --fail-rate 0 &
wait
```

Each prints a running log as it claims and completes jobs, e.g.:

```
[w1] claimed job 2 (demolition_permit, attempt 1/3): DP-2024-0002 — processing for 0.09s
[w1] job 2 completed
[w2] claimed job 1 (demolition_permit, attempt 1/3): DP-2024-0001 — processing for 0.12s
[w2] job 1 completed
```

Once both finish, confirm the split was clean — 20 jobs completed total,
no job claimed by both workers:

```sql
SELECT claimed_by, COUNT(*) FROM jobs WHERE status = 'completed'
GROUP BY claimed_by ORDER BY claimed_by;
```

```
 claimed_by | count
------------+-------
 w1         |    10
 w2         |    10
(2 rows)
```

```sql
SELECT status, COUNT(*) FROM jobs GROUP BY status;
```

```
  status   | count
-----------+-------
 completed |    20
 queued    |    25
(2 rows)
```

10 + 10 = 20, matching exactly the `--max-jobs 10` cap on each worker — no
overlaps, no double-processing, no lost jobs.

---

### Exercise 4 — Heartbeat and Stalled-Job Recovery

Claiming a job is only half the reliability story. What happens if the
worker that claimed a job crashes, gets OOM-killed, or loses its network
connection halfway through? The row is stuck at `status = 'in_progress'`
forever unless something notices and puts it back.

**4.1 — The heartbeat column**

`heartbeat_at` exists for exactly this. A well-behaved worker updates it
periodically while it holds a job (see the `while` loop in
`process_job()` in `ch03_worker.py`, which sends a heartbeat roughly every
2 seconds during simulated processing). If a job has been `in_progress`
for a long time *and* its heartbeat has gone stale, that's a strong signal
the worker holding it is dead — a live worker would have updated it.

**4.2 — Simulate a crashed worker**

Pick any queued job and manually walk it through what a real claim would
do, then simulate a crash by never sending a heartbeat again:

```sql
UPDATE jobs
SET    status = 'in_progress', claimed_at = now(),
       claimed_by = 'worker-crashed', heartbeat_at = now(),
       attempts = attempts + 1
WHERE  id = 21;

-- Simulate 5 minutes of silence from the "crashed" worker
UPDATE jobs SET heartbeat_at = now() - interval '5 minutes' WHERE id = 21;
```

**4.3 — Run the reclaim sweep**

```bash
python data/ch03_reclaim.py --timeout 30
```

```
Connecting to: dbname=portsmith
  job 21 (building_permit) stalled — requeued (attempt 1)

Done: 1 requeued, 0 dead-lettered.
```

The sweep looks for `in_progress` rows whose `heartbeat_at` is older than
`--timeout` seconds (`FIND_STALLED_SQL` in `ch03_reclaim.py`), and since
this job's `attempts` (1) is still below `max_attempts` (3), it goes back
to `queued`:

```sql
SELECT id, status, attempts, claimed_by, heartbeat_at, last_error
FROM   jobs WHERE id = 21;
```

```
 id | status | attempts | claimed_by | heartbeat_at |                     last_error
----+--------+----------+------------+--------------+----------------------------------------------------
 21 | queued |        1 |            |              | stalled: no heartbeat since ... (last claimed by worker-crashed)
```

Notice `attempts` stayed at `1` — the reclaim did not reset it. The
attempt the crashed worker used is still counted; the job doesn't get a
free retry just because the worker that lost it never got to report
failure honestly.

**4.4 — Why the timeout, not an outright deadline**

A fixed timeout on the *last heartbeat* (rather than on total processing
time) lets jobs run arbitrarily long as long as they keep proving they're
alive. A 10-minute report-generation job with a 30-second heartbeat
interval will never be mistaken for stalled, while a worker that dies
mid-task is detected within one missed heartbeat window. Run
`ch03_reclaim.py` again immediately — it correctly finds nothing to do,
since the reclaimed job now has a fresh `queued` state and no stale
`in_progress` row exists:

```
No jobs stalled beyond 30s — nothing to do.
```

---

### Exercise 5 — Dead-Lettering Exhausted Jobs

Some jobs will never succeed no matter how many times you retry them — a
malformed application, a permanently invalid address, a bug that only
triggers on one particular payload. Retrying forever wastes worker time and
can mask a real problem. Once a job has used its last attempt, it belongs
in `dead_letter_jobs`: out of the active queue, but preserved for a human
to inspect.

**5.1 — The `dead_letter_jobs` schema**

```sql
\d dead_letter_jobs
```

```
                     Table "public.dead_letter_jobs"
    Column    |           Type           | Collation | Nullable | Default
--------------+--------------------------+-----------+----------+---------
 id           | bigint                   |           | not null |
 job_type     | text                     |           | not null |
 payload      | jsonb                    |           | not null |
 priority     | smallint                 |           | not null |
 attempts     | integer                  |           | not null |
 max_attempts | integer                  |           | not null |
 created_at   | timestamp with time zone |           | not null |
 last_error   | text                     |           |          |
 failed_at    | timestamp with time zone |           | not null | now()
```

It mirrors `jobs` but adds `failed_at` and drops the in-flight columns
(`status`, `claimed_by`, `heartbeat_at`) that no longer mean anything once
a job is out of the active queue.

**5.2 — Push a job past its retry limit**

Continuing with job 21 from Exercise 4 (now back to `queued` with
`attempts = 1`), fast-forward it to its last attempt and let it stall
again:

```sql
UPDATE jobs
SET    status = 'in_progress', claimed_at = now(),
       claimed_by = 'worker-crashed-2', heartbeat_at = now() - interval '5 minutes',
       attempts = max_attempts
WHERE  id = 21;
```

```bash
python data/ch03_reclaim.py --timeout 30
```

```
Connecting to: dbname=portsmith
  job 21 (building_permit) exhausted retries — dead-lettered

Done: 0 requeued, 1 dead-lettered.
```

This time `attempts` (3) is no longer less than `max_attempts` (3), so the
sweep's `DEAD_LETTER_SQL` runs instead: it `DELETE`s the row from `jobs`
and `INSERT`s it into `dead_letter_jobs` in one CTE, so the row is never
visible in neither-place or both-places, even under concurrent access.

```sql
SELECT id FROM jobs WHERE id = 21;
```

```
 id
----
(0 rows)
```

```sql
SELECT id, job_type, payload ->> 'application_id' AS application_id,
       attempts, max_attempts, last_error, failed_at
FROM   dead_letter_jobs WHERE id = 21;
```

```
 id |    job_type     | application_id | attempts | max_attempts |                     last_error                     |          failed_at
----+-----------------+----------------+----------+--------------+-----------------------------------------------------+-------------------------------
 21 | building_permit | BP-2024-0005   |        3 |            3 | stalled: no heartbeat since ... (last claimed ...)  | 2026-07-12 22:15:45.613583-04
(1 row)
```

The exact same dead-lettering logic runs inline inside `ch03_worker.py`
when a job fails organically (not via a stall) on its last attempt — see
`DEAD_LETTER_SQL` in that script. Whether a job dies from an explicit
failure or from going silent, it ends up in the same place, with a record
of why.

---

### Exercise 6 — Benchmarking Claim Throughput with `pgbench`

**6.1 — A benchmark script that doesn't drain the queue**

`pgbench` repeatedly runs a SQL script against the database for a fixed
duration, from any number of concurrent client connections — exactly the
tool for measuring how the claim query holds up under contention. The
catch: if the script just claims a job and leaves it claimed, 45 rows
disappear from the pool in well under a second and every worker after that
finds nothing to do. `data/ch03_claim_bench.sql` works around this by
claiming a job and then **immediately releasing it back to `queued`** in
the same transaction:

```sql
BEGIN;

WITH next_job AS (
    SELECT id
    FROM   jobs
    WHERE  status = 'queued'
    ORDER  BY priority ASC, created_at ASC, id ASC
    FOR UPDATE SKIP LOCKED
    LIMIT  1
)
UPDATE jobs
SET    status       = 'in_progress',
       claimed_at   = now(),
       claimed_by   = 'bench-' || :client_id,
       heartbeat_at = now()
FROM   next_job
WHERE  jobs.id = next_job.id
RETURNING jobs.id AS claimed_id \gset

UPDATE jobs
SET    status = 'queued', claimed_at = NULL, claimed_by = NULL, heartbeat_at = NULL
WHERE  id = :claimed_id;

COMMIT;
```

`:client_id` is a `pgbench` built-in variable — the number of the
simulated client running this script. `\gset` captures the claimed row's
`id` into a `pgbench` variable (`:claimed_id`) so the release step can
target it. This keeps the pool at a constant 45 claimable rows for the
whole benchmark run, so throughput reflects lock contention rather than
the queue running dry.

**6.2 — Run at increasing concurrency**

```bash
pgbench -n -c 1  -j 1  -T 5 -f data/ch03_claim_bench.sql portsmith
pgbench -n -c 4  -j 4  -T 5 -f data/ch03_claim_bench.sql portsmith
pgbench -n -c 16 -j 16 -T 5 -f data/ch03_claim_bench.sql portsmith
```

`-c` is the number of simulated concurrent workers (clients), `-j` the
number of `pgbench` threads driving them, and `-T 5` runs each test for 5
seconds. Results on the machine used to write this chapter:

| Clients (`-c`) | tps       | Avg. latency |
|-----------------|-----------|--------------|
| 1               |   799     | 1.25 ms      |
| 4               | 1,202     | 3.33 ms      |
| 16              | 2,570     | 6.23 ms      |

Your numbers will differ with your hardware — the shape of the result is
what matters. Throughput climbs with concurrency because `SKIP LOCKED`
lets additional workers keep finding unlocked rows to claim instead of
queueing up behind each other; latency per transaction also climbs
because more workers are contending for the same 45-row table and for
CPU. Try dropping `idx_jobs_claim_order` (inside a `BEGIN; ... ROLLBACK;`
block, as in Exercise 1.3) and rerunning the `-c 16` case — you should see
tps fall, since every claim now pays for a `Sort` over all queued rows
instead of an index walk.

**6.3 — Where this stops being enough**

`pgbench` here is exercising claim contention on 45 rows — a stand-in for
"the working set the claim query actually scans." A real permitting-office
queue might hold a very different shape of data (thousands of queued rows,
heavy skew toward one `priority` bucket), and the honest way to benchmark
your own workload is to seed a table that resembles it, not a 45-row toy.
Chapter 20 (`pg_stat_statements` and Query Performance) picks this thread
back up: rather than a synthetic benchmark, it measures and fixes real
slow queries observed in production traffic.

---

## Summary — What You Should Now Know

You built a working, concurrency-safe job queue entirely out of core
PostgreSQL features. Here is a reference for the pieces:

| Tool | What it does |
|------|-------------|
| `FOR UPDATE` | Locks selected rows; other transactions selecting the same rows **block** until released |
| `FOR UPDATE SKIP LOCKED` | Locks selected rows; other transactions **skip** already-locked rows instead of blocking |
| `WITH next_job AS (... FOR UPDATE SKIP LOCKED LIMIT 1) UPDATE ... FROM next_job` | The atomic claim pattern: find, lock, and mark a row in one round trip |
| Partial index `WHERE status = 'queued'` | Keeps the claim-path index small regardless of how many settled rows accumulate |
| `clock_timestamp()` vs. `now()` | `now()` freezes at transaction start; `clock_timestamp()` reflects real wall-clock time on every call |
| `heartbeat_at` + timeout sweep | Detects and recovers jobs abandoned by a crashed worker |
| `dead_letter_jobs` | Removes permanently-failing jobs from the active queue while preserving them for inspection |
| `pgbench -f script.sql` | Benchmarks a custom SQL workload at a chosen concurrency level |

**The key design insight** from this chapter is that a reliable queue is
not one clever query — it's the combination of an atomic claim, a way to
detect workers that go silent, and a place for work that genuinely cannot
succeed. PostgreSQL's row-locking primitives give you the first two almost
for free; the dead-letter table is just a normal table.

The `jobs` table you built here is reused directly in later chapters:
Chapter 13 adds a trigger that fires `NOTIFY` on status changes so
listeners can react to queue activity in real time, Chapter 14 uses
advisory locks alongside it for leader-election patterns, and Chapter 19
schedules the reclaim sweep you wrote by hand in Exercise 4 to run
automatically with `pg_cron`.

---

*Going further: the pattern in this chapter — status column, atomic claim,
heartbeat, dead-letter — is exactly what PostgreSQL-backed job-queue
libraries like `river` (Go) and `oban` (Elixir) implement, with more
polish around scheduling, uniqueness constraints, and observability. If you
outgrow a single-database queue — cross-database work distribution,
guaranteed ordering at very high throughput, or consumer groups — that's
the point at which a dedicated broker starts to earn its operational cost.
For most applications below that scale, the table you just built is
enough.*
