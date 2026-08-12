# Chapter 19 — `pg_cron`: Scheduled Jobs Inside PostgreSQL

> *A cron job that lives outside the database has to be told, from
> scratch, how to reach it. A cron job that lives inside the database
> is already there.*

---

## Background

Every real system accumulates recurring maintenance: materialized
views that need refreshing, stalled work that needs reclaiming, stale
statistics that need updating. The traditional answer is an external
scheduler — OS-level `cron`, a workflow tool, a sidecar container —
that wakes up on its own timeline and connects in from outside.
**`pg_cron`** takes a different position: it runs *inside* PostgreSQL,
as a background process the postmaster manages like any other, reading
its schedule from an ordinary table (`cron.job`) and writing its
history to another (`cron.job_run_details`). Scheduling a job is a
`SELECT`, not a deployment.

That proximity is also exactly where this chapter's real gotchas come
from: a job that "lives inside PostgreSQL" doesn't skip the parts of
PostgreSQL that would normally apply to any other client connecting in
— it still needs a role, that role still needs privileges, and if a
password is required to connect as that role, `pg_cron`'s own
connection needs one too, from somewhere.

---

## The Scenario

| Object                    | Source                          | Purpose                                                    |
|----------------------------|-----------------------------------|---------------------------------------------------------------|
| `refresh_and_log(regclass)`  | Chapter 9                        | Scheduled hourly against `mv_sensor_daily`                     |
| `jobs` / `dead_letter_jobs`   | Chapter 3                        | Scheduled dead-letter sweep target                             |
| `sweep_stalled_jobs()`         | *(new)*                        | SQL port of `ch03_reclaim.py`'s stalled-job logic               |
| `guarded_demo_task()`           | *(new)*                        | Teaching-only procedure demonstrating advisory-lock overlap guards |
| `businesses_archive`             | Chapter 17, `portsmith_legacy` | Target of `cron.schedule_in_database()`                          |

---

## Exercise Goals

By the end of this chapter you will be able to:

- Install `pg_cron`, schedule a job, and know exactly which two real
  walls a first attempt hits before a job actually runs.
- Read `cron.job` and `cron.job_run_details` correctly — including a
  sorting mistake that's easy to make and easy to miss.
- Understand precisely what `pg_cron` already protects you from around
  overlapping runs, and what it doesn't — and use an advisory lock for
  the part it doesn't.
- Turn a script you'd otherwise run by hand into unattended, scheduled
  SQL.
- Schedule a job against a database other than the one `pg_cron`
  itself runs in.
- Modify, unschedule, and monitor jobs for failure, treating
  `cron.job_run_details` as a first-class thing to alert on.

---

## Installation

```bash
sudo apt install postgresql-16-cron
```

```
# postgresql.conf — shared across this chapter and the next two
shared_preload_libraries = 'pg_cron,pg_stat_statements,auto_explain'
cron.database_name = 'portsmith'
```

```bash
sudo systemctl restart postgresql
```

```sql
-- as postgres
CREATE EXTENSION pg_cron;
```

`cron.database_name` matters beyond just naming a database: it's where
`pg_cron`'s own launcher process runs and where `cron.job` /
`cron.job_run_details` live — Exercise 5's whole point is scheduling a
job that runs somewhere *other* than this one database.

---

## Exercises

---

### Exercise 1 — Installing `pg_cron` and Scheduling an Hourly Refresh

**1.1 — Schedule it**

Chapter 9's `refresh_and_log()` procedure already does everything an
hourly refresh needs — `pg_cron`'s job is just to call it on a
schedule instead of by hand:

```sql
SELECT cron.schedule('refresh-mv-sensor-daily', '0 * * * *',
    $$CALL refresh_and_log('mv_sensor_daily')$$);
```

```
ERROR:  permission denied for schema cron
```

