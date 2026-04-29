#!/usr/bin/env python3
"""
finish_hourly_tables_AM.py
Reload BOTH hourly tables (aq.pollutant_hourly + aq.weather_hourly) from
their parquet stores using Postgres COPY (10-100x faster than to_sql,
resilient to network blips because each chunk is its own transaction).

WHY THIS EXISTS:
  Step 07 of the April 28 pipeline run reported pollutant_hourly as
  successfully loaded after 5h 27min, but a Neon MCP verification
  afterwards revealed the table still contained the v0.3.5 data
  (latest Camp Bullis ozone date was 2025-10-31, not 2025-12-31).
  weather_hourly hit a PendingRollbackError after 36 minutes.

  The to_sql(method='multi') approach is slow AND silent-failure-prone
  for tables this size. COPY fixes both: streams data in a single
  connection per chunk, and chunk failures abort cleanly instead of
  poisoning the whole load.

  Daily/monthly/combined tables are already correct (verified — those
  use much smaller chunks and finished cleanly).

Usage:
    cd "C:\\Users\\aidan\\OneDrive\\Desktop\\AirQuality South TX"
    python notebooks/finish_hourly_tables_AM.py

    # Just one table:
    python notebooks/finish_hourly_tables_AM.py --only pollutant_hourly
    python notebooks/finish_hourly_tables_AM.py --only weather_hourly

Expected runtime: ~10-15 min total (pollutant_hourly ~10 min,
weather_hourly ~5 min).
"""
from __future__ import annotations

import argparse
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


def _normalize_url(url: str) -> str:
    """Force the psycopg (v3) driver. Without this, SQLAlchemy tries
    psycopg2 (which is not installed in this project)."""
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://") and "+psycopg" not in url:
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    if "sslmode=" not in url:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}sslmode=require"
    return url


URL = _normalize_url(URL)

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = "aq"

# Table specs: name -> (parquet_path, indexes)
TABLES = {
    "pollutant_hourly": (
        ROOT / "data" / "parquet" / "pollutants",
        ["aqsid", "date_local", "pollutant_group", "year"],
    ),
    "weather_hourly": (
        ROOT / "data" / "parquet" / "weather",
        ["location", "year", "date_local"],
    ),
}

CHUNK_SIZE = 100_000   # rows per COPY call


def load_partitioned_parquet(parquet_dir: Path) -> pd.DataFrame:
    """Read the partitioned parquet directory into a single DataFrame."""
    if not parquet_dir.exists():
        raise FileNotFoundError(f"{parquet_dir} does not exist — run upstream pipeline step first")
    files = list(parquet_dir.rglob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"No .parquet files under {parquet_dir}")
    print(f"  found {len(files)} parquet partition files")
    dataset = ds.dataset([str(f) for f in files], format="parquet", partitioning="hive")
    return dataset.to_table().to_pandas()


def copy_load(table: str, df: pd.DataFrame, engine, chunk_size: int) -> int:
    """Bulk-load via psycopg3 COPY with one transaction per chunk + retry."""
    total = 0
    t0 = time.time()
    cols_quoted = ",".join(f'"{c}"' for c in df.columns)

    for chunk_start in range(0, len(df), chunk_size):
        chunk = df.iloc[chunk_start:chunk_start + chunk_size]

        buf = io.StringIO()
        chunk.to_csv(buf, index=False, header=False, na_rep="\\N",
                      lineterminator="\n", date_format="%Y-%m-%d %H:%M:%S")
        payload = buf.getvalue().encode("utf-8")

        for attempt in range(3):
            raw_conn = engine.raw_connection()
            try:
                with raw_conn.cursor() as cur:
                    with cur.copy(
                        f'COPY {SCHEMA}."{table}" ({cols_quoted}) '
                        "FROM STDIN WITH (FORMAT CSV, HEADER false, NULL '\\N')"
                    ) as copy:
                        copy.write(payload)
                raw_conn.commit()
                break
            except Exception as e:
                raw_conn.rollback()
                if attempt < 2:
                    print(f"    chunk {chunk_start:,}: retrying after {type(e).__name__}: {e}")
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
        print(f"  {total:>10,}/{len(df):,}  ({pct:5.1f}%)  "
              f"{rate:>7,.0f} rows/s  ETA {eta_sec:>5.0f}s")

    return total


def reload_table(table: str, parquet_dir: Path, indexes: list[str], engine) -> None:
    print(f"\n{'=' * 70}")
    print(f"RELOAD: {SCHEMA}.{table}")
    print(f"{'=' * 70}")

    print(f"\n[1/5] Reading parquet from {parquet_dir} ...")
    t = time.time()
    df = load_partitioned_parquet(parquet_dir)
    print(f"  {len(df):,} rows × {df.shape[1]} cols  (read in {time.time()-t:.1f}s)")

    print(f"\n[2/5] DROP {SCHEMA}.{table} CASCADE  (this also drops dependent indexes)")
    with engine.begin() as conn:
        conn.execute(text(f'DROP TABLE IF EXISTS {SCHEMA}."{table}" CASCADE'))

    print(f"[3/5] CREATE {SCHEMA}.{table}  (schema inferred from parquet)")
    df.head(0).to_sql(table, engine, schema=SCHEMA, if_exists="fail",
                       index=False, method="multi")

    print(f"\n[4/5] Bulk-loading {len(df):,} rows via COPY (chunks of {CHUNK_SIZE:,}) ...")
    total = copy_load(table, df, engine, CHUNK_SIZE)
    if total != len(df):
        raise RuntimeError(f"COPY total mismatch: parquet={len(df):,} loaded={total:,}")

    print(f"\n[5/5] Creating indexes ...")
    with engine.begin() as conn:
        for col in indexes:
            idx_name = f"ix_{table}_{col}"
            conn.execute(text(
                f'CREATE INDEX IF NOT EXISTS "{idx_name}" '
                f'ON {SCHEMA}."{table}" ("{col}")'
            ))
            print(f"  created {idx_name}")

    # Re-grant SELECT to the Data API roles (DROP CASCADE wiped them)
    print(f"\n[grants] re-granting SELECT to anonymous + authenticated ...")
    with engine.begin() as conn:
        conn.execute(text(
            f'GRANT SELECT ON {SCHEMA}."{table}" TO anonymous, authenticated'
        ))

    print(f"\n[verify] Counting rows in Neon ...")
    with engine.connect() as conn:
        actual = conn.execute(text(f'SELECT COUNT(*) FROM {SCHEMA}."{table}"')).scalar_one()
        size = conn.execute(text(
            f"SELECT pg_size_pretty(pg_total_relation_size('{SCHEMA}.{table}'::regclass))"
        )).scalar_one()
    if actual == len(df):
        print(f"  ✓ {SCHEMA}.{table}: {actual:,} rows · {size}  (matches parquet)")
    else:
        print(f"  ⚠ {SCHEMA}.{table}: {actual:,} rows · {size}  (parquet was {len(df):,})")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", choices=list(TABLES.keys()),
                     help="Reload only this one table (default: both)")
    args = ap.parse_args()

    targets = [args.only] if args.only else list(TABLES.keys())

    print("=" * 70)
    print(f"HOURLY TABLE RELOAD via COPY  ·  targets: {', '.join(targets)}")
    print("=" * 70)

    engine = create_engine(URL, pool_pre_ping=True, future=True)

    t_total = time.time()
    for table in targets:
        parquet_dir, indexes = TABLES[table]
        reload_table(table, parquet_dir, indexes, engine)

    print(f"\n{'=' * 70}")
    print(f"DONE ✓   total runtime: {(time.time() - t_total) / 60:.1f} min")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
