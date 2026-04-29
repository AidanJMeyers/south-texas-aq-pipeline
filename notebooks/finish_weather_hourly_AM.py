#!/usr/bin/env python3
"""
finish_weather_hourly_AM.py
Recover from the step 07 failure on 2026-04-29 by loading aq.weather_hourly
via Postgres COPY (10-100x faster than pandas.to_sql, resilient to network
blips because each chunk is its own transaction).

Pollutant_hourly + the 5 aggregate tables are assumed to be loaded
correctly already — this script does NOT touch them.

Usage:
    cd "C:\\Users\\aidan\\OneDrive\\Desktop\\AirQuality South TX"
    python notebooks/finish_weather_hourly_AM.py

Expected runtime: ~3-5 minutes (vs. ~30+ min for to_sql).

Requirements:
    AQ_POSTGRES_URL env var must be set (the same one the pipeline uses).
"""
from __future__ import annotations

import io
import os
import sys
import time
from pathlib import Path

import pandas as pd
import pyarrow.dataset as ds
from sqlalchemy import create_engine, text


URL = os.environ.get("AQ_POSTGRES_URL")
if not URL:
    print("ERROR: AQ_POSTGRES_URL is not set in environment.")
    print("In a fresh PowerShell window:")
    print('  $env:AQ_POSTGRES_URL = [Environment]::GetEnvironmentVariable("AQ_POSTGRES_URL","User")')
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent
WEATHER_PARQUET = ROOT / "data" / "parquet" / "weather"
SCHEMA     = "aq"
TABLE      = "weather_hourly"
CHUNK_SIZE = 100_000   # rows per COPY call — each is its own transaction

INDEXES = ["location", "year", "date_local"]


def load_weather_parquet() -> pd.DataFrame:
    """Read the partitioned weather parquet into a single DataFrame."""
    if not WEATHER_PARQUET.exists():
        raise FileNotFoundError(f"{WEATHER_PARQUET} does not exist — run pipeline step 02 first")
    files = list(WEATHER_PARQUET.rglob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"No .parquet files under {WEATHER_PARQUET}")
    print(f"  found {len(files)} parquet partition files")
    dataset = ds.dataset([str(f) for f in files], format="parquet", partitioning="hive")
    return dataset.to_table().to_pandas()


def copy_chunked(df: pd.DataFrame, engine, chunk_size: int) -> int:
    """Bulk-load via psycopg3 COPY with one transaction per chunk."""
    total = 0
    t0 = time.time()
    cols = ",".join(f'"{c}"' for c in df.columns)

    for chunk_start in range(0, len(df), chunk_size):
        chunk = df.iloc[chunk_start:chunk_start + chunk_size]

        buf = io.StringIO()
        chunk.to_csv(buf, index=False, header=False, na_rep="\\N",
                      lineterminator="\n", date_format="%Y-%m-%d %H:%M:%S")
        buf.seek(0)
        payload = buf.getvalue().encode("utf-8")

        # Each chunk = its own raw connection + commit.  If a single chunk
        # fails the connection, it doesn't poison the whole load.
        for attempt in range(3):
            raw_conn = engine.raw_connection()
            try:
                with raw_conn.cursor() as cur:
                    with cur.copy(
                        f'COPY {SCHEMA}."{TABLE}" ({cols}) '
                        "FROM STDIN WITH (FORMAT CSV, HEADER false, NULL '\\N')"
                    ) as copy:
                        copy.write(payload)
                raw_conn.commit()
                break
            except Exception as e:
                raw_conn.rollback()
                if attempt < 2:
                    print(f"    chunk {chunk_start:,}: retrying after error: {type(e).__name__}")
                    time.sleep(2 ** attempt)
                else:
                    raise
            finally:
                raw_conn.close()

        total += len(chunk)
        elapsed = time.time() - t0
        rate = total / elapsed if elapsed > 0 else 0
        eta_sec = (len(df) - total) / rate if rate > 0 else 0
        pct = 100 * total / len(df)
        print(f"  {total:>10,}/{len(df):,} rows  ({pct:5.1f}%)  "
              f"{rate:>7,.0f} rows/s  ETA {eta_sec:>5.0f}s")

    return total


def main() -> None:
    print("=" * 70)
    print("RECOVERY: load aq.weather_hourly via COPY")
    print("=" * 70)

    print(f"\n[1/4] Loading weather parquet from {WEATHER_PARQUET} ...")
    df = load_weather_parquet()
    print(f"  {len(df):,} rows × {df.shape[1]} cols")

    engine = create_engine(URL, pool_pre_ping=True, future=True)

    print(f"\n[2/4] Dropping + recreating {SCHEMA}.{TABLE} ...")
    with engine.begin() as conn:
        conn.execute(text(f'DROP TABLE IF EXISTS {SCHEMA}."{TABLE}" CASCADE'))
    # Use to_sql to create the empty table with the right schema (0 rows)
    df.head(0).to_sql(TABLE, engine, schema=SCHEMA, if_exists="fail",
                       index=False, method="multi")
    print(f"  created empty {SCHEMA}.{TABLE}")

    print(f"\n[3/4] Bulk-loading {len(df):,} rows via COPY (chunks of {CHUNK_SIZE:,}) ...")
    total = copy_chunked(df, engine, CHUNK_SIZE)
    print(f"  → loaded {total:,} rows")

    print(f"\n[4/4] Creating indexes ...")
    with engine.begin() as conn:
        for col in INDEXES:
            idx_name = f"ix_{TABLE}_{col}"
            conn.execute(text(
                f'CREATE INDEX IF NOT EXISTS "{idx_name}" '
                f'ON {SCHEMA}."{TABLE}" ("{col}")'
            ))
            print(f"  created {idx_name}")

    print(f"\n[verify] Counting rows ...")
    with engine.connect() as conn:
        actual = conn.execute(text(f'SELECT COUNT(*) FROM {SCHEMA}."{TABLE}"')).scalar_one()
        size = conn.execute(text(
            f"SELECT pg_size_pretty(pg_total_relation_size('{SCHEMA}.{TABLE}'::regclass))"
        )).scalar_one()
    print(f"  ✓ {SCHEMA}.{TABLE}: {actual:,} rows · {size}")
    if actual != len(df):
        print(f"  ⚠ row count mismatch: parquet had {len(df):,}, table has {actual:,}")
        sys.exit(2)

    print("\n" + "=" * 70)
    print("DONE ✓")
    print("=" * 70)


if __name__ == "__main__":
    main()
