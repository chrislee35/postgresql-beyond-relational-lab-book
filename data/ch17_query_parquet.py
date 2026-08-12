#!/usr/bin/env python3.12
"""
Chapter 17, Exercise 6 — sanity-check the Parquet export by querying it
directly out of MinIO with DuckDB, no PostgreSQL or parquet_s3_fdw
involved. DuckDB can read Parquet straight off an S3-compatible
endpoint via its httpfs extension, treating all eleven monthly files
as one logical table with a glob pattern.

Usage:
    python ch17_query_parquet.py
"""

import duckdb

MINIO_ENDPOINT = "localhost:9000"
MINIO_ACCESS_KEY = "minioadmin"
MINIO_SECRET_KEY = "minioadmin"
BUCKET = "portsmith-bucket"

con = duckdb.connect()
con.execute("INSTALL httpfs; LOAD httpfs;")
con.execute(f"""
    SET s3_endpoint = '{MINIO_ENDPOINT}';
    SET s3_access_key_id = '{MINIO_ACCESS_KEY}';
    SET s3_secret_access_key = '{MINIO_SECRET_KEY}';
    SET s3_use_ssl = false;
    SET s3_url_style = 'path';
""")

PARQUET_GLOB = f"s3://{BUCKET}/sensor_readings/*.parquet"

print("--- row count across all 11 files ---")
print(con.execute(f"SELECT COUNT(*) FROM read_parquet('{PARQUET_GLOB}')").fetchone())

print("\n--- daily average temperature, one week in June ---")
for row in con.execute(f"""
    SELECT reading_date, round(avg(reading_value), 2) AS avg_temp
    FROM   read_parquet('{PARQUET_GLOB}')
    WHERE  sensor_type = 'temperature'
    AND    reading_date BETWEEN DATE '2024-06-01' AND DATE '2024-06-07'
    GROUP  BY reading_date
    ORDER  BY reading_date
""").fetchall():
    print(row)

print("\n--- EXPLAIN ANALYZE: confirm pruning by bytes actually transferred ---")
con.execute(f"""
    EXPLAIN ANALYZE SELECT COUNT(*) FROM read_parquet('{PARQUET_GLOB}')
    WHERE reading_date = DATE '2024-06-15'
""")
for row in con.fetchall():
    print(row[1])
