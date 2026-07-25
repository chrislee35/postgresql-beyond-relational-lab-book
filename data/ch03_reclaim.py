#!/usr/bin/env python3.12
"""
Chapter 3 maintenance sweep — reclaims stalled jobs and dead-letters jobs
that have exhausted their retries.

A job is "stalled" if it has been `in_progress` for longer than
`--timeout` seconds without a heartbeat update — the worker that claimed it
crashed, lost its database connection, or was killed mid-job. Stalled jobs
with attempts remaining are put back in the queue; stalled jobs that have
already used their last attempt are moved to `dead_letter_jobs`.

Usage:
    python ch03_reclaim.py [--timeout 30] [DSN]

Safe to run repeatedly — each run only touches rows that are actually
stalled. Intended to run on a schedule (see Chapter 19 — pg_cron) or be
invoked by hand between exercises.
"""

import argparse

import psycopg

FIND_STALLED_SQL = """
SELECT id, job_type, attempts, max_attempts, claimed_by, heartbeat_at
FROM   jobs
WHERE  status = 'in_progress'
  AND  heartbeat_at < now() - (%(timeout_seconds)s || ' seconds')::interval
ORDER  BY id
"""

REQUEUE_SQL = """
UPDATE jobs
SET    status       = 'queued',
       claimed_at   = NULL,
       claimed_by   = NULL,
       heartbeat_at = NULL,
       last_error   = %(error)s
WHERE  id = %(id)s
"""

DEAD_LETTER_SQL = """
WITH failed AS (
    DELETE FROM jobs WHERE id = %(id)s
    RETURNING id, job_type, payload, priority, attempts, max_attempts, created_at
)
INSERT INTO dead_letter_jobs
    (id, job_type, payload, priority, attempts, max_attempts, created_at, last_error)
SELECT id, job_type, payload, priority, attempts, max_attempts, created_at, %(error)s
FROM   failed
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dsn", nargs="?", default="dbname=portsmith")
    parser.add_argument("--timeout", type=int, default=30,
                         help="Seconds without a heartbeat before a job is considered stalled")
    args = parser.parse_args()

    print(f"Connecting to: {args.dsn}")
    requeued = 0
    dead_lettered = 0

    with psycopg.connect(args.dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(FIND_STALLED_SQL, {"timeout_seconds": args.timeout})
            stalled = cur.fetchall()

            if not stalled:
                print(f"No jobs stalled beyond {args.timeout}s — nothing to do.")
                return

            for job_id, job_type, attempts, max_attempts, claimed_by, heartbeat_at in stalled:
                error = (
                    f"stalled: no heartbeat since {heartbeat_at} "
                    f"(last claimed by {claimed_by})"
                )
                if attempts >= max_attempts:
                    cur.execute(DEAD_LETTER_SQL, {"id": job_id, "error": error})
                    dead_lettered += 1
                    print(f"  job {job_id} ({job_type}) exhausted retries — dead-lettered")
                else:
                    cur.execute(REQUEUE_SQL, {"id": job_id, "error": error})
                    requeued += 1
                    print(f"  job {job_id} ({job_type}) stalled — requeued (attempt {attempts})")

        conn.commit()

    print(f"\nDone: {requeued} requeued, {dead_lettered} dead-lettered.")


if __name__ == "__main__":
    main()
