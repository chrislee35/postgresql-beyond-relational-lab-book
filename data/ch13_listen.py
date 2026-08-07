#!/usr/bin/env python3.12
"""
Chapter 13 — Portsmith permit-status staff dashboard (a LISTEN client).

Connects, subscribes to one or more channels, and prints every job status
change as it arrives — a live dashboard instead of a script polling `jobs`
on a timer. Exercise 4 introduces per-job-type channels; pass more than one
channel name to LISTEN on all of them at once.

Usage:
    python ch13_listen.py [CHANNEL ...] [--dsn DSN] [--timeout SECONDS]

    Defaults to listening on "job_status_changes". With no --timeout, runs
    until interrupted (Ctrl-C).
"""

import argparse
import json

import psycopg


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("channels", nargs="*", default=["job_status_changes"])
    parser.add_argument("--dsn", default="dbname=portsmith")
    parser.add_argument("--timeout", type=float, default=None,
                         help="Stop listening after this many idle seconds (default: run forever)")
    args = parser.parse_args()

    with psycopg.connect(args.dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            for channel in args.channels:
                cur.execute(f"LISTEN {channel};")
                print(f"listening on {channel!r} …")

        try:
            for notice in conn.notifies(timeout=args.timeout):
                job = json.loads(notice.payload)
                print(
                    f"[{notice.channel}] job {job['job_id']} ({job['job_type']}): "
                    f"{job['old_status']} -> {job['new_status']}"
                )
        except KeyboardInterrupt:
            print("\nstopped.")


if __name__ == "__main__":
    main()
