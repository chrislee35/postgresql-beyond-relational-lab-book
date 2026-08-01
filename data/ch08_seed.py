#!/usr/bin/env python3.12
"""
Chapter 8 seed data — Portsmith IoT Sensor Network.

Creates two things:
  - sensors                  : metadata for 120 city infrastructure sensors
                                (temperature, traffic, air quality)
  - sensor_readings_staging  : ~10.5 million timestamped readings for all of
                                2024, as a single unpartitioned table — the
                                state the data is in *before* Chapter 8's
                                exercises decide to partition it

The chapter itself creates the partitioned `sensor_readings` table and backs
it with data copied from the staging table, so that the reader performs the
"retrofit an existing table to be partitioned" exercise rather than finding
it already done for them.

One deliberate anomaly: temperature sensor #17 has a firmware clock bug that
reports its last four days of the year one year fast (2025 instead of 2024).
Nothing downstream removes these rows — they exist so that Chapter 8,
Exercise 2 has a real case of data landing in a DEFAULT partition instead of
a dated one.

Usage:
    python ch08_seed.py [DSN]

    DSN defaults to "dbname=portsmith".
"""

import calendar
import math
import random
import sys
import time
from datetime import date, datetime, timedelta, timezone

import psycopg

DSN = sys.argv[1] if len(sys.argv) > 1 else "dbname=portsmith"

DDL = """
DROP TABLE IF EXISTS sensor_readings_staging CASCADE;
DROP TABLE IF EXISTS sensor_readings CASCADE;
DROP TABLE IF EXISTS sensors CASCADE;

CREATE TABLE sensors (
    id           INTEGER PRIMARY KEY,
    sensor_type  TEXT NOT NULL
                     CHECK (sensor_type IN ('temperature', 'traffic', 'air_quality')),
    label        TEXT NOT NULL,
    neighborhood TEXT NOT NULL
);

CREATE TABLE sensor_readings_staging (
    id            BIGINT GENERATED ALWAYS AS IDENTITY,
    sensor_id     INTEGER NOT NULL REFERENCES sensors(id),
    sensor_type   TEXT NOT NULL
                      CHECK (sensor_type IN ('temperature', 'traffic', 'air_quality')),
    reading_value DOUBLE PRECISION NOT NULL,
    recorded_at   TIMESTAMPTZ NOT NULL
);
"""

NEIGHBORHOODS = [
    "Harbour District", "Old Town", "Northgate",
    "Riverside", "University Quarter", "Industrial Port",
]

STREETS = [
    "Harbour Walk", "Portside Drive", "Market Street", "Lighthouse Avenue",
    "Bay Street", "Canal Road", "Dock Road", "Quay Street",
    "Tidewater Lane", "Anchor Lane", "Fisherman's Row", "Ring Road",
]

N_TEMP, N_TRAFFIC, N_AIR = 50, 40, 30

# Average monthly temperature (°F), a mild maritime climate like Portsmith's
# harbour setting — cool damp winters, warm-not-hot summers.
MONTHLY_TEMP_F = [42, 44, 48, 54, 61, 68, 74, 75, 69, 59, 50, 44]

# Vehicles per 5-minute interval, by hour of day, weekday vs weekend.
WEEKDAY_TRAFFIC = [3, 2, 2, 2, 3, 8, 20, 55, 70, 45, 30, 28,
                   32, 30, 28, 35, 55, 75, 60, 35, 20, 14, 9, 5]
WEEKEND_TRAFFIC = [5, 4, 3, 2, 2, 3, 6, 10, 18, 28, 38, 42,
                   45, 44, 42, 40, 38, 34, 28, 22, 16, 12, 9, 6]

YEAR = 2024
CLOCK_BUG_SENSOR_ID = 17  # a temperature sensor


def build_sensors(rng: random.Random) -> list[dict]:
    sensors = []
    sid = 1
    for i in range(N_TEMP):
        sensors.append({
            "id": sid, "sensor_type": "temperature",
            "label": f"Temp-{i + 1:02d}",
            "neighborhood": NEIGHBORHOODS[i % len(NEIGHBORHOODS)],
            "offset": rng.uniform(-3.0, 3.0),
        })
        sid += 1
    for i in range(N_TRAFFIC):
        sensors.append({
            "id": sid, "sensor_type": "traffic",
            "label": f"Traffic-{i + 1:02d}",
            "neighborhood": STREETS[i % len(STREETS)],
            "scale": rng.uniform(0.6, 1.6),
        })
        sid += 1
    for i in range(N_AIR):
        sensors.append({
            "id": sid, "sensor_type": "air_quality",
            "label": f"AQI-{i + 1:02d}",
            "neighborhood": NEIGHBORHOODS[i % len(NEIGHBORHOODS)],
        })
        sid += 1
    return sensors


