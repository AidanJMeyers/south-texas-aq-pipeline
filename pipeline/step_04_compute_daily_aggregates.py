"""Step 04 — Daily & monthly pollutant aggregates.

Computes per-site, per-parameter daily statistics with a 75% hourly
completeness flag, then rolls up to monthly. Notebooks that currently
recompute daily means on every run should load from
``data/csv/daily_pollutant_means.csv`` instead.

Inputs:
    data/parquet/pollutants/

Outputs:
    data/parquet/daily/pollutant_daily.parquet
    data/parquet/daily/pollutant_monthly.parquet
    data/csv/daily_pollutant_means.csv

Runtime: ~1–2 minutes.
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from pipeline.utils.io import (
    PipelineConfig,
    ensure_dir,
    load_config,
    read_parquet_dataset,
    write_csv,
)
from pipeline.utils.logging import get_logger, step_timer


def _daily_agg(df: pd.DataFrame, completeness_threshold: float) -> pd.DataFrame:
    """One row per (aqsid, date_local, parameter_code, pollutant_name)."""
    g = df.groupby(
        ["aqsid", "date_local", "parameter_code", "pollutant_name",
         "pollutant_group", "county_name", "site_name"],
        dropna=False,
    )["sample_measurement"]
    daily = g.agg(
        mean="mean",
        min="min",
        max="max",
        std="std",
        n_hours="count",
    ).reset_index()
    daily["completeness_pct"] = daily["n_hours"] / 24.0
    daily["valid_day"] = daily["completeness_pct"] >= completeness_threshold
    return daily


def _monthly_agg(daily: pd.DataFrame) -> pd.DataFrame:
    """Roll daily→monthly using only valid days."""
    d = daily[daily["valid_day"]].copy()
    d["year_month"] = pd.to_datetime(d["date_local"]).dt.to_period("M").astype(str)
    g = d.groupby(
        ["aqsid", "year_month", "parameter_code", "pollutant_name",
         "pollutant_group", "county_name", "site_name"],
        dropna=False,
    )["mean"]
    monthly = g.agg(
        monthly_mean="mean",
        monthly_min="min",
        monthly_max="max",
        monthly_std="std",
        n_valid_days="count",
    ).reset_index()
    return monthly


def main(cfg: PipelineConfig | None = None) -> bool:
    cfg = cfg or load_config()
    log = get_logger("04_compute_daily_aggregates", log_dir=cfg.path("logs"))

    pq_poll = cfg.path("parquet_pollutants")
    if not pq_poll.exists():
        log.error(f"Pollutant parquet store not found: {pq_poll}  (run step 01 first)")
        return False

    completeness = float(cfg.get("data_quality", "hourly_completeness_threshold", default=0.75))

    with step_timer(log, "load pollutant parquet"):
        df = read_parquet_dataset(
            pq_poll,
            columns=[
                "aqsid", "date_local", "parameter_code", "pollutant_name",
                "pollutant_group", "county_name", "site_name", "sample_measurement",
            ],
        )
    log.info(f"  rows loaded: {len(df):,}")

    with step_timer(log, "daily aggregation"):
        daily = _daily_agg(df, completeness_threshold=completeness)
    log.info(
        f"  daily rows: {len(daily):,}  "
        f"valid={daily['valid_day'].sum():,}  "
        f"invalid={(~daily['valid_day']).sum():,}"
    )

    with step_timer(log, "monthly aggregation"):
        monthly = _monthly_agg(daily)
    log.info(f"  monthly rows: {len(monthly):,}")

    # Write outputs
    daily_out = ensure_dir(cfg.path("parquet_daily"))
    daily.to_parquet(daily_out / "pollutant_daily.parquet", index=False)
    monthly.to_parquet(daily_out / "pollutant_monthly.parquet", index=False)

    csv_out = cfg.path("csv_exports") / "daily_pollutant_means.csv"
    write_csv(daily, csv_out)

    log.info(f"  parquet: {daily_out}")
    log.info(f"  csv:     {csv_out}")
    return True


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
