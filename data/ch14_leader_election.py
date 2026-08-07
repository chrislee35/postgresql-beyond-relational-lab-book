#!/usr/bin/env python3.12
"""
Chapter 14 — leader election among N Portsmith worker processes.

Every worker races for the same advisory lock key the instant it starts.
Exactly one gets it and becomes leader; the rest immediately find out they
lost and stand by. This is `pg_try_advisory_lock()` used for its other
common job: not "is this row taken," but "is *any* process already doing
this job city-wide."

Usage:
    python ch14_leader_election.py [N_WORKERS] [DSN]

    N_WORKERS defaults to 5. DSN defaults to "dbname=portsmith".
"""

import multiprocessing
import sys
import time

import psycopg

LEADER_LOCK_KEY = 99001


def worker(worker_id: int, dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s)", (LEADER_LOCK_KEY,))
            (got_lock,) = cur.fetchone()

            if got_lock:
                print(f"[worker-{worker_id}] elected leader — starting work")
                time.sleep(1.5)
                print(f"[worker-{worker_id}] leader work done, releasing")
                cur.execute("SELECT pg_advisory_unlock(%s)", (LEADER_LOCK_KEY,))
            else:
                print(f"[worker-{worker_id}] lost the race — standing by")


def main() -> None:
    n_workers = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    dsn = sys.argv[2] if len(sys.argv) > 2 else "dbname=portsmith"

    procs = [
        multiprocessing.Process(target=worker, args=(i, dsn))
        for i in range(1, n_workers + 1)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join()


if __name__ == "__main__":
    main()
