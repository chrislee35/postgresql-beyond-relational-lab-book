# Chapter 18 — Logical Replication and Change Data Capture

> *A foreign data wrapper asks a question and waits for an answer,
> every time. A subscription asks once, then never stops listening.*

---

## Background

Chapter 17 reached across to another database at query time, live,
through `postgres_fdw` — every `SELECT` was a real network round-trip,
answered fresh. **Logical replication** solves a different problem: it
streams every row-level change out of PostgreSQL, continuously, so a
second database ends up with its own independent, current copy —
queryable locally, with its own indexes, at none of the join-time
latency an FDW pays.

The mechanism underneath is the same **write-ahead log (WAL)** every
PostgreSQL install already produces for crash recovery, decoded into a
stream of logical changes (`INSERT`, `UPDATE`, `DELETE`) instead of the
physical byte-level records **physical replication** (streaming
standbys) sends. Two pieces make it work:

- **A publication** — created on the source ("publisher"), naming which
  tables (and optionally which columns, and which rows) should be
  streamed out.
- **A subscription** — created on the destination ("subscriber"),
  pointing at a publisher and a publication, pulling changes in and
  applying them.

Underneath every subscription is a **replication slot** — a durable
bookmark on the publisher that says "don't let WAL older than this be
recycled, a consumer still needs it." That's the whole safety
contract: as long as the slot exists, the publisher retains whatever
WAL the subscriber hasn't confirmed yet, even across a subscriber
outage. It's also the whole *risk*: a slot nobody's draining anymore
retains WAL forever, silently filling disk.

<img src="imgs/ch18_pub_sub_architecture.svg" alt="Portsmith (publisher) writes WAL; a replication slot named portsmith_sub using the pgoutput plugin feeds CREATE SUBSCRIPTION on portsmith_legacy, applying changes to its own local businesses and jobs tables; a second, independent replication slot named demo_test_decoding using the test_decoding plugin feeds a Python script reading the replication protocol directly with psycopg, printing human-readable change records"/>

This chapter builds both paths off the same publisher: the standard
`CREATE SUBSCRIPTION` route or the second row shows the raw protocol,
read directly from Python.

---

## The Scenario

| Object                    | Lives in                                | Purpose                                                         |
|---------------------------|------------------------------------------|-------------------------------------------------------------------|
| `portsmith_pub`             | `portsmith` (publisher)                   | Publication covering `businesses` (partial columns, row-filtered) and `jobs` (all columns) |
| `portsmith_sub`              | `portsmith_legacy` (subscriber)           | Subscription consuming `portsmith_pub`, backed by a slot of the same name on the publisher |
| `businesses` / `jobs`         | Both databases                           | Chapter 1 / Chapter 3's tables — subscriber's copies are narrower, no PostGIS geometry, no generated columns |
| `demo_test_decoding`          | `portsmith` (publisher)                   | A second, independent slot, read directly by Python instead of by a subscription |
| `data/ch18_replication_stream.py` | *(new)*                            | Consumes `demo_test_decoding` at the wire protocol level |

`portsmith_legacy` is the same second database Chapter 17 created —
reused here as the subscriber, on the same PostgreSQL instance as the
publisher. That choice is convenient for a lab environment and, as
Exercise 2 shows, not free: it creates a real deadlock a genuinely
separate instance wouldn't.

---

## Exercise Goals

By the end of this chapter you will be able to:

- Turn on logical replication, create a publication scoped to specific
  tables and columns, and understand what a replication slot actually
  guarantees.
- Stand up a subscription, understand exactly why doing so on the same
  instance as the publisher can deadlock, and know the real fix.
- Read `pg_replication_slots` and `pg_stat_replication` to check lag and
  confirm a subscriber is actually keeping up.
- Filter a publication by row, and navigate the replica identity
  requirements that come with filtering on a non-key column.
- Consume the logical replication protocol directly from Python,
  without `CREATE SUBSCRIPTION` at all.
- Describe how Debezium turns this same protocol into a Kafka event
  stream — the production-grade version of Exercise 5's hand-rolled
  script.

---

## Installation

### `wal_level = logical`

Logical decoding needs more information in the WAL than PostgreSQL
writes by default:

