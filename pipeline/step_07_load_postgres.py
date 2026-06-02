"""Step 07 — Load all analysis tables into Postgres via COPY.

v0.4.0 rewrite. Replaces the v0.3.7 ``to_sql(method='multi')`` loader which
was 10-100x slower and silent-failure-prone on big tables (the v0.3.7 run
took 5.5 hr and produced a stale ``weather_hourly`` table; see
``notebooks/finish_hourly_tables_AM.py`` for the recovery script that
inspired this rewrite).

Strategy:
    1. For every table in ``config.yaml:postgres.tables``:
         a. Read source (CSV, single parquet, or partitioned parquet_dir)
         b. DROP TABLE IF EXISTS ... CASCADE  (idempotent)
         c. CREATE TABLE via df.head(0).to_sql (schema inferred from pandas)
         d. Bulk-load all rows via ``COPY ... FROM STDIN WITH (FORMAT CSV)``
            in 100K-row chunks, one transaction per chunk, with retry.
         e. CREATE INDEX for each configured index column.
    2. After every table loaded, re-GRANT SELECT to the Data API roles
       (anonymous, authenticated) and set DEFAULT PRIVILEGES so future
       schema changes don't break the read-only roles.

Credentials:
    Reads ``AQ_POSTGRES_URL`` from env. Skips with a warning if unset.

Idempotency:
    Each table is DROP-then-CREATE on every run. Safe to re-run.

Runtime: ~15-25 min for a full v0.4.0 load (~11 M rows across 10 tables).

Tables loaded (v0.4.0 set, source-of-truth = ``config.yaml:postgres.tables``):
    aq.site_registry            ~42 rows         (csv)
    aq.parameter_reference     ~57 rows         (csv)
    aq.naaqs_design_values    ~759 rows         (parquet)
    aq.pollutant_daily      ~201K rows          (parquet)
    aq.pollutant_daily_24hr   ~636 rows         (parquet_dir)
    aq.pollutant_monthly      ~7K rows          (parquet)
    aq.pollutant_hourly      ~4.7M rows         (parquet_dir)
    aq.vocs_1hr              ~5.0M rows         (parquet_dir)
    aq.vocs_24hr             ~97K rows          (parquet_dir)
    aq.weather_hourly        ~1.5M rows         (parquet_dir)
"""

from __future__ import annotations

import io
import sys
import time
from pathlib import Path

import pandas as pd
import pyarrow.dataset as ds
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from pipeline.utils.db import ensure_schema, get_engine, is_quota_error, ping
from pipeline.utils.io import PipelineConfig, load_config
from pipeline.utils.logging import get_logger, step_timer


COPY_CHUNK = 100_000          # Rows per COPY call
DATA_API_ROLES = ("anonymous", "authenticated")


# ---------------------------------------------------------------------------
# Source readers
# ---------------------------------------------------------------------------
def _load_source(path: Path, source: str) -> pd.DataFrame:
    """Read CSV, single parquet, or partitioned parquet directory."""
    if not path.exists():
        raise FileNotFoundError(f"{path} — upstream step must run first")
    if source == "csv":
        return pd.read_csv(path)
    if source == "parquet":
        return pd.read_parquet(path)
    if source == "parquet_dir":
        # Enumerate .parquet files explicitly so OneDrive's desktop.ini
        # sidecars don't break the dataset scan.
        files = [str(p) for p in path.rglob("*.parquet")]
        if not files:
            raise FileNotFoundError(f"No .parquet files under {path}")
        dataset = ds.dataset(files, format="parquet", partitioning="hive")
        return dataset.to_table().to_pandas()
    raise ValueError(f"Unknown source type: {source!r}")


# ---------------------------------------------------------------------------
# COPY-based bulk load
# ---------------------------------------------------------------------------
def _copy_load(engine, schema: str, table: str, df: pd.DataFrame, log) -> int:
    """Stream the DataFrame into Postgres via psycopg COPY.

    - One transaction per chunk: a single bad chunk aborts only itself,
      not the whole load (and we retry transient errors up to 3x).
    - Uses raw psycopg connection (engine.raw_connection()) because
      SQLAlchemy 2.x doesn't expose COPY directly.

    Returns total rows COPYed.
    """
    cols_quoted = ",".join(f'"{c}"' for c in df.columns)
    total = 0
    t0 = time.time()

    for chunk_start in range(0, len(df), COPY_CHUNK):
        chunk = df.iloc[chunk_start:chunk_start + COPY_CHUNK]
        buf = io.StringIO()
        chunk.to_csv(
            buf,
            index=False,
            header=False,
            na_rep="\\N",
            lineterminator="\n",
            date_format="%Y-%m-%d %H:%M:%S",
        )
        payload = buf.getvalue().encode("utf-8")

        for attempt in range(3):
            raw_conn = engine.raw_connection()
            try:
                with raw_conn.cursor() as cur:
                    with cur.copy(
                        f'COPY "{schema}"."{table}" ({cols_quoted}) '
                        "FROM STDIN WITH (FORMAT CSV, HEADER false, NULL '\\N')"
                    ) as copy:
                        copy.write(payload)
                raw_conn.commit()
                break
            except Exception as e:
                raw_conn.rollback()
                if attempt < 2:
                    log.warning(
                        f"  chunk {chunk_start:,}: retry {attempt+1}/3 after "
                        f"{type(e).__name__}: {e}"
                    )
                    time.sleep(2 ** attempt)
                else:
                    raise
            finally:
                raw_conn.close()

        total += len(chunk)
        elapsed = time.time() - t0
        rate = total / elapsed if elapsed > 0 else 0
        eta = (len(df) - total) / rate if rate > 0 else 0
        pct = 100 * total / len(df)
        log.info(
            f"  {total:>10,}/{len(df):,}  ({pct:5.1f}%)  "
            f"{rate:>7,.0f} rows/s  ETA {eta:>5.0f}s"
        )

    return total


