"""Step 02 — Build the partitioned weather parquet store.

Reads the Weather_Irradiance_Master CSV and writes a Hive-partitioned
parquet dataset partitioned by ``location`` (station) + ``year``.

The upstream weather master has already been enriched by prior project
scripts with the derived columns I would have added from scratch — it
already contains ``temp_f``, ``wind_u``, ``wind_v``, ``heat_index_c``,
``td_spread``, and ``is_raining``. ``temp`` is already in **Celsius**
(verified by ``temp_f ≈ temp*9/5+32``), so no Kelvin conversion is needed.

Adjustments this step does make:
    * Rename ``site_name`` → ``location`` (the spec's partition key)
    * Add ``temp_c`` as an alias of ``temp`` for schema stability downstream
    * Normalize ``location`` to a filesystem-safe string for Hive partitions
    * Ensure ``hour`` column exists (source uses ``hour_local``)

Inputs:
    01_Data/Processed/Meteorological/Weather_Irradiance_Master_2015_2025.csv

Outputs:
    data/parquet/weather/location=X/year=YYYY/*.parquet

Expected: ~1.47M rows × 15 stations. Runtime: ~2–4 minutes.
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from pipeline.utils.io import (
    PipelineConfig,
    ensure_dir,
    load_config,
    write_parquet_partitioned,
)
from pipeline.utils.logging import get_logger, step_timer


STATION_COL_CANDIDATES = ("location", "site_name", "station", "station_name")


def _pick_station_col(df: pd.DataFrame) -> str:
    for c in STATION_COL_CANDIDATES:
        if c in df.columns:
            return c
    raise KeyError(
        f"Weather master has no station identifier column. Tried: {STATION_COL_CANDIDATES}. "
        f"Actual columns: {list(df.columns)}"
    )


def _ensure_time_cols(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure year/month/hour exist. Parse datetime_local if needed."""
    # Year already present in this file
    if "hour" not in df.columns:
        if "hour_local" in df.columns:
            df["hour"] = df["hour_local"].astype("Int8")
        elif "datetime_local" in df.columns:
            df["hour"] = pd.to_datetime(df["datetime_local"], errors="coerce").dt.hour.astype("Int8")
    if "month" not in df.columns and "datetime_local" in df.columns:
        df["month"] = pd.to_datetime(df["datetime_local"], errors="coerce").dt.month.astype("Int8")
    if "year" not in df.columns and "datetime_local" in df.columns:
        df["year"] = pd.to_datetime(df["datetime_local"], errors="coerce").dt.year.astype("Int16")
    return df


def _ensure_temp_c(df: pd.DataFrame) -> pd.DataFrame:
    """Add a stable ``temp_c`` alias. If the source `temp` is already in C
    (detected via presence of ``temp_f`` or a mean < 60), we just copy it.
    """
    if "temp_c" in df.columns:
        return df
    if "temp" not in df.columns:
        return df
    sample_mean = df["temp"].dropna().mean()
    if "temp_f" in df.columns or sample_mean < 60:
        df["temp_c"] = df["temp"]
    else:
        df["temp_c"] = df["temp"] - 273.15
    # Also alias feels_like / dew_point to _c if they look Celsius
    for col in ("feels_like", "dew_point"):
        c_name = f"{col}_c"
        if col in df.columns and c_name not in df.columns:
            mean = df[col].dropna().mean()
            df[c_name] = df[col] if mean < 60 else df[col] - 273.15
    return df


def main(cfg: PipelineConfig | None = None) -> bool:
    cfg = cfg or load_config()
    log = get_logger("02_build_weather_store", log_dir=cfg.path("logs"))

    wx_path = cfg.path("weather_master")
    out_dir = ensure_dir(cfg.path("parquet_weather"))

    if not wx_path.exists():
        log.error(f"Weather master not found: {wx_path}")
        return False

    log.info(f"Reading {wx_path.name} → {out_dir}")

    with step_timer(log, "read weather master CSV"):
        df = pd.read_csv(wx_path, low_memory=False)
    log.info(f"  rows in: {len(df):,}  cols: {df.shape[1]}")

    station_col = _pick_station_col(df)
    if station_col != "location":
        df = df.rename(columns={station_col: "location"})
        log.info(f"  renamed {station_col!r} → 'location'")

    with step_timer(log, "enrich (ensure temp_c, time cols)"):
        df = _ensure_time_cols(df)
        df = _ensure_temp_c(df)

    # Filesystem-safe partition values
    df["location"] = (
        df["location"].astype(str)
        .str.replace(r"[\\/:\*\?\"<>\|]", "_", regex=True)
        .str.strip()
    )

    # Drop rows with unusable year for partitioning
    n_before = len(df)
    df = df.dropna(subset=["year"]).copy()
    if len(df) < n_before:
        log.warning(f"  dropped {n_before - len(df):,} rows with missing year")

    with step_timer(log, "write partitioned parquet"):
        write_parquet_partitioned(
            df,
            out_dir,
            partition_cols=["location", "year"],
        )

    log.info(
        f"Stations: {df['location'].nunique()}, "
        f"years: {sorted(df['year'].dropna().unique().tolist())}, "
        f"rows out: {len(df):,}"
    )
    return True


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
