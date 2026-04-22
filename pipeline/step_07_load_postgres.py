"""Step 07 — Load analysis-ready tables into Postgres.

Loads the small/medium analysis-ready outputs into a Postgres database so
collaborators and BI tools can query them with plain SQL. The raw hourly
pollutant + weather data **stays in parquet** — it is too large for free-tier
Postgres and rarely needed in SQL form.

Loaded tables (configurable via ``config.yaml:postgres.tables``):
    aq.site_registry
    aq.naaqs_design_values
    aq.pollutant_daily
    aq.pollutant_monthly
    aq.aq_weather_daily

Credentials:
    Reads the connection URL from the ``AQ_POSTGRES_URL`` environment
    variable. If unset, this step is **skipped with a warning** — it is
    optional and not a hard failure.

Idempotency:
    Default ``if_exists='replace'`` drops and recreates each table on every
    run. Switch to ``'append'`` in config if you need incremental loading.

Quota handling:
    On Neon / Supabase free tier, the big ``aq_weather_daily`` table may
    push storage over the limit. Any table with ``skip_on_quota_error: true``
    will be skipped (with a warning) if the insert raises a quota-like
    error, and the remaining tables continue loading.

Runtime: ~1–3 minutes depending on network latency to Neon.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
from sqlalchemy.exc import SQLAlchemyError

from pipeline.utils.db import (
    create_indexes,
    ensure_schema,
    get_engine,
    is_quota_error,
    ping,
)
from pipeline.utils.io import PipelineConfig, load_config
from pipeline.utils.logging import get_logger, step_timer


def _load_source(path: Path, source: str) -> pd.DataFrame:
    """Read a parquet file, parquet directory, or CSV into a DataFrame."""
    if not path.exists():
        raise FileNotFoundError(f"{path} — upstream step must run first")
    if source == "parquet":
        return pd.read_parquet(path)
    if source == "parquet_dir":
        # Partitioned Hive directory — glob for *.parquet to avoid
        # OneDrive desktop.ini pollution (same approach as io.py).
        files = list(path.rglob("*.parquet"))
        if not files:
            raise FileNotFoundError(f"No .parquet files under {path}")
        import pyarrow.dataset as ds
        dataset = ds.dataset(
            [str(f) for f in files], format="parquet", partitioning="hive"
        )
        return dataset.to_table().to_pandas()
    if source == "csv":
        return pd.read_csv(path)
    raise ValueError(f"Unknown source type: {source!r}")


def _load_table(engine, schema: str, spec: dict, cfg: PipelineConfig, log) -> bool:
    """Load a single table spec into Postgres. Returns True on success."""
    name   = spec["name"]
    path   = cfg.root / spec["path"]
    source = spec["source"]
    skip_on_quota = bool(spec.get("skip_on_quota_error", False))
    indexes = list(spec.get("indexes", []))

    with step_timer(log, f"load {schema}.{name} from {path.name}"):
        try:
            df = _load_source(path, source)
        except FileNotFoundError as e:
            log.error(f"  {name}: {e}")
            return False

        log.info(f"  {name}: {len(df):,} rows × {df.shape[1]} cols")

        if_exists = cfg.get("postgres", "if_exists", default="replace")
        # Postgres allows at most 65535 parameters per statement. With
        # method='multi' the parameter count = chunksize * ncols, so we
        # clamp chunksize so we never cross that ceiling.
        ncols = max(df.shape[1], 1)
        safe_chunksize = max(min(int(65000 / ncols), 10000), 100)
        chunksize = min(
            int(cfg.get("postgres", "chunksize", default=50000)),
            safe_chunksize,
        )
        if chunksize != int(cfg.get("postgres", "chunksize", default=50000)):
            log.info(f"  {name}: chunksize clamped to {chunksize} (ncols={ncols})")

        try:
            df.to_sql(
                name=name,
                con=engine,
                schema=schema,
                if_exists=if_exists,
                index=False,
                chunksize=chunksize,
                method="multi",
            )
        except SQLAlchemyError as e:
            if skip_on_quota and is_quota_error(e):
                log.warning(
                    f"  {name}: quota/storage error — skipping (non-fatal). "
                    f"Free-tier storage may be full. Raw error: {e}"
                )
                return True  # non-fatal
            log.exception(f"  {name}: load failed")
            return False

        # Indexes
        if indexes:
            existing = [c for c in indexes if c in df.columns]
            created = create_indexes(engine, schema, name, existing)
            log.info(f"  {name}: indexes {created}")

    return True


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

    # Connectivity check
    try:
        with step_timer(log, "ping Postgres"):
            version = ping(engine)
        log.info(f"  server: {version}")
    except SQLAlchemyError as e:
        log.error(f"Could not connect to Postgres: {e}")
        log.error("Check AQ_POSTGRES_URL; on Neon free tier the DB may be paused — retry once.")
        return False

    schema = pg_cfg.get("schema", "aq")
    ensure_schema(engine, schema)
    log.info(f"Schema ready: {schema}")

    specs = pg_cfg.get("tables", [])
    if not specs:
        log.error("No tables configured under postgres.tables")
        return False

    overall_ok = True
    for spec in specs:
        ok = _load_table(engine, schema, spec, cfg, log)
        if not ok:
            overall_ok = False

    if overall_ok:
        log.info(f"Postgres load complete: {len(specs)} table specs processed.")
    return overall_ok


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