def _load_table(engine, schema: str, spec: dict, cfg: PipelineConfig, log) -> bool:
    name = spec["name"]
    path = cfg.root / spec["path"]
    source = spec["source"]
    skip_on_quota = bool(spec.get("skip_on_quota_error", False))
    indexes = list(spec.get("indexes", []))

    with step_timer(log, f"load {schema}.{name}"):
        # 1. Read source
        try:
            df = _load_source(path, source)
        except FileNotFoundError as e:
            log.error(f"  {name}: {e}")
            return False
        log.info(f"  {name}: {len(df):,} rows × {df.shape[1]} cols from {path.name}")

        # 2. Drop + create empty table with inferred schema
        try:
            with engine.begin() as conn:
                conn.execute(text(f'DROP TABLE IF EXISTS "{schema}"."{name}" CASCADE'))
            df.head(0).to_sql(
                name=name,
                con=engine,
                schema=schema,
                if_exists="fail",   # we just dropped; this confirms empty creation
                index=False,
                method="multi",
            )
        except SQLAlchemyError as e:
            log.exception(f"  {name}: CREATE failed")
            return False

        # 3. Bulk load via COPY
        try:
            n = _copy_load(engine, schema, name, df, log)
            if n != len(df):
                log.error(f"  {name}: COPY mismatch parquet={len(df):,} loaded={n:,}")
                return False
        except SQLAlchemyError as e:
            if skip_on_quota and is_quota_error(e):
                log.warning(f"  {name}: quota error; skipping (non-fatal): {e}")
                return True
            log.exception(f"  {name}: COPY failed")
            return False
        except Exception as e:
            log.exception(f"  {name}: COPY failed with {type(e).__name__}")
            return False

        # 4. Indexes
        if indexes:
            with engine.begin() as conn:
                for col in indexes:
                    if col not in df.columns:
                        log.warning(f"  {name}: index column {col!r} missing, skipping")
                        continue
                    idx = f"ix_{name}_{col}"
                    conn.execute(text(
                        f'CREATE INDEX IF NOT EXISTS "{idx}" '
                        f'ON "{schema}"."{name}" ("{col}")'
                    ))
            log.info(f"  {name}: indexes created for {indexes}")

        # 5. Re-grant SELECT to Data API roles for this table
        try:
            with engine.begin() as conn:
                for role in DATA_API_ROLES:
                    conn.execute(text(
                        f'GRANT SELECT ON "{schema}"."{name}" TO {role}'
                    ))
        except SQLAlchemyError as e:
            # Non-fatal: maybe the roles don't exist on this DB
            log.warning(f"  {name}: GRANT to Data API roles failed (non-fatal): {e}")

    return True


def _set_default_privileges(engine, schema: str, log) -> None:
    """ALTER DEFAULT PRIVILEGES so future tables in this schema auto-grant
    SELECT to Data API roles. Best-effort — log warnings on failure."""
    for role in DATA_API_ROLES:
        try:
            with engine.begin() as conn:
                conn.execute(text(
                    f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{schema}" '
                    f'GRANT SELECT ON TABLES TO {role}'
                ))
            log.info(f"  default SELECT privileges set for {role}")
        except SQLAlchemyError as e:
            log.warning(f"  could not set default privileges for {role}: {e}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(cfg: PipelineConfig | None = None) -> bool:
    cfg = cfg or load_config()
    log = get_logger("07_load_postgres", log_dir=cfg.path("logs"))

    pg_cfg = cfg.get("postgres", default={})
    if not pg_cfg.get("enabled", True):
        log.info("Postgres loader disabled in config; skipping.")
        return True

    engine = get_engine(log)
    if engine is None:
        log.warning("No AQ_POSTGRES_URL — skipping Postgres loader (not a failure).")
        return True

    try:
        with step_timer(log, "ping Postgres"):
            version = ping(engine)
        log.info(f"  server: {version[:80]}")
    except SQLAlchemyError as e:
        log.error(f"Could not connect to Postgres: {e}")
        return False

    schema = pg_cfg.get("schema", "aq")
    ensure_schema(engine, schema)
    log.info(f"Schema ready: {schema}")

    specs = pg_cfg.get("tables", [])
    if not specs:
        log.error("No tables configured under postgres.tables")
        return False

    log.info(f"Loading {len(specs)} tables via COPY into schema {schema!r}")

    overall_ok = True
    for spec in specs:
        ok = _load_table(engine, schema, spec, cfg, log)
        if not ok:
            overall_ok = False

    # Set DEFAULT PRIVILEGES so any future tables (e.g. v0.4.1 additions)
    # auto-grant SELECT to Data API roles without manual intervention.
    _set_default_privileges(engine, schema, log)

    if overall_ok:
        log.info(f"Postgres load complete: {len(specs)} tables loaded into {schema}.")
    return overall_ok


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