```sql
-- as postgres, in postgresql.conf, or:
ALTER SYSTEM SET wal_level = 'logical';
```

```
# postgresql.conf
wal_level = logical    # (change requires restart)
```

Like `shared_preload_libraries` in the previous two chapters' setup,
this needs a full restart, not just a config reload:

```bash
sudo systemctl restart postgresql
```

```sql
SHOW wal_level;
```

```
 wal_level
-----------
 logical
```

No other extension is needed — logical replication is built into core
PostgreSQL.

---

## Loading the Data

`portsmith_legacy` needs matching structure for whatever gets
published, but *matching* doesn't mean *identical*. `businesses` in
`portsmith` carries a PostGIS `geometry` column and a generated
`tsvector` — neither makes sense to replicate here: `portsmith_legacy`
has no PostGIS extension installed, and generated columns aren't sent
over logical replication anyway (PostgreSQL 16 excludes them from the
wire format by default; a subscriber with the same generated column
would just compute its own value locally, and one without it simply
doesn't have it). So the subscriber's `businesses` is deliberately
narrower — the domain and enum types still have to match, since those
govern the columns that *are* published:

```sql
-- in portsmith_legacy
CREATE DOMAIN positive_integer AS integer CHECK (VALUE > 0);
CREATE TYPE job_status AS ENUM ('queued','on_hold','in_progress','completed','failed','cancelled');

CREATE TABLE businesses (
    id             integer PRIMARY KEY,
    name           text NOT NULL,
    address        text NOT NULL,
    neighbourhood  text NOT NULL,
    details        jsonb NOT NULL,
    employee_count positive_integer
);

CREATE TABLE jobs (
    id            bigint PRIMARY KEY,
    job_type      text NOT NULL,
    payload       jsonb NOT NULL,
    status        job_status NOT NULL DEFAULT 'queued',
    priority      smallint NOT NULL DEFAULT 5,
    attempts      integer NOT NULL DEFAULT 0,
    max_attempts  integer NOT NULL DEFAULT 3,
    created_at    timestamptz NOT NULL DEFAULT clock_timestamp(),
    claimed_at    timestamptz,
    claimed_by    text,
    heartbeat_at  timestamptz,
    completed_at  timestamptz,
    last_error    text
);
```

`jobs` is published in full — no PostGIS-shaped complications there, so
its subscriber copy is a plain structural match.

---

## Exercises

---

### Exercise 1 — `wal_level` and a Publication

With `wal_level` already set to `logical`, creating a publication is
the easy part:

```sql
-- in portsmith
CREATE PUBLICATION portsmith_pub
    FOR TABLE businesses (id, name, address, neighbourhood, details, employee_count), jobs;
```

```
CREATE PUBLICATION
```

`businesses` uses a **column list** — PostgreSQL 15+ lets a publication
name a subset of a table's columns, not just a subset of its rows.
Here that's what makes the narrower subscriber schema above valid at
all: `geom` and `search_vector` are simply never offered, so
`portsmith_legacy` never needs to know they exist.

```sql
SELECT pubname, puballtables FROM pg_publication;
SELECT schemaname, tablename, attnames FROM pg_publication_tables WHERE pubname = 'portsmith_pub';
```

```
       pubname       | puballtables
----------------------+---------------
 portsmith_pub        | f

 schemaname | tablename  |                          attnames
------------+------------+--------------------------------------------------------------
 public     | businesses | {id,name,address,neighbourhood,details,employee_count}
 public     | jobs       | {id,job_type,payload,status,priority,attempts,max_attempts,created_at,claimed_at,claimed_by,heartbeat_at,completed_at,last_error}
```

---

### Exercise 2 — A Subscription, and a Deadlock Worth Understanding

**2.1 — Two permission gates, back to back**

```sql
-- in portsmith_legacy
CREATE SUBSCRIPTION portsmith_sub
    CONNECTION 'host=localhost dbname=portsmith user=chris password=fdw-demo-password'
    PUBLICATION portsmith_pub;
```

```
ERROR:  permission denied to create subscription
DETAIL:  Only roles with privileges of the "pg_create_subscription" role may create subscriptions.
```

A PostgreSQL 16 hardening measure — creating a subscription can execute
arbitrary code on the publisher's behalf (via the connection string), so
it's gated behind its own predefined role, separate from ordinary table
privileges:

```sql
-- as postgres
GRANT pg_create_subscription TO chris;
```

Retrying reaches a second, unrelated gate:

```
ERROR:  could not connect to the publisher: connection to server at "localhost" (127.0.0.1), port 5432 failed: FATAL:  permission denied to start WAL sender
DETAIL:  Only roles with the REPLICATION attribute may start a WAL sender process.
```

`pg_create_subscription` governs creating the *local* subscription
object; actually connecting to the publisher and opening a replication
connection is gated separately, by a role *attribute* (like `LOGIN` or
`CREATEDB`), not a grantable role membership:

```sql
-- as postgres
ALTER ROLE chris REPLICATION;
```

**2.2 — The deadlock**

Retrying again:

```sql
CREATE SUBSCRIPTION portsmith_sub
    CONNECTION 'host=localhost dbname=portsmith user=chris password=fdw-demo-password'
    PUBLICATION portsmith_pub;
```

...hangs. No error, no completion — indefinitely. From another session:

```sql
SELECT l.pid, l.mode, l.granted, a.query
FROM   pg_locks l JOIN pg_stat_activity a ON a.pid = l.pid
WHERE  l.locktype = 'transactionid';
```

```
  pid   |     mode      | granted |                          query
--------+---------------+---------+------------------------------------------------------------
 322315 | ExclusiveLock | t       | CREATE SUBSCRIPTION portsmith_sub CONNECTION ... ;
 322316 | ShareLock     | f       | CREATE_REPLICATION_SLOT "portsmith_sub" LOGICAL pgoutput (SNAPSHOT 'nothing')
```

`CREATE SUBSCRIPTION` (pid 322315), by default, tries to create its
replication slot as part of its own work — and creating a *logical*
slot needs a consistent snapshot, which means waiting for every other
currently-running transaction in the cluster to finish. Because the
publisher and subscriber are the **same PostgreSQL instance** here, the
walsender process it spawns to build that snapshot (pid 322316) ends up
waiting on `CREATE SUBSCRIPTION`'s *own*, still-open transaction — which
can't finish until the slot creation it's waiting on returns. A true
self-deadlock, specific to same-instance publisher/subscriber setups; a
genuinely separate PostgreSQL server wouldn't have this problem, since
its walsender would never need to wait on a transaction ID that belongs
to a different cluster entirely.

Cancel it and clean up:

```sql
SELECT pg_cancel_backend(322315);
```

**2.3 — The real fix: create the slot first, separately**

```sql
-- in portsmith (the publisher)
SELECT pg_create_logical_replication_slot('portsmith_sub', 'pgoutput');
```

```
 pg_create_logical_replication_slot
-------------------------------------
 (portsmith_sub,0/C697AEB8)
```

```sql
-- in portsmith_legacy
CREATE SUBSCRIPTION portsmith_sub
    CONNECTION 'host=localhost dbname=portsmith user=chris password=fdw-demo-password'
    PUBLICATION portsmith_pub
    WITH (create_slot = false, slot_name = 'portsmith_sub');
```

```
CREATE SUBSCRIPTION
```

With the slot already sitting there, `CREATE SUBSCRIPTION` has nothing
left to wait on — it just starts the initial data copy immediately:

```sql
SELECT count(*) FROM businesses;  -- in portsmith_legacy
SELECT count(*) FROM jobs;
```

```
 count      count
-------    -------
    48        48
```

**2.4 — Real-time replication**

```sql
-- in portsmith
INSERT INTO businesses (name, address, neighbourhood, details, employee_count)
VALUES ('Harbor Light Cafe', '12 Quay Street', 'Old Town', '{"category":"restaurant"}', 6)
RETURNING id;
```

```sql
-- moments later, in portsmith_legacy
SELECT id, name, employee_count FROM businesses WHERE name = 'Harbor Light Cafe';
```

```
 id |       name        | employee_count
----+--------------------+-----------------
 49 | Harbor Light Cafe  |               6
```

No polling, no manual refresh — the row is there because a walsender
process pushed it the moment the `INSERT` committed on the publisher.

---

### Exercise 3 — Inspecting Slot and Replication State

```sql
-- in portsmith
SELECT slot_name, plugin, slot_type, database, active, restart_lsn, confirmed_flush_lsn
FROM pg_replication_slots;
```

```
   slot_name   |  plugin  | slot_type | database  | active | restart_lsn | confirmed_flush_lsn
---------------+----------+-----------+-----------+--------+-------------+----------------------
 portsmith_sub | pgoutput | logical   | portsmith | t      | 0/C698E388  | 0/C698E3C0
```

`pg_stat_replication` is the live, moment-to-moment view — but querying
it as `chris` at first shows an odd, mostly-empty row:

```sql
SELECT application_name, state, sent_lsn, replay_lsn, replay_lag FROM pg_stat_replication;
```

```
 application_name | state | sent_lsn | replay_lsn | replay_lag
------------------+-------+----------+------------+------------
 portsmith_sub    |       |          |            |
```

The row exists — `chris` can see *that* a replication connection is
active — but the detail columns (`state`, every LSN, lag) are hidden
unless the querying role is a superuser or holds `pg_monitor`:

```sql
-- as postgres
GRANT pg_monitor TO chris;
```

```sql
SELECT application_name, state, sent_lsn, write_lsn, flush_lsn, replay_lsn, replay_lag
FROM pg_stat_replication;
```

```
 application_name |   state   |  sent_lsn  | write_lsn  | flush_lsn  | replay_lsn |   replay_lag
------------------+-----------+------------+------------+------------+------------+------------------
 portsmith_sub    | streaming | 0/C698EFC8 | 0/C698EFC8 | 0/C698EFC8 | 0/C698EFC8 | 00:00:00.00025
```

`state: streaming` and a quarter-millisecond `replay_lag` — on
`localhost`, replication lag is essentially the cost of a context
switch. The same query against a subscriber across a real network would
show it rising under load, which is exactly what an operator watches
this view for.

---

### Exercise 4 — Row-Filtered Publication: Active Businesses Only

**4.1 — Give `businesses` something to filter on**

```sql
-- in portsmith
ALTER TABLE businesses ADD COLUMN active boolean NOT NULL DEFAULT true;
UPDATE businesses SET active = false WHERE id IN (6, 8, 14);  -- closed since the seed data was written
```

```sql
-- in portsmith_legacy, so the published column list still has somewhere to land
ALTER TABLE businesses ADD COLUMN active boolean NOT NULL DEFAULT true;
```

**4.2 — Add the filter**

```sql
-- in portsmith
ALTER PUBLICATION portsmith_pub
    SET TABLE businesses (id, name, address, neighbourhood, details, employee_count, active) WHERE (active = true),
        jobs;
```

```
ALTER PUBLICATION
```

**4.3 — A refresh alone doesn't retroactively resync**

```sql
-- in portsmith_legacy
ALTER SUBSCRIPTION portsmith_sub REFRESH PUBLICATION WITH (copy_data = true);
SELECT count(*) FROM businesses;
```

```
 count
-------
    49
```

Still 49 — the three closed businesses are still sitting there, and
still show `active = true` locally. `REFRESH PUBLICATION` only
reconciles which *tables* a subscription tracks (picking up newly
added or removed ones); it does nothing for a column list or row
filter that changed on a table the subscription is already
happily synchronized with. Nothing is wrong — this is documented
behavior, just an easy assumption to get wrong the first time.

**4.4 — Forcing a real resync**

```sql
ALTER SUBSCRIPTION portsmith_sub DISABLE;
TRUNCATE businesses;
TRUNCATE jobs;   -- every table touched by the resync, not just the one you changed
ALTER SUBSCRIPTION portsmith_sub ENABLE;
ALTER SUBSCRIPTION portsmith_sub REFRESH PUBLICATION WITH (copy_data = true);
```

```sql
SELECT count(*) FROM businesses;
SELECT id, name FROM businesses WHERE id IN (6, 8, 14);
```

```
 count
-------
    46

 id | name
----+------
(0 rows)
```

Forty-six — 49 minus the three now-`active = false` rows — and none of
the closed businesses present at all. **Truncate every table the
resync touches, not just the one whose filter changed.** Forgetting
one leaves its tablesync worker retrying a `COPY` into a table that
already has the same primary keys, forever:

```
ERROR:  duplicate key value violates unique constraint "jobs_pkey"
CONTEXT:  COPY jobs, line 1
LOG:  logical replication table synchronization worker for subscription "portsmith_sub", table "jobs" has started
... (repeats every ~5 seconds)
```

— a real failure mode, not a hypothetical: exactly this happened while
preparing this chapter, from truncating one table in a multi-table
resync and not the other.

**4.5 — Filtering on a non-key column has its own wall**

With the resync clean, flip a business's `active` flag live:

```sql
UPDATE businesses SET active = false WHERE id = 49;
```

```
ERROR:  cannot update table "businesses"
DETAIL:  Column used in the publication WHERE expression is not part of the replica identity.
```

For an `UPDATE`, PostgreSQL has to know whether the *old* row matched
the filter (to decide whether the subscriber needs a delete-equivalent)
— and by default, only the primary key travels in the WAL as the "old"
row image. `active` isn't part of that. The obvious-looking fix:

```sql
ALTER TABLE businesses REPLICA IDENTITY FULL;
UPDATE businesses SET active = false WHERE id = 49;
```

```
ERROR:  cannot update table "businesses"
DETAIL:  Column list used by the publication does not cover the replica identity.
```

`REPLICA IDENTITY FULL` swings too far the other way: now the replica
identity is *every* column, including `geom` and `search_vector` —
neither of which the publication's column list includes. The real fix
is a replica identity that's exactly as wide as it needs to be:

```sql
CREATE UNIQUE INDEX idx_businesses_replident ON businesses (id, active);
ALTER TABLE businesses REPLICA IDENTITY USING INDEX idx_businesses_replident;
```

```sql
UPDATE businesses SET active = false WHERE id = 49;
```

```
UPDATE 1
```

```sql
-- moments later, in portsmith_legacy
SELECT id FROM businesses WHERE id = 49;
```

```
 id
----
(0 rows)
```

Gone — correctly filtered out the moment `active` flipped, effectively
replicated as a delete. Flipping a previously-closed business back to
active does the reverse:

```sql
UPDATE businesses SET active = true WHERE id = 6;
```

```sql
SELECT id, name, active FROM businesses WHERE id = 6;  -- in portsmith_legacy
```

```
 id |          name         | active
----+------------------------+--------
  6 | Tidal Wave Surf Shop   | t
```

Reappears — an insert-equivalent, from the subscriber's point of view.
Two real errors, two real fixes, and the underlying idea worth keeping:
**a row filter on any column other than the primary key needs that
column in the replica identity — sized to exactly what the publication
actually exposes, no wider.**

<img src="imgs/ch18_replica_identity_walls.svg" alt="Sequence of two real PostgreSQL errors and their fixes while adding a row filter on a non-key column: an UPDATE fails with the filtered column not part of the replica identity; setting REPLICA IDENTITY FULL fails a second time because the publication's column list does not cover a full-row replica identity; the working fix is a unique index on exactly the id and active columns, set as the replica identity via REPLICA IDENTITY USING INDEX, after which the UPDATE succeeds and the row correctly disappears from or reappears on the subscriber depending on the new active value"/>

---

### Exercise 5 — Reading the Replication Protocol Directly, from Python

`CREATE SUBSCRIPTION` is PostgreSQL talking to PostgreSQL — the wire
format (`pgoutput`) is a compact binary protocol meant for another
PostgreSQL server to decode, not for a human or a general-purpose
client to read directly. Anything that wants to consume the *raw*
change stream — a custom sync tool, or (Exercise 6) Debezium — talks
the same underlying replication protocol, just with a different output
plugin and its own logic for what to do with each change.

**5.1 — A second, independent slot**

```sql
-- in portsmith
SELECT pg_create_logical_replication_slot('demo_test_decoding', 'test_decoding');
```

`test_decoding` ships with core PostgreSQL and produces human-readable
text instead of `pgoutput`'s binary format — the right choice for
*reading* the stream directly rather than feeding it to another
PostgreSQL instance. This slot is entirely independent of
`portsmith_sub` — the same WAL, decoded twice, for two different
consumers.

**5.2 — psycopg has no high-level replication API**

Unlike `psycopg2`, which ships a purpose-built
`LogicalReplicationConnection`, `psycopg` (v3, used throughout this
book) doesn't wrap the replication protocol at all. It's still fully
reachable, though, through the same low-level `pq` connection object
every higher-level psycopg call is eventually built on:

```python
#!/usr/bin/env python3.12
# ch18_replication_stream.py — consume a logical replication slot directly
import struct
import time

import psycopg

SLOT_NAME = "demo_test_decoding"

conn = psycopg.connect("dbname=portsmith replication=database", autocommit=True)
pgconn = conn.pgconn
pgconn.exec_(f"START_REPLICATION SLOT {SLOT_NAME} LOGICAL 0/0".encode())

while True:
    data = pgconn.get_copy_data(1)          # 1 = non-blocking
    if data[0] == 0:
        pgconn.consume_input()
        time.sleep(0.1)
        continue
    payload = bytes(data[1])
    msg_type = payload[0:1]

    if msg_type == b"w":                     # XLogData: an actual decoded change
        wal_start = struct.unpack("!Q", payload[1:9])[0]
        body = payload[25:].decode("utf-8", errors="replace")
        print(f"[{wal_start:X}] {body}")

    elif msg_type == b"k":                   # Primary keepalive
        wal_end, _send_time, reply_requested = struct.unpack("!QQb", payload[1:18])
        if reply_requested:
            # must reply, or the server eventually decides this client is dead
            now = int(time.time() * 1_000_000) - 946_684_800_000_000
            pgconn.put_copy_data(b"r" + struct.pack("!QQQQb", wal_end, wal_end, wal_end, now, 0))
```

`START_REPLICATION` puts the connection into **COPY BOTH** mode — the
same bidirectional streaming protocol PostgreSQL's own physical
replication uses, just carrying decoded logical changes instead of raw
WAL bytes. Two message types arrive: `w` (an actual change, `XLogData`)
and `k` (a keepalive the server sends periodically, which must be
acknowledged with a standby status update — skip that, and the server
eventually assumes the client has died and closes the connection). Full
script: `data/ch18_replication_stream.py`.

**5.3 — Running it**

```bash
python ch18_replication_stream.py --seconds 12
```

While it runs, from another session:

```sql
INSERT INTO jobs (job_type, payload) VALUES ('demo_test', '{"note":"replication stream test"}');
UPDATE businesses SET employee_count = 10 WHERE id = 1;
```

Real output:

```
[C6B57B98] table public.jobs: INSERT: id[bigint]:49 job_type[text]:'demo_test' payload[jsonb]:'{"note": "replication stream test"}' status[job_status]:'queued' priority[smallint]:5 ...
[C6B5A530] table public.businesses: UPDATE: id[integer]:1 name[text]:'The Gilded Clam' ... geom[geometry]:'0101000020E6100000FA7E6ABC7493FCBF9A99999999594940' employee_count[positive_integer]:'10' search_vector[tsvector]:'''clam'':3 ''gild'':2 ...' active[boolean]:true
```

Notice `geom` and `search_vector` are both present here — columns
`portsmith_pub` never publishes at all. That's the real distinction to
take away: **the WAL always contains the whole row; a publication's
column list is a filter applied on top of it, not something baked into
what gets written to WAL in the first place.** A slot with no column
list restriction, like this one, sees everything; `portsmith_sub`, tied
to `portsmith_pub`, only ever sees what that publication chose to
expose.

---

### Exercise 6 — Debezium: the Same Protocol, at Production Scale

Everything Exercise 5 hand-rolled — a replication slot, a decoding
plugin, a loop reading changes and acknowledging keepalives — is
exactly what **Debezium**'s PostgreSQL connector does, running as a
**Kafka Connect** worker instead of a standalone script:

1. **A logical replication slot**, created and owned by the connector
   itself, using `pgoutput` (or the older `decoderbufs`/`wal2json`
   plugins in older setups) — structurally identical to
   `portsmith_sub`.
2. **One Kafka topic per table** — `portsmith.public.businesses`,
   `portsmith.public.jobs` — each message a JSON or Avro envelope
   carrying the operation type (`c`reate, `u`pdate, `d`elete, or `r`ead
   for the initial snapshot), the row's before-and-after image, and
   source metadata (LSN, transaction ID, commit timestamp) — the same
   fields Exercise 5's raw `XLogData` messages carried, structured for
   machine consumption instead of printed as text.
3. **Offset tracking**, conceptually identical to `confirmed_flush_lsn`
   in Exercise 3's `pg_replication_slots` — Debezium periodically
   commits how far it's gotten, so a restart resumes from the right
   point in the WAL instead of replaying everything or losing changes.
4. **Kafka Connect's distributed worker model** handles the part a
   single Python script doesn't: if the machine running the connector
   dies, another worker in the cluster picks up the same slot and
   continues, using the last committed offset.

<img src="imgs/ch18_debezium_architecture.svg" alt="PostgreSQL with a logical replication slot, decoded by a Debezium connector running inside Kafka Connect, publishing one Kafka topic per table (portsmith.public.businesses, portsmith.public.jobs), consumed downstream by a search index updater, a cache invalidator, and other services — the production-scale version of Exercise 5's hand-rolled psycopg script reading the same kind of replication slot directly"/>

This is deliberately a discussion, not a hands-on exercise — a real
Debezium deployment needs Zookeeper (or KRaft), a Kafka broker, a Kafka
Connect worker, and the Debezium connector JARs, a multi-container
stack disproportionate to stand up for one exercise. What's worth
taking away is that there's no new mechanism to learn: Debezium is
Exercise 5's script, hardened and made distributed, reading the exact
same kind of slot this chapter already created and drained by hand.
Typical uses lean on that continuous stream directly: keeping a search
index or cache in sync with PostgreSQL without a batch job's inherent
lag, or feeding a `businesses`/`jobs` change feed into other services
in an event-driven architecture — the **outbox pattern**, notably, uses
exactly this to publish domain events reliably, by writing them as
ordinary rows in a transaction and letting CDC carry them out instead
of risking a dual-write to both a database and a message queue.

---

## Summary — What You Should Now Know

| Concept | What it does |
|---------|----------------|
| `wal_level = logical` | Required for any logical decoding — needs a restart, like `shared_preload_libraries` |
| `CREATE PUBLICATION ... FOR TABLE t (cols) WHERE (expr)` | Scopes what's streamed by table, column, and row |
| Replication slot | A durable bookmark retaining WAL for one consumer — exists independently of any subscription |
| `pg_create_subscription` / `REPLICATION` attribute | Two separate gates: creating the local subscription object vs. opening a replication connection |
| Same-instance pub/sub deadlock | `CREATE SUBSCRIPTION`'s default `create_slot=true` can wait on its own open transaction when publisher and subscriber share an instance — pre-create the slot instead |
| `pg_replication_slots` / `pg_stat_replication` | Slot state and live lag — the detail columns of the latter need `pg_monitor` |
| `ALTER SUBSCRIPTION ... REFRESH PUBLICATION` | Reconciles *which tables* are tracked — does **not** retroactively resync a changed column list or row filter on an already-synced table |
| `REPLICA IDENTITY USING INDEX` | The precise fix for filtering on a non-key column — wide enough to cover the filter, no wider than the publication's own column list |
| Raw replication protocol (`pgconn.get_copy_data`/`put_copy_data`) | What `CREATE SUBSCRIPTION`, Exercise 5's script, and Debezium all ultimately speak underneath |
| Debezium | The same slot/decode/apply loop, made distributed and production-grade, one Kafka topic per table |

**The key design insight** from this chapter is that a replication
slot is the one durable object underneath everything else —
`CREATE SUBSCRIPTION`, a hand-rolled psycopg script, and Debezium are
three different consumers of the exact same primitive, differing only
in what decodes the WAL and what happens to the output. Understanding
the slot is understanding the whole chapter; everything else is a
client.

---

*Going further: Chapter 19's `pg_cron` is the natural next tool for
operationalizing what this chapter demonstrated by hand — a scheduled
job that checks `pg_replication_slots` for a slot whose
`confirmed_flush_lsn` hasn't advanced in too long (a stuck or abandoned
consumer, quietly retaining WAL) and pages someone before disk fills
up, the same shape of unattended, recurring maintenance task Chapter
17's own "going further" note imagined for aging partition exports.*
