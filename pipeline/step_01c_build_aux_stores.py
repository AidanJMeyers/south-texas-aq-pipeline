"""Step 01c — Build auxiliary parquet stores (VOCs + 24hr-only criteria).

v0.4.0 addition. Companion to step_01 (criteria hourly parquet) for the three
NEW v0.4.0 tables that don't fit the canonical hourly criteria mold:

    1. ``vocs_1hr``             — VOC AutoGC 1hr cadence (5 county feeds)
    2. ``vocs_24hr``            — VOC AutoGC 24hr cadence (5 county feeds)
    3. ``pollutant_daily_24hr`` — 24hr block samplers (PM10 site 0060 today;
                                  extensible to any future Sample Duration
                                  Code 7 / X feed)

Inputs (all written by step_01b):
    01_Data/Processed/By_VOC/vocs_1hr_2016_2025.csv
    01_Data/Processed/By_VOC/vocs_24hr_2015_2025.csv
    01_Data/Processed/By_Pollutant_Daily/pollutant_daily_24hr_2015_2025.csv

Outputs:
    data/parquet/vocs_1hr/pollutant_name=*/year=YYYY/*.parquet
    data/parquet/vocs_24hr/pollutant_name=*/year=YYYY/*.parquet
    data/parquet/pollutant_daily_24hr/pollutant_group=*/year=YYYY/*.parquet

The VOC stores partition by ``pollutant_name`` (not ``pollutant_group``) because
every VOC row has ``pollutant_group="VOCs"`` — that would mean one giant
partition. Splitting by chemical species keeps partitions small and lets
downstream queries push down filters like ``pollutant_name="Benzene"`` cheaply.

Expected after a full v0.4.0 ingest:
    vocs_1hr             ≈ 4,964,065 rows
    vocs_24hr            ≈    97,244 rows
    pollutant_daily_24hr ≈       636 rows
"""

from __future__ import annotations

import sys

import pandas as pd

from pipeline.utils.io import (
    PipelineConfig,
    ensure_dir,
    load_config,
    read_pollutant_csv,
    write_parquet_partitioned,
)
from pipeline.utils.logging import get_logger, step_timer


# Month -> meteorological season (DJF/MAM/JJA/SON)
_SEASON_MAP = {
    12: "DJF", 1: "DJF", 2: "DJF",
    3: "MAM", 4: "MAM", 5: "MAM",
    6: "JJA", 7: "JJA", 8: "JJA",
    9: "SON", 10: "SON", 11: "SON",
}


def _enrich(df: pd.DataFrame) -> pd.DataFrame:
    """Add datetime/year/month/hour/season; normalize county_name casing."""
    dt = pd.to_datetime(
        df["date_local"].astype(str) + " " + df["time_local"].astype(str),
        format="%Y-%m-%d %H:%M",
        errors="coerce",
    )
    df = df.assign(
        datetime=dt,
        year=dt.dt.year.astype("Int16"),
        month=dt.dt.month.astype("Int8"),
        hour=dt.dt.hour.astype("Int8"),
        season=dt.dt.month.map(_SEASON_MAP).astype("string"),
        county_name=df["county_name"].str.title(),
    )
    n_before = len(df)
    df = df.dropna(subset=["datetime", "year"])
    if len(df) < n_before:
        df = df.copy()
    return df


def _build_one(
    label: str,
    csv_path,
    out_path,
    partition_cols: list[str],
    log,
) -> tuple[int, int]:
    """Read one CSV, enrich, write partitioned parquet. Returns (n_in, n_out)."""
    if not csv_path.exists():
        log.warning(f"{label}: {csv_path} does not exist — skipping")
        return (0, 0)

    with step_timer(log, f"build {label}"):
        df = read_pollutant_csv(csv_path)
        n_in = len(df)
        df = _enrich(df)
        n_out = len(df)
        ensure_dir(out_path)
        write_parquet_partitioned(df, out_path, partition_cols=partition_cols)
        log.info(
            f"  {label}: rows {n_in:,} → {n_out:,}, "
            f"sites={df['aqsid'].nunique()}, "
            f"chemicals={df['pollutant_name'].nunique()}, "
            f"years={sorted(df['year'].dropna().unique().tolist())}"
        )
    return (n_in, n_out)


def main(cfg: PipelineConfig | None = None) -> bool:
    cfg = cfg or load_config()
    log = get_logger("01c_build_aux_stores", log_dir=cfg.path("logs"))

    targets = [
        ("vocs_1hr",
         cfg.path("processed_voc_1hr"),
         cfg.path("parquet_vocs_1hr"),
         ["pollutant_name", "year"]),
        ("vocs_24hr",
         cfg.path("processed_voc_24hr"),
         cfg.path("parquet_vocs_24hr"),
         ["pollutant_name", "year"]),
        ("pollutant_daily_24hr",
         cfg.path("processed_daily_24hr"),
         cfg.path("parquet_daily_24hr"),
         ["pollutant_group", "year"]),
    ]

    log.info(f"Building {len(targets)} auxiliary parquet stores")
    grand_in = 0
    grand_out = 0
    for label, csv_path, out_path, partition_cols in targets:
        n_in, n_out = _build_one(label, csv_path, out_path, partition_cols, log)
        grand_in += n_in
        grand_out += n_out

    log.info(f"TOTAL rows in={grand_in:,} out={grand_out:,}")
    return True


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
