#!/usr/bin/env python3.12
"""
Chapter 18, Exercise 5 — consume the logical replication stream directly
from Python, bypassing CREATE SUBSCRIPTION entirely. psycopg (v3) has no
high-level replication API (unlike psycopg2's LogicalReplicationConnection),
so this talks the replication protocol at the libpq level: START_REPLICATION
puts the connection into COPY BOTH mode, and every message read back is
either an XLogData record (a decoded change) or a keepalive that must be
acknowledged with a standby status update, or the server eventually decides
the client is dead and closes the connection.

Uses the test_decoding output plugin rather than pgoutput (what CREATE
SUBSCRIPTION uses) because its output is human-readable text, not a binary
wire format meant for another PostgreSQL instance to parse.

Usage:
    python ch18_replication_stream.py [--seconds 15]

    Run this, then in another terminal make some changes to businesses or
    jobs in the portsmith database — INSERTs/UPDATEs/DELETEs all show up.
"""

import argparse
import struct
import time

import psycopg

SLOT_NAME = "demo_test_decoding"
DSN = "dbname=portsmith replication=database"


def send_standby_status(pgconn, write_lsn: int) -> None:
    now_usec = int(time.time() * 1_000_000) - 946_684_800_000_000  # since 2000-01-01
    msg = b"r" + struct.pack("!QQQQb", write_lsn, write_lsn, write_lsn, now_usec, 0)
    pgconn.put_copy_data(msg)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=15.0,
                         help="How long to listen before stopping (default: 15)")
    args = parser.parse_args()

    conn = psycopg.connect(DSN, autocommit=True)
    pgconn = conn.pgconn

    pgconn.exec_(
        f"START_REPLICATION SLOT {SLOT_NAME} LOGICAL 0/0".encode()
    )
    print(f"streaming from slot {SLOT_NAME!r} for {args.seconds}s ...\n")

    deadline = time.monotonic() + args.seconds
    last_lsn = 0

    while time.monotonic() < deadline:
        data = pgconn.get_copy_data(1)  # 1 = non-blocking
        if data[0] == 0:
            # no data ready right now
            pgconn.consume_input()
            time.sleep(0.1)
            continue
        payload = bytes(data[1])
        msg_type = payload[0:1]

        if msg_type == b"w":
            # XLogData: type(1) + wal_start(8) + wal_end(8) + send_time(8) + body
            wal_start = struct.unpack("!Q", payload[1:9])[0]
            body = payload[25:].decode("utf-8", errors="replace")
            last_lsn = max(last_lsn, wal_start)
            print(f"[{wal_start:X}] {body}")

        elif msg_type == b"k":
            # Primary keepalive: type(1) + wal_end(8) + send_time(8) + reply_requested(1)
            wal_end, _send_time, reply_requested = struct.unpack("!QQb", payload[1:18])
            last_lsn = max(last_lsn, wal_end)
            if reply_requested:
                send_standby_status(pgconn, last_lsn)

    pgconn.put_copy_end()
    conn.close()
    print("\nstopped listening.")


if __name__ == "__main__":
    main()
