#!/usr/bin/env python3.12
"""
Chapter 11 seed data — Portsmith Business Revenue.

Creates one small table, `business_revenue`, extending the `businesses`
table from Chapter 1 with a synthetic quarterly revenue figure for 2024.
Revenue is generated from each business's category (from the `details`
JSONB column) plus a mild summer tourism bump in Q2/Q3 and a small
quarter-over-quarter growth trend — enough structure for running totals
and partition-percentage exercises to have a real story, without being
a realistic financial model.

Requires: Chapter 1's seed script (ch01_seed.py) to have been run first.

Usage:
    python ch11_seed.py [DSN]

    DSN defaults to "dbname=portsmith".
"""

import sys

import psycopg

DSN = sys.argv[1] if len(sys.argv) > 1 else "dbname=portsmith"

DDL = """
DROP TABLE IF EXISTS business_revenue CASCADE;

CREATE TABLE business_revenue (
    business_id  INTEGER NOT NULL REFERENCES businesses (id),
    quarter      INTEGER NOT NULL CHECK (quarter BETWEEN 1 AND 4),
    revenue      NUMERIC(10, 2) NOT NULL,
    PRIMARY KEY (business_id, quarter)
);
"""

# Base quarterly revenue range per category — accommodation (hotels, inns)
# and restaurants run highest, service businesses lowest.
BASE_RANGE = {
    "accommodation": (60_000, 150_000),
    "restaurant":    (45_000, 90_000),
    "retail":        (30_000, 70_000),
    "entertainment": (25_000, 80_000),
    "service":       (20_000, 50_000),
}

# Q2/Q3 seasonal multiplier — Portsmith's harbour setting draws a summer
# tourist bump that lifts every category, accommodation and restaurants
# most of all.
SEASONAL_BUMP = {
    "accommodation": {1: 1.00, 2: 1.35, 3: 1.45, 4: 1.05},
    "restaurant":    {1: 0.95, 2: 1.15, 3: 1.20, 4: 0.98},
    "retail":        {1: 0.95, 2: 1.05, 3: 1.10, 4: 1.10},  # Q4 holiday bump too
    "entertainment": {1: 0.90, 2: 1.10, 3: 1.20, 4: 1.05},
    "service":       {1: 1.00, 2: 1.02, 3: 1.03, 4: 1.02},  # steady, non-seasonal
}

GROWTH_PER_QUARTER = 0.02  # mild, steady quarter-over-quarter growth


def main() -> None:
    print(f"Connecting to: {DSN}")
    with psycopg.connect(DSN) as conn:
        with conn.cursor() as cur:
            print("Creating schema …")
            cur.execute(DDL)

            cur.execute("SELECT id, details ->> 'category' FROM businesses ORDER BY id")
            businesses = cur.fetchall()

            print(f"Generating quarterly revenue for {len(businesses)} businesses …")
            rows = []
            for business_id, category in businesses:
                lo, hi = BASE_RANGE[category]
                # Deterministic per-business base, spread evenly across the
                # category's range by id so results are reproducible without
                # needing a stored random seed table.
                spread = (business_id * 2654435761) % 1000 / 1000.0  # 0.0-1.0
                base = lo + spread * (hi - lo)
                for quarter in range(1, 5):
                    growth = (1 + GROWTH_PER_QUARTER) ** (quarter - 1)
                    seasonal = SEASONAL_BUMP[category][quarter]
                    revenue = round(base * growth * seasonal, 2)
                    rows.append((business_id, quarter, revenue))

            cur.executemany(
                "INSERT INTO business_revenue (business_id, quarter, revenue) VALUES (%s, %s, %s)",
                rows,
            )
        conn.commit()

        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM business_revenue")
            (total,) = cur.fetchone()
        print(f"Done — {total} rows in business_revenue.")


if __name__ == "__main__":
    main()
