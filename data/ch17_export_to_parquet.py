#!/usr/bin/env python3.12
"""
Chapter 17, Exercise 6 — export sensor_readings partitions to Parquet
and upload them to a MinIO bucket. The data half of the parquet_s3_fdw
architecture sketch: one Parquet file per monthly partition, uploaded
to S3-compatible object storage, ready for a foreign table to read
back later.

Usage:
    python ch17_export_to_parquet.py [--months 2024-02,2024-03] [DSN]

    Defaults to exporting every month currently present in
    sensor_readings (Chapter 8 dropped January, so this is Feb-Dec
    2024 by default). DSN defaults to "dbname=portsmith".
"""

import argparse
import calendar
import io
from datetime import date, timedelta

import boto3
import psycopg
import pyarrow as pa
import pyarrow.parquet as pq

MINIO_ENDPOINT = "http://localhost:9000"
MINIO_ACCESS_KEY = "minioadmin"
MINIO_SECRET_KEY = "minioadmin"
BUCKET = "portsmith-bucket"

DEFAULT_MONTHS = [f"2024-{m:02d}" for m in range(2, 13)]  # Feb-Dec 2024

QUERY = """
SELECT sensor_id, sensor_type, reading_value, recorded_at, reading_date
FROM   sensor_readings
WHERE  reading_date >= %(start)s AND reading_date < %(end)s
ORDER  BY recorded_at
"""


def month_bounds(year_month: str) -> tuple[date, date]:
    year, month = (int(p) for p in year_month.split("-"))
    start = date(year, month, 1)
    days = calendar.monthrange(year, month)[1]
    end = date(year, month, days) + timedelta(days=1)
    return start, end


def export_month(conn: psycopg.Connection, year_month: str) -> pa.Table:
    start, end = month_bounds(year_month)
    with conn.cursor() as cur:
        cur.execute(QUERY, {"start": start, "end": end})
        rows = cur.fetchall()

    sensor_id, sensor_type, reading_value, recorded_at, reading_date = (
        [r[i] for r in rows] for i in range(5)
    )
    table = pa.table({
        "sensor_id": pa.array(sensor_id, type=pa.int32()),
        "sensor_type": pa.array(sensor_type, type=pa.string()),
        "reading_value": pa.array(reading_value, type=pa.float64()),
        "recorded_at": pa.array(recorded_at, type=pa.timestamp("us", tz="UTC")),
        "reading_date": pa.array(reading_date, type=pa.date32()),
    })
    return table


def upload_parquet(s3, table: pa.Table, year_month: str) -> int:
    buf = io.BytesIO()
    pq.write_table(table, buf, compression="snappy")
    size = buf.tell()
    buf.seek(0)
    key = f"sensor_readings/{year_month}.parquet"
    s3.upload_fileobj(buf, BUCKET, key)
    return size


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--months", default=",".join(DEFAULT_MONTHS),
                         help="Comma-separated YYYY-MM list (default: Feb-Dec 2024)")
    parser.add_argument("dsn", nargs="?", default="dbname=portsmith")
    args = parser.parse_args()
    months = args.months.split(",")

    s3 = boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
    )

    existing = [b["Name"] for b in s3.list_buckets().get("Buckets", [])]
    if BUCKET not in existing:
        s3.create_bucket(Bucket=BUCKET)
        print(f"created bucket {BUCKET!r}")

    print(f"connecting to: {args.dsn}")
    with psycopg.connect(args.dsn) as conn:
        total_rows = 0
        total_bytes = 0
        for year_month in months:
            table = export_month(conn, year_month)
            size = upload_parquet(s3, table, year_month)
            total_rows += table.num_rows
            total_bytes += size
            print(f"  {year_month}: {table.num_rows:,} rows -> "
                  f"s3://{BUCKET}/sensor_readings/{year_month}.parquet ({size:,} bytes)")

    print(f"done — {total_rows:,} rows, {total_bytes:,} bytes across {len(months)} files")


if __name__ == "__main__":
    main()
