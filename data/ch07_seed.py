#!/usr/bin/env python3.12
"""
Chapter 7 seed data — Portsmith Network Security Monitoring.

Creates an ip4r-backed schema for tracking access to Portsmith's online
services (the resident portal, the business licensing API, PostGIS map
tiles) and the block/allow lists the security team maintains against it:
  - network_events : login attempts and API calls, one row per event
  - blocklists     : CIDR ranges flagged as malicious, by category
  - allowlists     : CIDR ranges that should never be blocked

All IP ranges here use IANA-reserved, non-routable blocks (RFC 5737
documentation ranges and the 240.0.0.0/4 reserved block) rather than real
public address space, since this is synthetic security data, not a real
blocklist.

Usage:
    python ch07_seed.py [DSN]

    DSN defaults to "dbname=portsmith".
"""

import random
import sys
from datetime import datetime, timedelta, timezone

import psycopg

DSN = sys.argv[1] if len(sys.argv) > 1 else "dbname=portsmith"

DDL = """
DROP TABLE IF EXISTS network_events CASCADE;
DROP TABLE IF EXISTS blocklists CASCADE;
DROP TABLE IF EXISTS allowlists CASCADE;

CREATE TABLE blocklists (
    id          SERIAL PRIMARY KEY,
    cidr        ip4r NOT NULL,
    category    TEXT NOT NULL,
    description TEXT NOT NULL,
    added_on    DATE NOT NULL
);

CREATE TABLE allowlists (
    id          SERIAL PRIMARY KEY,
    cidr        ip4r NOT NULL,
    description TEXT NOT NULL,
    added_on    DATE NOT NULL
);

CREATE TABLE network_events (
    id          BIGSERIAL PRIMARY KEY,
    event_type  TEXT NOT NULL
                    CHECK (event_type IN ('login_success', 'login_failure', 'api_call', 'api_error')),
    source_ip   ip4 NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    detail      TEXT NOT NULL
);
"""

# ---------------------------------------------------------------------------
# Block/allow lists
#
# 198.51.100.0/28 (inside the blocklist) sits INSIDE 198.51.100.0/24 (the
# City Hall allowlist entry) on purpose -- an automated brute-force feed
# flagged a sub-range that overlaps the city's own VPN block, exactly the
# kind of conflict Exercise 5 asks you to find.
# ---------------------------------------------------------------------------

BLOCKLISTS = [
    {
        "cidr": "203.0.113.0/24", "category": "known_malicious",
        "description": "Repeated brute-force login attempts against the resident portal, flagged by the security team",
        "added_on": "2024-01-15",
    },
    {
        "cidr": "203.0.113.128/26", "category": "botnet",
        "description": "Subrange within 203.0.113.0/24 attributed to a specific credential-stuffing botnet",
        "added_on": "2024-02-02",
    },
    {
        "cidr": "240.1.2.0/25", "category": "tor_exit_node",
        "description": "Known Tor exit node range observed hitting the business licensing API",
        "added_on": "2024-01-20",
    },
    {
        "cidr": "198.51.100.0/28", "category": "brute_force_source",
        "description": "Automated feed: high-volume failed logins, unreviewed",
        "added_on": "2024-03-01",
    },
]

ALLOWLISTS = [
    {
        "cidr": "198.51.100.0/24",
        "description": "Portsmith City Hall internal network and staff VPN",
        "added_on": "2023-06-01",
    },
    {
        "cidr": "192.0.2.0/24",
        "description": "Trusted vendor: Riverside IT Contracting Partners",
        "added_on": "2023-09-12",
    },
    {
        "cidr": "192.0.2.64/29",
        "description": "City payment processor webhook source",
        "added_on": "2023-11-05",
    },
]

# ---------------------------------------------------------------------------
# Synthetic network events
#
# Four source pools, each with a distinct behavioural pattern:
#   - 203.0.113.0/24    : brute-force login failures (matches blocklist)
#   - 240.1.2.0/25       : Tor exit traffic hitting the API (matches blocklist)
#   - 198.51.100.0/24    : mostly legitimate City Hall traffic, with a
#                          handful of IPs inside the flagged .0/28 sub-range
#   - 192.0.2.0/24       : vendor API/webhook traffic (matches allowlist)
#   - a handful of unrelated IPs                : ordinary resident traffic
# ---------------------------------------------------------------------------


