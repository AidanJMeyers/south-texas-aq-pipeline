"""Step 01 — Build the partitioned pollutant parquet store (criteria hourly).

v0.4.0: this step now runs AFTER step_01b (raw TCEQ → CSV ingestion). All unit
normalization, A/B concatenation, dedup, and out-of-scope filtering happened
upstream in 01b, so this step is reduced to:

    1. Read the 6 criteria-pollutant By_Pollutant CSVs (14-col schema).
    2. Enrich with derived columns (datetime / year / month / hour / season,
       title-case county_name).
    3. Write Hive-partitioned parquet by ``pollutant_group / year``.

Inputs:
    01_Data/Processed/By_Pollutant/*.csv                (~478 MB, 6 files)

Outputs:
    data/parquet/pollutants/pollutant_group=X/year=YYYY/*.parquet

Expected: ~4.7M rows total (criteria hourly only — VOCs go to step_01c).
Runtime: ~1–3 minutes on SSD.

Historical note (v0.3.7 -> v0.4.0):
    The old EPA+TCEQ blended ingest happened HERE: this step used to read
    7 By_Pollutant CSVs (including VOCs), apply per-source ozone unit
    conversion, and drop the Calaveras Lake TCEQ duplicate feed. None of
    that is needed in v0.4.0 because:
      - Data is TCEQ-only, so `data_source` column is gone (decision #3).
      - Ozone ppb -> ppm conversion is applied in 01b at ingestion time.
      - VOCs route to their own table via 01c, not here (decision #10).
      - Calaveras Lake is now a single TCEQ-only feed (no duplicate to drop).
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
    # Drop rows that failed to parse (shouldn't happen but defensive)
    n_before = len(df)
    df = df.dropna(subset=["datetime", "year"])
    if len(df) < n_before:
        df = df.copy()
    return df


def main(cfg: PipelineConfig | None = None) -> bool:
    cfg = cfg or load_config()
    log = get_logger("01_build_pollutant_store", log_dir=cfg.path("logs"))

    in_dir = cfg.path("processed_pollutant")
    out_dir = ensure_dir(cfg.path("parquet_pollutants"))
    csvs = sorted(in_dir.glob("*_AllCounties_*.csv"))
    if not csvs:
        log.error(f"No CSVs in {in_dir} — run step 01b first")
        return False

    # Defensive: skip any leftover VOC CSV if one exists (shouldn't, but
    # v0.3.7 used to write VOCs_AllCounties_*.csv here and the file might
    # linger in a partial-upgrade environment).
    voc_in_pollutant_dir = [c for c in csvs if "VOC" in c.name.upper()]
    if voc_in_pollutant_dir:
        log.warning(
            f"Skipping {len(voc_in_pollutant_dir)} legacy VOC CSVs in {in_dir}: "
            f"{[c.name for c in voc_in_pollutant_dir]}. "
            "VOCs are written to 01_Data/Processed/By_VOC/ in v0.4.0."
        )
        csvs = [c for c in csvs if c not in voc_in_pollutant_dir]

    log.info(f"Found {len(csvs)} criteria pollutant CSVs → {out_dir}")

    total_in = 0
    total_out = 0
    for csv in csvs:
        with step_timer(log, f"process {csv.name}"):
            df = read_pollutant_csv(csv)
            n_in = len(df)
            df = _enrich(df)
            n_out = len(df)
            write_parquet_partitioned(
                df,
                out_dir,
                partition_cols=["pollutant_group", "year"],
            )
            log.info(
                f"  {csv.name}: rows {n_in:,} → {n_out:,}, "
                f"sites={df['aqsid'].nunique()}, "
                f"years={sorted(df['year'].dropna().unique().tolist())}"
            )
            total_in += n_in
            total_out += n_out
            del df

    log.info(f"TOTAL rows in={total_in:,} out={total_out:,}")
    return True


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
