#!/usr/bin/env python3.12
"""
Chapter 3 worker — claims and processes jobs from the Portsmith permit queue.

Demonstrates the atomic claim pattern (`FOR UPDATE SKIP LOCKED`), periodic
heartbeats for longer-running jobs, and the retry / dead-letter path when a
job's simulated processing fails.

Run two or more copies at once (separate terminals, or backgrounded with
`&`) to see `FOR UPDATE SKIP LOCKED` prevent two workers from ever claiming
the same row:

    python ch03_worker.py --worker-id w1 &
    python ch03_worker.py --worker-id w2 &

Usage:
    python ch03_worker.py [--worker-id ID] [--max-jobs N] [--once]
                           [--fail-rate 0.15] [--min-seconds 0.3]
                           [--max-seconds 1.2] [DSN]

    DSN defaults to "dbname=portsmith".
"""

import argparse
import os
import random
import time

import psycopg

CLAIM_SQL = """
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
       claimed_by   = %(worker_id)s,
       heartbeat_at = now(),
       attempts     = attempts + 1
FROM   next_job
WHERE  jobs.id = next_job.id
RETURNING jobs.id, jobs.job_type, jobs.payload, jobs.attempts, jobs.max_attempts;
"""

HEARTBEAT_SQL = "UPDATE jobs SET heartbeat_at = now() WHERE id = %s"

COMPLETE_SQL = """
UPDATE jobs
SET    status = 'completed', completed_at = now()
WHERE  id = %s
"""

REQUEUE_SQL = """
UPDATE jobs
SET    status       = 'queued',
       claimed_at   = NULL,
       claimed_by   = NULL,
       heartbeat_at = NULL,
       last_error   = %s
WHERE  id = %s
"""

DEAD_LETTER_SQL = """
WITH failed AS (
    DELETE FROM jobs WHERE id = %(id)s
    RETURNING id, job_type, payload, priority, attempts, max_attempts, created_at
)
INSERT INTO dead_letter_jobs
    (id, job_type, payload, priority, attempts, max_attempts, created_at, last_error)
SELECT id, job_type, payload, priority, attempts, max_attempts, created_at, %(last_error)s
FROM   failed
"""


def process_job(cur, worker_id: str, job: dict, args: argparse.Namespace) -> None:
    job_id, job_type, payload, attempts, max_attempts = job

    work_seconds = random.uniform(args.min_seconds, args.max_seconds)
    print(
        f"[{worker_id}] claimed job {job_id} ({job_type}, attempt "
        f"{attempts}/{max_attempts}): {payload.get('application_id')} — "
        f"processing for {work_seconds:.2f}s"
    )

    # Send a heartbeat partway through, the way a real long-running job
    # would, so the reclaim sweep (Exercise 4) can tell this worker is
    # still alive.
    elapsed = 0.0
    heartbeat_every = 2.0
    while elapsed < work_seconds:
        step = min(heartbeat_every, work_seconds - elapsed)
        time.sleep(step)
        elapsed += step
        cur.execute(HEARTBEAT_SQL, (job_id,))
        cur.connection.commit()

    if random.random() < args.fail_rate:
        error = f"simulated failure processing {job_type} on attempt {attempts}"
        if attempts >= max_attempts:
            print(f"[{worker_id}] job {job_id} exhausted retries — dead-lettering")
            cur.execute(DEAD_LETTER_SQL, {"id": job_id, "last_error": error})
        else:
            print(f"[{worker_id}] job {job_id} failed — requeuing (attempt {attempts})")
            cur.execute(REQUEUE_SQL, (error, job_id))
    else:
        print(f"[{worker_id}] job {job_id} completed")
        cur.execute(COMPLETE_SQL, (job_id,))

    cur.connection.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dsn", nargs="?", default="dbname=portsmith")
    parser.add_argument("--worker-id", default=f"worker-{os.getpid()}")
    parser.add_argument("--max-jobs", type=int, default=None,
                         help="Stop after processing this many jobs (default: drain the queue)")
    parser.add_argument("--once", action="store_true",
                         help="Claim and process a single job, then exit")
    parser.add_argument("--fail-rate", type=float, default=0.15,
                         help="Probability a claimed job simulates a failure (default 0.15)")
    parser.add_argument("--min-seconds", type=float, default=0.3)
    parser.add_argument("--max-seconds", type=float, default=1.2)
    args = parser.parse_args()

    if args.once:
        args.max_jobs = 1

    print(f"[{args.worker_id}] connecting to: {args.dsn}")
    processed = 0
    with psycopg.connect(args.dsn) as conn:
        with conn.cursor() as cur:
            while args.max_jobs is None or processed < args.max_jobs:
                cur.execute(CLAIM_SQL, {"worker_id": args.worker_id})
                row = cur.fetchone()
                conn.commit()

                if row is None:
                    print(f"[{args.worker_id}] queue empty — stopping")
                    break

                job_id, job_type, payload, attempts, max_attempts = row
                process_job(
                    cur, args.worker_id,
                    (job_id, job_type, payload, attempts, max_attempts),
                    args,
                )
                processed += 1

    print(f"[{args.worker_id}] done — processed {processed} job(s)")


if __name__ == "__main__":
    main()
