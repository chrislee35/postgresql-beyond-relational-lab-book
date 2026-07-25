#!/usr/bin/env python3.12
"""
Chapter 3 seed data — Portsmith Permit Queue.

Creates a job-queue schema (no extensions required) and seeds it with
synthetic work items representing permit applications submitted to
Portsmith's permitting office:
  - jobs             : the live queue (status, priority, retry bookkeeping)
  - dead_letter_jobs : jobs that exhausted their retries (empty at seed time)

Usage:
    python ch03_seed.py [DSN]

    DSN defaults to "dbname=portsmith".
"""

import json
import sys

import psycopg

DSN = sys.argv[1] if len(sys.argv) > 1 else "dbname=portsmith"

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

DDL = """
DROP TABLE IF EXISTS dead_letter_jobs CASCADE;
DROP TABLE IF EXISTS jobs CASCADE;

CREATE TABLE jobs (
    id            BIGSERIAL PRIMARY KEY,
    job_type      TEXT        NOT NULL,
    payload       JSONB       NOT NULL,
    status        TEXT        NOT NULL DEFAULT 'queued'
                      CHECK (status IN ('queued', 'in_progress', 'completed', 'failed')),
    priority      SMALLINT    NOT NULL DEFAULT 5,
    attempts      INTEGER     NOT NULL DEFAULT 0,
    max_attempts  INTEGER     NOT NULL DEFAULT 3,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    claimed_at    TIMESTAMPTZ,
    claimed_by    TEXT,
    heartbeat_at  TIMESTAMPTZ,
    completed_at  TIMESTAMPTZ,
    last_error    TEXT
);

-- The claim query only ever looks at queued rows, ordered by priority then
-- age. A partial index keeps the index small as completed/failed rows pile
-- up, since they are never part of it.
CREATE INDEX idx_jobs_claim_order
    ON jobs (priority, created_at, id)
    WHERE status = 'queued';

-- General-purpose index for status dashboards and the reclaim sweep.
CREATE INDEX idx_jobs_status
    ON jobs (status);

CREATE TABLE dead_letter_jobs (
    id            BIGINT      PRIMARY KEY,
    job_type      TEXT        NOT NULL,
    payload       JSONB       NOT NULL,
    priority      SMALLINT    NOT NULL,
    attempts      INTEGER     NOT NULL,
    max_attempts  INTEGER     NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL,
    last_error    TEXT,
    failed_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

# ---------------------------------------------------------------------------
# Synthetic permit applications
#
# job_type doubles as the permit category. priority is set per category
# (1 = most urgent, 5 = least) — demolition work affects public safety and
# jumps the queue; sign permits can wait.
# ---------------------------------------------------------------------------

JOBS: list[dict] = [
    # ── demolition_permit — priority 1 ─────────────────────────────────────
    {
        "job_type": "demolition_permit", "priority": 1,
        "payload": {
            "application_id": "DP-2024-0001", "applicant_name": "Marlowe Estates Ltd.",
            "property_address": "12 Anchor Lane", "neighbourhood": "Harbour District",
            "description": "Demolish derelict boat shed prior to redevelopment",
            "fee_due": 850.00,
        },
    },
    {
        "job_type": "demolition_permit", "priority": 1,
        "payload": {
            "application_id": "DP-2024-0002", "applicant_name": "Northgate Housing Trust",
            "property_address": "88 Bay Street", "neighbourhood": "Northgate",
            "description": "Demolish condemned rowhouse (structural failure)",
            "fee_due": 1200.00,
        },
    },
    {
        "job_type": "demolition_permit", "priority": 1,
        "payload": {
            "application_id": "DP-2024-0003", "applicant_name": "Ironside Auto Group",
            "property_address": "4 Dock Road", "neighbourhood": "Industrial Port",
            "description": "Demolish disused warehouse annex",
            "fee_due": 950.00,
        },
    },
    {
        "job_type": "demolition_permit", "priority": 1,
        "payload": {
            "application_id": "DP-2024-0004", "applicant_name": "City of Portsmith Public Works",
            "property_address": "1 Ring Road", "neighbourhood": "Northgate",
            "description": "Emergency demolition of storm-damaged retaining wall",
            "fee_due": 0.00,
        },
    },

    # ── business_license — priority 2 ──────────────────────────────────────
    {
        "job_type": "business_license", "priority": 2,
        "payload": {
            "application_id": "BL-2024-0001", "applicant_name": "Ada Whitfield",
            "property_address": "27 Market Street", "neighbourhood": "Old Town",
            "description": "New license: specialty tea shop", "fee_due": 150.00,
        },
    },
    {
        "job_type": "business_license", "priority": 2,
        "payload": {
            "application_id": "BL-2024-0002", "applicant_name": "Reef & Rope Outfitters",
            "property_address": "9 Quay Street", "neighbourhood": "Riverside",
            "description": "New license: kayak and paddleboard rental", "fee_due": 200.00,
        },
    },
    {
        "job_type": "business_license", "priority": 2,
        "payload": {
            "application_id": "BL-2024-0003", "applicant_name": "Tomas Bianchi",
            "property_address": "41 Fisherman's Row", "neighbourhood": "Old Town",
            "description": "New license: gelato cart, seasonal", "fee_due": 90.00,
        },
    },
    {
        "job_type": "business_license", "priority": 2,
        "payload": {
            "application_id": "BL-2024-0004", "applicant_name": "Portsmith Robotics Club",
            "property_address": "6 Lighthouse Avenue", "neighbourhood": "University Quarter",
            "description": "New license: nonprofit workshop space", "fee_due": 60.00,
        },
    },
    {
        "job_type": "business_license", "priority": 2,
        "payload": {
            "application_id": "BL-2024-0005", "applicant_name": "Selene Okafor",
            "property_address": "18 Tidewater Lane", "neighbourhood": "Riverside",
            "description": "New license: mobile hair salon", "fee_due": 120.00,
        },
    },
    {
        "job_type": "business_license", "priority": 2,
        "payload": {
            "application_id": "BL-2024-0006", "applicant_name": "Dockside Roasters LLC",
            "property_address": "3 Dock Road", "neighbourhood": "Industrial Port",
            "description": "New license: coffee roastery and taproom", "fee_due": 300.00,
        },
    },
    {
        "job_type": "business_license", "priority": 2,
        "payload": {
            "application_id": "BL-2024-0007", "applicant_name": "Priya Nandakumar",
            "property_address": "22 Canal Road", "neighbourhood": "Riverside",
            "description": "New license: yoga studio", "fee_due": 150.00,
        },
    },
    {
        "job_type": "business_license", "priority": 2,
        "payload": {
            "application_id": "BL-2024-0008", "applicant_name": "Bay Street Vintage",
            "property_address": "55 Bay Street", "neighbourhood": "Northgate",
            "description": "New license: secondhand clothing store", "fee_due": 150.00,
        },
    },
    {
        "job_type": "business_license", "priority": 2,
        "payload": {
            "application_id": "BL-2024-0009", "applicant_name": "Otis Marchetti",
            "property_address": "14 Harbour Walk", "neighbourhood": "Harbour District",
            "description": "New license: dockside bait and tackle shop", "fee_due": 150.00,
        },
    },
    {
        "job_type": "business_license", "priority": 2,
        "payload": {
            "application_id": "BL-2024-0010", "applicant_name": "Northgate Family Diner Inc.",
            "property_address": "70 Bay Street", "neighbourhood": "Northgate",
            "description": "New license: 24-hour diner", "fee_due": 300.00,
        },
    },
    {
        "job_type": "business_license", "priority": 2,
        "payload": {
            "application_id": "BL-2024-0011", "applicant_name": "Wren Alcott",
            "property_address": "5 Portside Drive", "neighbourhood": "Harbour District",
            "description": "New license: independent bookstore annex (rare books)", "fee_due": 150.00,
        },
    },
    {
        "job_type": "business_license", "priority": 2,
        "payload": {
            "application_id": "BL-2024-0012", "applicant_name": "Quarter Note Holdings",
            "property_address": "12 Lighthouse Avenue", "neighbourhood": "University Quarter",
            "description": "License renewal: late-night music venue", "fee_due": 400.00,
        },
    },

    # ── building_permit — priority 3 ───────────────────────────────────────
    {
        "job_type": "building_permit", "priority": 3,
        "payload": {
            "application_id": "BP-2024-0001", "applicant_name": "Marcus Webb",
            "property_address": "142 Harbour Walk", "neighbourhood": "Harbour District",
            "description": "Single-story rear extension", "fee_due": 425.00,
        },
    },
    {
        "job_type": "building_permit", "priority": 3,
        "payload": {
            "application_id": "BP-2024-0002", "applicant_name": "Fiona Aldous",
            "property_address": "8 Market Street", "neighbourhood": "Old Town",
            "description": "Kitchen remodel, load-bearing wall removal", "fee_due": 375.00,
        },
    },
    {
        "job_type": "building_permit", "priority": 3,
        "payload": {
            "application_id": "BP-2024-0003", "applicant_name": "Riverside Development Group",
            "property_address": "60 Canal Road", "neighbourhood": "Riverside",
            "description": "New 4-unit apartment building", "fee_due": 3200.00,
        },
    },
    {
        "job_type": "building_permit", "priority": 3,
        "payload": {
            "application_id": "BP-2024-0004", "applicant_name": "Portsmith University",
            "property_address": "1 Lighthouse Avenue", "neighbourhood": "University Quarter",
            "description": "New lecture hall wing", "fee_due": 8500.00,
        },
    },
    {
        "job_type": "building_permit", "priority": 3,
        "payload": {
            "application_id": "BP-2024-0005", "applicant_name": "Hannah Reyes",
            "property_address": "33 Quay Street", "neighbourhood": "Riverside",
            "description": "Detached garden studio", "fee_due": 210.00,
        },
    },
    {
        "job_type": "building_permit", "priority": 3,
        "payload": {
            "application_id": "BP-2024-0006", "applicant_name": "Old Town Hardware Co.",
            "property_address": "18 Market Street", "neighbourhood": "Old Town",
            "description": "Storefront facade renovation", "fee_due": 480.00,
        },
    },
    {
        "job_type": "building_permit", "priority": 3,
        "payload": {
            "application_id": "BP-2024-0007", "applicant_name": "Callum Ostrowski",
            "property_address": "5 Anchor Lane", "neighbourhood": "Harbour District",
            "description": "Second-story addition", "fee_due": 640.00,
        },
    },
    {
        "job_type": "building_permit", "priority": 3,
        "payload": {
            "application_id": "BP-2024-0008", "applicant_name": "Northgate Logistics Ltd.",
            "property_address": "40 Bay Street", "neighbourhood": "Northgate",
            "description": "New loading dock structure", "fee_due": 1100.00,
        },
    },
    {
        "job_type": "building_permit", "priority": 3,
        "payload": {
            "application_id": "BP-2024-0009", "applicant_name": "Ines Falkner",
            "property_address": "27 Tidewater Lane", "neighbourhood": "Riverside",
            "description": "Basement conversion to rental unit", "fee_due": 390.00,
        },
    },
    {
        "job_type": "building_permit", "priority": 3,
        "payload": {
            "application_id": "BP-2024-0010", "applicant_name": "Portsmith Arms Hotel",
            "property_address": "6 Market Street", "neighbourhood": "Old Town",
            "description": "Rooftop terrace addition", "fee_due": 1450.00,
        },
    },
    {
        "job_type": "building_permit", "priority": 3,
        "payload": {
            "application_id": "BP-2024-0011", "applicant_name": "Dominic Ferro",
            "property_address": "16 Dock Road", "neighbourhood": "Industrial Port",
            "description": "Workshop and small warehouse", "fee_due": 2200.00,
        },
    },
    {
        "job_type": "building_permit", "priority": 3,
        "payload": {
            "application_id": "BP-2024-0012", "applicant_name": "Saoirse Kavanagh",
            "property_address": "2 Fisherman's Row", "neighbourhood": "Old Town",
            "description": "Front porch enclosure", "fee_due": 180.00,
        },
    },
    {
        "job_type": "building_permit", "priority": 3,
        "payload": {
            "application_id": "BP-2024-0013", "applicant_name": "Harbourfront Holdings",
            "property_address": "9 Portside Drive", "neighbourhood": "Harbour District",
            "description": "Boathouse reconstruction", "fee_due": 960.00,
        },
    },
    {
        "job_type": "building_permit", "priority": 3,
        "payload": {
            "application_id": "BP-2024-0014", "applicant_name": "Green Leaf Cooperative",
            "property_address": "11 Lighthouse Avenue", "neighbourhood": "University Quarter",
            "description": "Rooftop greenhouse addition", "fee_due": 520.00,
        },
    },
    {
        "job_type": "building_permit", "priority": 3,
        "payload": {
            "application_id": "BP-2024-0015", "applicant_name": "Petra Lindqvist",
            "property_address": "48 Ring Road", "neighbourhood": "Northgate",
            "description": "Detached double garage", "fee_due": 260.00,
        },
    },

    # ── event_permit — priority 4 ──────────────────────────────────────────
    {
        "job_type": "event_permit", "priority": 4,
        "payload": {
            "application_id": "EP-2024-0001", "applicant_name": "Portsmith Maritime Festival Committee",
            "property_address": "Harbourside Park", "neighbourhood": "Harbour District",
            "description": "3-day maritime festival, temporary stalls and stage", "fee_due": 600.00,
        },
    },
    {
        "job_type": "event_permit", "priority": 4,
        "payload": {
            "application_id": "EP-2024-0002", "applicant_name": "University Quarter Business Association",
            "property_address": "University Grounds", "neighbourhood": "University Quarter",
            "description": "Street food market, weekly recurring", "fee_due": 150.00,
        },
    },
    {
        "job_type": "event_permit", "priority": 4,
        "payload": {
            "application_id": "EP-2024-0003", "applicant_name": "Old Town Merchants Guild",
            "property_address": "Market Square Gardens", "neighbourhood": "Old Town",
            "description": "Winter craft fair", "fee_due": 220.00,
        },
    },
    {
        "job_type": "event_permit", "priority": 4,
        "payload": {
            "application_id": "EP-2024-0004", "applicant_name": "Riverside Cinema",
            "property_address": "Riverside Walk Park", "neighbourhood": "Riverside",
            "description": "Outdoor summer film screenings", "fee_due": 180.00,
        },
    },
    {
        "job_type": "event_permit", "priority": 4,
        "payload": {
            "application_id": "EP-2024-0005", "applicant_name": "Northgate Community Trust",
            "property_address": "Northgate Recreation Ground", "neighbourhood": "Northgate",
            "description": "Charity fun run, road closure required", "fee_due": 300.00,
        },
    },
    {
        "job_type": "event_permit", "priority": 4,
        "payload": {
            "application_id": "EP-2024-0006", "applicant_name": "Dockside Green Neighbours",
            "property_address": "Dockside Green", "neighbourhood": "Industrial Port",
            "description": "Community harvest festival", "fee_due": 120.00,
        },
    },
    {
        "job_type": "event_permit", "priority": 4,
        "payload": {
            "application_id": "EP-2024-0007", "applicant_name": "Portsmith Jazz Society",
            "property_address": "Harbourside Park", "neighbourhood": "Harbour District",
            "description": "Evening jazz concert series", "fee_due": 250.00,
        },
    },
    {
        "job_type": "event_permit", "priority": 4,
        "payload": {
            "application_id": "EP-2024-0008", "applicant_name": "Portsmith Cycling Club",
            "property_address": "Ring Road", "neighbourhood": "Northgate",
            "description": "Charity cycling race, rolling road closures", "fee_due": 400.00,
        },
    },

    # ── sign_permit — priority 5 ───────────────────────────────────────────
    {
        "job_type": "sign_permit", "priority": 5,
        "payload": {
            "application_id": "SP-2024-0001", "applicant_name": "Dragon Palace",
            "property_address": "12 Bay Street", "neighbourhood": "Northgate",
            "description": "Illuminated storefront sign replacement", "fee_due": 75.00,
        },
    },
    {
        "job_type": "sign_permit", "priority": 5,
        "payload": {
            "application_id": "SP-2024-0002", "applicant_name": "Old Brewery Tap",
            "property_address": "3 Dock Road", "neighbourhood": "Industrial Port",
            "description": "New hanging pub sign", "fee_due": 60.00,
        },
    },
    {
        "job_type": "sign_permit", "priority": 5,
        "payload": {
            "application_id": "SP-2024-0003", "applicant_name": "Lighthouse Bookshop",
            "property_address": "20 Harbour Walk", "neighbourhood": "Harbour District",
            "description": "Window vinyl lettering", "fee_due": 40.00,
        },
    },
    {
        "job_type": "sign_permit", "priority": 5,
        "payload": {
            "application_id": "SP-2024-0004", "applicant_name": "The Hungry Scholar",
            "property_address": "9 Lighthouse Avenue", "neighbourhood": "University Quarter",
            "description": "A-frame sandwich board approval", "fee_due": 25.00,
        },
    },
    {
        "job_type": "sign_permit", "priority": 5,
        "payload": {
            "application_id": "SP-2024-0005", "applicant_name": "Thai Orchid",
            "property_address": "14 Quay Street", "neighbourhood": "Riverside",
            "description": "Illuminated storefront sign replacement", "fee_due": 75.00,
        },
    },
    {
        "job_type": "sign_permit", "priority": 5,
        "payload": {
            "application_id": "SP-2024-0006", "applicant_name": "Finch & Sons Barbers",
            "property_address": "31 Market Street", "neighbourhood": "Old Town",
            "description": "Traditional barber pole reinstallation", "fee_due": 50.00,
        },
    },
]

# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def main() -> None:
    print(f"Connecting to: {DSN}")
    with psycopg.connect(DSN) as conn:
        with conn.cursor() as cur:
            print("Creating schema …")
            cur.execute(DDL)

            print(f"Inserting {len(JOBS)} jobs …")
            cur.executemany(
                """
                INSERT INTO jobs (job_type, priority, payload)
                VALUES (%(job_type)s, %(priority)s, %(payload)s)
                """,
                [
                    {**j, "payload": json.dumps(j["payload"])}
                    for j in JOBS
                ],
            )

            cur.execute("SELECT COUNT(*) FROM jobs")
            (count,) = cur.fetchone()
            print(f"Done — {count} rows in jobs, all queued.")

        conn.commit()


if __name__ == "__main__":
    main()