def build_spike_days(air_sensors: list[dict], rng: random.Random) -> set[tuple[int, date]]:
    """A handful of elevated-pollution days per air quality sensor per year."""
    spikes = set()
    all_days = [date(YEAR, 1, 1) + timedelta(days=d)
                for d in range((date(YEAR, 12, 31) - date(YEAR, 1, 1)).days + 1)]
    for s in air_sensors:
        for d in all_days:
            if rng.random() < 0.06:
                spikes.add((s["id"], d))
    return spikes


def temp_value(month: int, hour: int, offset: float, rng: random.Random) -> float:
    baseline = MONTHLY_TEMP_F[month - 1]
    diurnal = 6.0 * math.sin((hour - 9) / 24 * 2 * math.pi)
    return round(baseline + diurnal + offset + rng.gauss(0, 1.2), 1)


def traffic_value(hour: int, is_weekend: bool, scale: float, rng: random.Random) -> float:
    base = (WEEKEND_TRAFFIC if is_weekend else WEEKDAY_TRAFFIC)[hour]
    val = base * scale + rng.gauss(0, max(base, 1) * 0.15)
    return float(max(0, round(val)))


def air_value(is_spike: bool, hour: int, rng: random.Random) -> float:
    val = rng.uniform(20, 45)
    if is_spike:
        val += rng.uniform(60, 110)
    if hour in (7, 8, 17, 18):
        val += rng.uniform(3, 8)
    return round(max(val, 5.0), 1)


def generate_rows(sensors: list[dict], spike_days: set[tuple[int, date]], rng: random.Random):
    temp_sensors = [s for s in sensors if s["sensor_type"] == "temperature"]
    traffic_sensors = [s for s in sensors if s["sensor_type"] == "traffic"]
    air_sensors = [s for s in sensors if s["sensor_type"] == "air_quality"]

    for month in range(1, 13):
        days_in_month = calendar.monthrange(YEAR, month)[1]
        month_rows = 0
        for day in range(1, days_in_month + 1):
            d = date(YEAR, month, day)
            is_weekend = d.weekday() >= 5
            day_start = datetime(YEAR, month, day, tzinfo=timezone.utc)

            # Temperature + traffic: every 5 minutes (288 slots/day).
            for slot in range(288):
                ts = day_start + timedelta(minutes=5 * slot)
                hour = ts.hour
                for s in temp_sensors:
                    reading_ts = ts
                    if s["id"] == CLOCK_BUG_SENSOR_ID and month == 12 and day >= 28:
                        reading_ts = ts.replace(year=YEAR + 1)
                    yield (s["id"], "temperature",
                           temp_value(month, hour, s["offset"], rng), reading_ts)
                for s in traffic_sensors:
                    yield (s["id"], "traffic",
                           traffic_value(hour, is_weekend, s["scale"], rng), ts)

            # Air quality: every 15 minutes (96 slots/day).
            for slot in range(96):
                ts = day_start + timedelta(minutes=15 * slot)
                hour = ts.hour
                for s in air_sensors:
                    spike = (s["id"], d) in spike_days
                    yield (s["id"], "air_quality", air_value(spike, hour, rng), ts)

            month_rows += 288 * (N_TEMP + N_TRAFFIC) + 96 * N_AIR
        print(f"  generated {calendar.month_name[month]} {YEAR} — {month_rows:,} rows")


def main() -> None:
    print(f"Connecting to: {DSN}")
    rng = random.Random(8)
    sensors = build_sensors(rng)
    spike_days = build_spike_days([s for s in sensors if s["sensor_type"] == "air_quality"], rng)

    with psycopg.connect(DSN) as conn:
        with conn.cursor() as cur:
            print("Creating schema …")
            cur.execute(DDL)

            print(f"Inserting {len(sensors)} sensors …")
            cur.executemany(
                "INSERT INTO sensors (id, sensor_type, label, neighborhood) VALUES (%s, %s, %s, %s)",
                [(s["id"], s["sensor_type"], s["label"], s["neighborhood"]) for s in sensors],
            )
        conn.commit()

        print("Generating and loading readings (this takes a few minutes) …")
        start = time.monotonic()
        with conn.cursor() as cur:
            with cur.copy(
                "COPY sensor_readings_staging (sensor_id, sensor_type, reading_value, recorded_at) "
                "FROM STDIN"
            ) as copy:
                count = 0
                for row in generate_rows(sensors, spike_days, rng):
                    copy.write_row(row)
                    count += 1
        conn.commit()
        elapsed = time.monotonic() - start

        print("Indexing staging table on recorded_at (mirrors a typical pre-partitioning table) …")
        with conn.cursor() as cur:
            cur.execute(
                "CREATE INDEX idx_sensor_readings_staging_recorded_at "
                "ON sensor_readings_staging (recorded_at)"
            )
        conn.commit()

        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM sensor_readings_staging")
            (total,) = cur.fetchone()
        print(f"Done — {total:,} rows in sensor_readings_staging "
              f"({elapsed:.1f}s to generate + load), {len(sensors)} sensors.")


if __name__ == "__main__":
    main()