def ips_in(cidr_base: str, host_bits: int, count: int, rng: random.Random) -> list[str]:
    """Generate `count` distinct IPs within a given base prefix + host range."""
    base_octets = [int(o) for o in cidr_base.split(".")]
    base_int = (base_octets[0] << 24) + (base_octets[1] << 16) + (base_octets[2] << 8) + base_octets[3]
    max_host = (1 << host_bits) - 1
    hosts = rng.sample(range(1, max_host), min(count, max_host - 1))
    ips = []
    for h in hosts:
        ip_int = base_int + h
        ips.append(
            f"{(ip_int >> 24) & 255}.{(ip_int >> 16) & 255}.{(ip_int >> 8) & 255}.{ip_int & 255}"
        )
    return ips


def build_events(rng: random.Random) -> list[dict]:
    events = []
    start = datetime(2024, 3, 10, tzinfo=timezone.utc)

    def add(ip: str, event_type: str, detail: str, minutes_offset: int) -> None:
        events.append({
            "source_ip": ip,
            "event_type": event_type,
            "detail": detail,
            "occurred_at": start + timedelta(minutes=minutes_offset),
        })

    # Brute-force pool: 203.0.113.0/24, hammering resident portal logins
    brute_ips = ips_in("203.0.113.0", 8, 10, rng)
    minute = 0
    for ip in brute_ips:
        for _ in range(rng.randint(2, 5)):
            add(ip, "login_failure", "resident portal: invalid credentials", minute)
            minute += rng.randint(1, 4)

    # Tor exit pool: 240.1.2.0/25, probing the licensing API
    tor_ips = ips_in("240.1.2.0", 7, 6, rng)
    for ip in tor_ips:
        for _ in range(rng.randint(1, 3)):
            add(ip, "api_call", "business licensing API: GET /businesses", minute)
            minute += rng.randint(1, 6)

    # City Hall pool: 198.51.100.0/24, legitimate staff traffic ...
    city_hall_ips = ips_in("198.51.100.0", 8, 12, rng)
    for ip in city_hall_ips:
        add(ip, "login_success", "staff portal login", minute)
        minute += rng.randint(2, 10)
        if rng.random() < 0.4:
            add(ip, "api_call", "permit review dashboard: GET /jobs", minute)
            minute += rng.randint(1, 5)

    # ... plus a few IPs inside the flagged .0/28 sub-range (the overlap case)
    flagged_subrange_ips = ips_in("198.51.100.0", 4, 3, rng)
    for ip in flagged_subrange_ips:
        for _ in range(rng.randint(2, 4)):
            add(ip, "login_failure", "staff portal: invalid credentials", minute)
            minute += rng.randint(1, 3)

    # Vendor pool: 192.0.2.0/24, webhook/API traffic
    vendor_ips = ips_in("192.0.2.0", 8, 8, rng)
    for ip in vendor_ips:
        for _ in range(rng.randint(2, 6)):
            add(ip, rng.choice(["api_call", "api_call", "api_error"]),
                "payment webhook: POST /permits/payment-confirmed", minute)
            minute += rng.randint(1, 8)

    # Unrelated, ordinary resident traffic scattered across other ranges
    other_pools = ["100.64.5.0", "100.64.9.0", "203.0.113.200"]
    for base in other_pools:
        for ip in ips_in(base, 4, 4, rng):
            add(ip, rng.choice(["login_success", "api_call"]), "resident portal: normal use", minute)
            minute += rng.randint(3, 12)

    return events


def main() -> None:
    print(f"Connecting to: {DSN}")
    rng = random.Random(7)
    with psycopg.connect(DSN) as conn:
        with conn.cursor() as cur:
            print("Creating schema …")
            cur.execute(DDL)

            print(f"Inserting {len(BLOCKLISTS)} blocklist entries …")
            cur.executemany(
                "INSERT INTO blocklists (cidr, category, description, added_on) VALUES (%s, %s, %s, %s)",
                [(b["cidr"], b["category"], b["description"], b["added_on"]) for b in BLOCKLISTS],
            )

            print(f"Inserting {len(ALLOWLISTS)} allowlist entries …")
            cur.executemany(
                "INSERT INTO allowlists (cidr, description, added_on) VALUES (%s, %s, %s)",
                [(a["cidr"], a["description"], a["added_on"]) for a in ALLOWLISTS],
            )

            events = build_events(rng)
            print(f"Inserting {len(events)} network events …")
            cur.executemany(
                "INSERT INTO network_events (source_ip, event_type, detail, occurred_at) "
                "VALUES (%(source_ip)s, %(event_type)s, %(detail)s, %(occurred_at)s)",
                events,
            )

            cur.execute("SELECT COUNT(*) FROM network_events")
            (count,) = cur.fetchone()
            print(f"Done — {count} rows in network_events, {len(BLOCKLISTS)} blocklist entries, "
                  f"{len(ALLOWLISTS)} allowlist entries.")

        conn.commit()


if __name__ == "__main__":
    main()