Creating the extension doesn't hand every role access to its schema —
familiar territory by now (Chapter 17's `GRANT USAGE ON FOREIGN DATA
WRAPPER`, Chapter 10's `api` schema):

```sql
-- as postgres
GRANT USAGE ON SCHEMA cron TO chris;
GRANT SELECT ON cron.job, cron.job_run_details TO chris;
GRANT EXECUTE ON FUNCTION cron.schedule(text,text,text) TO chris;
```

A natural instinct is to grant every `cron.*` function chris might
need, all at once, in one `-c` call — which surfaces a real trap:

```
ERROR:  function cron.schedule_in_database(text, text, text, text) does not exist
```

That one function's signature didn't match this `pg_cron` version —
and because multiple `;`-separated statements sent as one `-c` string
run as a single implicit transaction, **the entire batch rolled back**,
including the `GRANT USAGE ON SCHEMA` that had appeared to succeed a
moment before. The fix is both a narrower ask and a more robust one —
grant every function in the schema by wildcard instead of enumerating
signatures you'd have to get exactly right:

```sql
-- as postgres, in one clean batch
GRANT USAGE ON SCHEMA cron TO chris;
GRANT SELECT ON cron.job, cron.job_run_details TO chris;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA cron TO chris;
```

```sql
SELECT cron.schedule('refresh-mv-sensor-daily', '* * * * *',  -- every minute, to verify quickly
    $$CALL refresh_and_log('mv_sensor_daily')$$);
```

```
 schedule
----------
        2
```

**1.2 — It "succeeds," but nothing actually runs**

```sql
SELECT jobid, status, return_message FROM cron.job_run_details WHERE jobid = 2;
```

```
 jobid | status |  return_message
-------+--------+-------------------
     2 | failed | connection failed
     2 | failed | connection failed
```

No further detail, and nothing in the PostgreSQL log even shows a
rejected authentication attempt — the connection is failing before it
gets that far. The reason: `pg_cron`'s launcher runs as the `postgres`
**OS** user, and to actually execute a job it opens its own new
connection to the target database, authenticating as whichever role
owns the job (`chris`). That's a different OS user than the one
`chris`'s own interactive `psql` sessions run as, and — same wall
Chapter 17 hit with `postgres_fdw` — a non-superuser connecting this
way needs a real password, which nothing here has supplied yet. The
fix is the standard one for a background process needing a password it
can't be prompted for: a `.pgpass` file, owned by the OS user running
PostgreSQL:

```bash
sudo -u postgres bash -c 'echo "localhost:5432:portsmith:chris:fdw-demo-password" >> ~/.pgpass && chmod 600 ~/.pgpass'
```

```sql
SELECT jobid, status, return_message, start_time, end_time FROM cron.job_run_details WHERE jobid = 2 ORDER BY runid DESC LIMIT 2;
```

```
 jobid |  status   | return_message |          start_time           |           end_time
-------+-----------+-----------------+-------------------------------+-------------------------------
     2 | succeeded | CALL            | 2026-08-09 23:27:00.015674-04 | 2026-08-09 23:27:02.030591-04
     2 | succeeded | CALL            | 2026-08-09 23:26:00.018446-04 | 2026-08-09 23:26:02.405988-04
```

Real, unattended, one-minute-apart refreshes, each taking about two
seconds. With it proven working, dial back to the real cadence:

```sql
SELECT cron.alter_job(2, schedule := '0 * * * *');
```

<img src="imgs/ch19_pgcron_architecture.svg" alt="cron.job holds the schedule; pg_cron's launcher process, running inside the postmaster, wakes up every minute, and for each due job opens a new connection authenticated as that job's role, requiring a .pgpass entry for the postgres OS user; it executes the job's command and logs the outcome to cron.job_run_details"/>

---

### Exercise 2 — Reading `cron.job` and `cron.job_run_details`

```sql
SELECT jobid, jobname, schedule, command, active FROM cron.job;
```

```
 jobid |         jobname         |  schedule  |                 command
-------+--------------------------+------------+-------------------------------------------
     2 | refresh-mv-sensor-daily  | 0 * * * *  | CALL refresh_and_log('mv_sensor_daily')
```

`cron.job_run_details` is the run history — and it has a sorting trap
worth knowing before it costs debugging time. The failed runs from
Exercise 1.2 never got a `start_time` at all (the connection never
opened far enough to set one):

```sql
SELECT jobid, status, start_time FROM cron.job_run_details ORDER BY start_time DESC LIMIT 5;
```

```
 jobid | status |          start_time
-------+--------+--------------------------------
     2 | failed |
     2 | failed |
     2 | failed |
     2 | succeeded | 2026-08-09 23:27:00.015674-04
     2 | succeeded | 2026-08-09 23:26:00.018446-04
```

`ORDER BY ... DESC` sorts `NULL` as the *largest* possible value by
default — so the oldest failures, the ones with no timestamp at all,
appear to be "first" ahead of genuinely recent successes. Anyone
scanning this for "what happened most recently" and trusting the sort
order would read yesterday's failures as more current than this
minute's successes. The fix is either an explicit `NULLS LAST`, or
sorting by `runid` (monotonic, never null) instead:

```sql
SELECT jobid, status, start_time FROM cron.job_run_details ORDER BY start_time DESC NULLS LAST LIMIT 5;
```

```
 jobid |  status   |          start_time
-------+-----------+--------------------------------
     2 | succeeded | 2026-08-09 23:27:00.015674-04
     2 | succeeded | 2026-08-09 23:26:00.018446-04
     2 | failed    |
     2 | failed    |
     2 | failed    |
```

---

### Exercise 3 — Overlap Prevention: What `pg_cron` Already Does, and What It Doesn't

**3.1 — A deliberately slow job**

```sql
CREATE OR REPLACE PROCEDURE guarded_demo_task(delay_seconds int DEFAULT 0)
LANGUAGE plpgsql AS $$
BEGIN
    IF NOT pg_try_advisory_lock(hashtext('guarded_demo_task')) THEN
        RAISE NOTICE 'already running, skipping this run';
        RETURN;
    END IF;
    PERFORM pg_sleep(delay_seconds);
    RAISE NOTICE 'did the work';
    PERFORM pg_advisory_unlock(hashtext('guarded_demo_task'));
END;
$$;

SELECT cron.schedule('guarded-demo', '* * * * *', $$CALL guarded_demo_task(75)$$);
```

A 75-second job on a 60-second schedule guarantees overlap — the
question is what `pg_cron` actually does about it.

**3.2 — `pg_cron` already refuses to double-run the same job**

```
LOG:  cron job 3 starting: CALL guarded_demo_task(75)      -- 23:28:00
LOG:  cron job 3 COMMAND completed: CALL                    -- 23:29:15
LOG:  cron job 3 starting: CALL guarded_demo_task(75)       -- 23:29:15, immediately after
```

There's no log line for a job 3 start at 23:29:00 at all — `pg_cron`
noticed the previous run of this exact `jobid` was still going and
simply didn't launch a second one for that tick. It doesn't queue the
missed tick either: the next run starts the instant a slot frees, at
23:29:15, not at the next minute boundary. Left running long enough,
the schedule drifts further from the clock with every overlap, a real
and worth-knowing side effect on its own.

**3.3 — What that protection doesn't cover**

`pg_cron`'s serialization is scoped to one `jobid`. It says nothing
about the same underlying task being triggered a second way — a
different job entry calling the same procedure, or a human running it
by hand. While job 3 was mid-run:

```sql
CALL guarded_demo_task(0);   -- from an ordinary psql session, not cron at all
```

```
NOTICE:  already running, skipping this run
CALL
```

*This* is what the advisory lock actually earns its keep for — not the
same-`jobid` case `pg_cron` already handles, but any other path that
might reach the same resource concurrently. The lock is keyed on the
resource (`guarded_demo_task`, or in a real refresh job's case,
probably the matview's name), not on the job — which is exactly what
lets it catch a case `pg_cron`'s own per-job serialization structurally
can't.

<img src="imgs/ch19_overlap_sequence.svg" alt="Timeline: at minute 0 pg_cron starts guarded_demo_task, which acquires an advisory lock and sleeps 75 seconds; at minute 1 pg_cron's own scheduled tick for the same job is silently skipped since the previous run is still active; partway through, a manually issued CALL to the same procedure from an unrelated session immediately fails to acquire the lock and returns; at 75 seconds the first run finishes, releases the lock, and pg_cron immediately starts the next run rather than waiting for the next minute boundary"/>

```sql
SELECT cron.unschedule('guarded-demo');
```

---

### Exercise 4 — A Scheduled Dead-Letter Sweep

Chapter 3 built `ch03_reclaim.py` to requeue stalled jobs and dead-letter
the ones that exhausted their retries — run by hand, or "on a schedule
(see Chapter 19)," per its own docstring at the time. That schedule is
this exercise: the same logic, as a SQL function `pg_cron` can call
directly, no external process required.

**4.1 — Port the script's logic to SQL**

```sql
CREATE OR REPLACE FUNCTION sweep_stalled_jobs(p_timeout interval DEFAULT interval '30 minutes')
RETURNS TABLE(requeued int, dead_lettered int)
LANGUAGE plpgsql AS $$
DECLARE
    r RECORD;
    v_requeued int := 0;
    v_dead_lettered int := 0;
    v_error text;
BEGIN
    FOR r IN
        SELECT id, job_type, attempts, max_attempts, claimed_by, heartbeat_at
        FROM jobs
        WHERE status = 'in_progress' AND heartbeat_at < now() - p_timeout
        ORDER BY id
    LOOP
        v_error := format('stalled: no heartbeat since %s (last claimed by %s)', r.heartbeat_at, r.claimed_by);
        IF r.attempts >= r.max_attempts THEN
            WITH failed AS (
                DELETE FROM jobs WHERE id = r.id
                RETURNING id, job_type, payload, priority, attempts, max_attempts, created_at
            )
            INSERT INTO dead_letter_jobs (id, job_type, payload, priority, attempts, max_attempts, created_at, last_error)
            SELECT id, job_type, payload, priority, attempts, max_attempts, created_at, v_error FROM failed;
            v_dead_lettered := v_dead_lettered + 1;
        ELSE
            UPDATE jobs SET status = 'queued', claimed_at = NULL, claimed_by = NULL,
                            heartbeat_at = NULL, last_error = v_error
            WHERE id = r.id;
            v_requeued := v_requeued + 1;
        END IF;
    END LOOP;
    RETURN QUERY SELECT v_requeued, v_dead_lettered;
END;
$$;
```

**4.2 — Prove both branches work**

```sql
INSERT INTO jobs (job_type, payload, status, priority, attempts, max_attempts, claimed_at, claimed_by, heartbeat_at)
VALUES ('demo_stall_requeue',    '{}', 'in_progress', 5, 1, 3, now() - interval '40 minutes', 'worker-demo', now() - interval '35 minutes'),
       ('demo_stall_deadletter', '{}', 'in_progress', 5, 3, 3, now() - interval '40 minutes', 'worker-demo', now() - interval '35 minutes');

SELECT * FROM sweep_stalled_jobs();
```

```
 requeued | dead_lettered
----------+----------------
        1 |              1
```

```sql
SELECT id, status FROM jobs WHERE job_type = 'demo_stall_requeue';
SELECT id, last_error FROM dead_letter_jobs WHERE job_type = 'demo_stall_deadletter';
```

```
 id |   status
----+-----------
 51 | queued

 id |                                       last_error
----+-------------------------------------------------------------------------------------------
 52 | stalled: no heartbeat since 2026-08-09 21:47:19.767251-04 (last claimed by worker-demo)
```

Exactly the two outcomes `ch03_reclaim.py` produced by hand — attempts
remaining gets requeued, retries exhausted gets dead-lettered, with a
descriptive `last_error` either way.

**4.3 — Schedule it**

```sql
SELECT cron.schedule('sweep-stalled-jobs', '*/5 * * * *', $$SELECT sweep_stalled_jobs()$$);
```

Verified live with a fresh stalled job and a one-minute test schedule
before settling on every five minutes: `job_run_details` showed
`status: succeeded`, `return_message: 1 row`, and the planted job's
`status` really did flip back to `queued` — the scheduled path produces
the same result as the manual call in 4.2, just unattended.

---

### Exercise 5 — `cron.schedule_in_database()`

`cron.database_name = 'portsmith'` means `pg_cron`'s launcher itself
lives there — every job scheduled with plain `cron.schedule()` runs
against `portsmith` by definition. `cron.schedule_in_database()` is the
escape hatch: a job that runs against a **different** database
entirely, using the same underlying launcher.

```sql
SELECT cron.schedule_in_database('legacy-analyze', '0 4 * * *',
    'ANALYZE businesses_archive;', 'portsmith_legacy');
```

Verified against `portsmith_legacy` — Chapter 17's second database —
by checking the one thing `ANALYZE` actually changes:

```sql
-- in portsmith_legacy, before
SELECT last_analyze FROM pg_stat_user_tables WHERE relname = 'businesses_archive';
```

```
 last_analyze
---------------
 (null)
```

```sql
-- in portsmith, briefly rescheduled to every 2 minutes to verify quickly
SELECT cron.alter_job((SELECT jobid FROM cron.job WHERE jobname = 'legacy-analyze'), schedule := '*/2 * * * *');
```

```sql
-- in portsmith_legacy, ~2 minutes later
SELECT last_analyze FROM pg_stat_user_tables WHERE relname = 'businesses_archive';
```

```
          last_analyze
-------------------------------
 2026-08-09 23:28:00.039363-04
```

A real, verified timestamp — `pg_cron`'s single launcher process,
still physically running inside `portsmith`, reached across and
executed SQL against a completely different database. Reset to a
realistic once-daily cadence once proven:

```sql
SELECT cron.alter_job((SELECT jobid FROM cron.job WHERE jobname = 'legacy-analyze'), schedule := '0 4 * * *');
```

---

### Exercise 6 — Modifying, Unscheduling, and Monitoring for Failure

**6.1 — `cron.alter_job()` and `cron.unschedule()`**

Both already used for real, twice each, in Exercises 1, 3, and 5 —
`alter_job` to change a schedule without dropping and recreating the
job (its history in `job_run_details` stays intact, keyed by the same
`jobid`), `unschedule` to remove one outright.

**6.2 — A job that genuinely fails**

```sql
SELECT cron.schedule('broken-demo-job', '* * * * *', 'SELECT * FROM this_table_does_not_exist;');
```

```sql
SELECT status, return_message FROM cron.job_run_details ORDER BY runid DESC LIMIT 1;
```

```
 status |                       return_message
--------+--------------------------------------------------------------
 failed | ERROR:  relation "this_table_does_not_exist" does not exist
        | LINE 1: SELECT * FROM this_table_does_not_exist;
        |                       ^
```

The real error text, captured and stored — `pg_cron` doesn't swallow
failures, it logs exactly what PostgreSQL would have said to an
interactive session running the same statement.

```sql
SELECT cron.unschedule('broken-demo-job');
```

**6.3 — The monitoring query this chapter has been building toward**

```sql
SELECT jobid, status, return_message, start_time
FROM   cron.job_run_details
WHERE  status = 'failed'
ORDER  BY start_time DESC NULLS LAST
LIMIT  10;
```

The same `NULLS LAST` fix from Exercise 2, now doing real work: a
recurring check for exactly this query, scheduled itself (or wired into
existing alerting), is the difference between a scheduled job failing
silently for weeks and someone finding out the same day.

---

## Summary — What You Should Now Know

| Concept | What it does |
|---------|----------------|
| `cron.schedule(name, schedule, command)` | Registers a job — needs `USAGE` on schema `cron` plus `EXECUTE` on its functions |
| `.pgpass` for the PostgreSQL OS user | Required for `pg_cron`'s background connection to authenticate as a non-superuser job owner |
| `cron.job` / `cron.job_run_details` | Schedule and run history — sort `job_run_details` by `runid` or with `NULLS LAST`, never a bare `start_time DESC` |
| Same-`jobid` overlap | Already prevented by `pg_cron` itself — a missed tick isn't queued, the next run starts immediately once a slot frees |
| Cross-path overlap (different jobs, or a manual call) | **Not** covered by `pg_cron` — needs its own `pg_try_advisory_lock`, keyed on the resource, not the job |
| `cron.schedule_in_database(name, schedule, command, database)` | Runs against a database other than `cron.database_name` |
| `cron.alter_job()` / `cron.unschedule()` | Modify a job in place (history preserved) or remove it entirely |
| `cron.job_run_details.status = 'failed'` | A real, monitorable signal — the same shape of query worth alerting on, not just reading by hand |

**The key design insight** from this chapter is that `pg_cron` gives
you exactly one guarantee for free — a job won't overlap with its own
previous run — and that guarantee is narrower than it first sounds.
Everything else a production scheduler needs (locking scoped to the
actual shared resource, credentials for the connection it opens on
your behalf, monitoring that actually gets read) is the same
responsibility it would be with any external scheduler, just moved
inside a table instead of a config file.

---

*Going further: Chapter 20's `pg_stat_statements` and `auto_explain` —
already sharing this chapter's `shared_preload_libraries` line — turn
the same kind of "what actually happened" question this chapter asked
of `cron.job_run_details` onto query performance instead of scheduled
jobs. And Exercise 4's `sweep_stalled_jobs()` is worth pairing with
Chapter 18's own "going further" note: a second `pg_cron` job that
watches `pg_replication_slots` for a slot whose `confirmed_flush_lsn`
has stopped advancing is the exact same "scheduled health check" shape
applied to replication instead of the job queue.*
