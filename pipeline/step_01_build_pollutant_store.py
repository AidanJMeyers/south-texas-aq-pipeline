"""Step 01 — Build the partitioned pollutant parquet store.

Reads the 7 By_Pollutant CSVs and writes a Hive-partitioned parquet dataset
partitioned by ``pollutant_group`` and ``year``. Derives ``datetime``, ``year``,
``month``, ``hour``, and ``season`` columns. Normalizes ``county_name`` to
title case (fixes the ALL-CAPS COMAL/GUADALUPE/NUECES quirk).

Inputs:
    01_Data/Processed/By_Pollutant/*.csv           (~565 MB, 7 files)

Outputs:
    data/parquet/pollutants/pollutant_group=X/year=YYYY/*.parquet

Expected: ~5.84M rows total. Runtime: ~3–5 minutes on SSD.
"""

from __future__ import annotations

import sys

import numpy as np
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


# ---------------------------------------------------------------------------
# Unit normalization between EPA and TCEQ
# ---------------------------------------------------------------------------
# The merged By_Pollutant CSVs were built from two sources with DIFFERENT
# native units. Verified directly from the raw files under !Final Raw Data/:
#
#   EPA AQS Downloads/by_pollutant/*.csv carry `units_of_measure` per row
#   TCEQ RD files carry AQS `Unit Cd` per row (008=ppb, 001/007=ppm, 105=µg/m³)
#
# Per-pollutant verification:
#   Parameter               EPA        TCEQ       Action
#   ---------               ---        ----       ------
#   44201  Ozone            ppm        ppb        multiply TCEQ ×0.001
#   42101  CO               ppm        (absent)   —
#   42401  SO2              ppb        ppb        none
#   42601  NO               ppb        ppb        none
#   42602  NO2              ppb        ppb        none
#   42603  NOx              ppb        ppb        none
#   88101  PM2.5 FRM        µg/m³      —          —
#   88502  PM2.5            —          µg/m³      none
#   81102  PM10             µg/m³      (absent)   —
#
# Only ozone needs conversion. The canonical unit we standardize to is the
# EPA unit for each pollutant (ozone→ppm) because the NAAQS thresholds in
# config.yaml are expressed in those units.
#
# The conversion factor is a multiplier applied to sample_measurement for
# rows matching (parameter_code, data_source).

UNIT_CONVERSIONS: dict[tuple[int, str], tuple[float, str]] = {
    # (parameter_code, data_source) -> (multiplier, description)
    (44201, "TCEQ"): (0.001, "ozone ppb → ppm"),
}


# ---------------------------------------------------------------------------
# Out-of-scope row filters
# ---------------------------------------------------------------------------
# Rules for dropping rows that are in the merged By_Pollutant CSVs but
# should NOT be in the analytical pipeline. Each rule is an AND over
# column=value matches. Applied in step 01 right after dedup.
#
# Historical rationale:
#
#   Calaveras Lake TCEQ feed — The EPA monitor at Calaveras Lake (AQSID
#   480290059) has a parallel TCEQ data feed in the merged CSVs
#   (~478,846 rows post-dedup across NOx_Family, Ozone, PM2.5, SO2). This
#   parallel feed partially mirrors the EPA feed and carries some value
#   conflicts. The project decision (v0.3.3) is to use **only** the EPA
#   feed for this site and drop the TCEQ parallel entirely. Calaveras
#   Lake Park (the separate TCEQ physical site at 480291609) measures
#   only TSP and is out-of-scope — see site_lookup.py:EXCLUDED_SITES.

OUT_OF_SCOPE_FILTERS: list[tuple[str, dict]] = [
    (
        "Calaveras Lake (480290059) TCEQ feed — use EPA only",
        {"aqsid": "480290059", "data_source": "TCEQ"},
    ),
]


def _drop_out_of_scope(df: pd.DataFrame, log) -> pd.DataFrame:
    """Apply OUT_OF_SCOPE_FILTERS. Each filter is an AND of column matches."""
    for desc, match in OUT_OF_SCOPE_FILTERS:
        mask = pd.Series(True, index=df.index)
        for col, val in match.items():
            if col not in df.columns:
                mask = pd.Series(False, index=df.index)
                break
            mask &= (df[col].astype(str) == str(val))
        n = int(mask.sum())
        if n:
            df = df.loc[~mask].copy()
            log.info(f"  filter: {desc}  ({n:,} rows dropped)")
    return df


def _normalize_units(df: pd.DataFrame, log) -> pd.DataFrame:
    """Apply per-(parameter, source) unit conversions and log row counts.

    This runs before any downstream aggregation so NAAQS computation, daily
    means, etc. all see a single consistent unit per pollutant.
    """
    if "parameter_code" not in df.columns or "data_source" not in df.columns:
        return df

    for (param, src), (factor, desc) in UNIT_CONVERSIONS.items():
        mask = (df["parameter_code"] == param) & (df["data_source"] == src)
        n = int(mask.sum())
        if n:
            df.loc[mask, "sample_measurement"] = df.loc[mask, "sample_measurement"] * factor
            log.info(f"  unit normalize: {desc}  ({n:,} rows × {factor})")
    return df


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
        log.error(f"No CSVs in {in_dir}")
        return False

    log.info(f"Found {len(csvs)} pollutant CSVs → {out_dir}")

    total_in = 0
    total_out = 0
    for csv in csvs:
        with step_timer(log, f"process {csv.name}"):
            df = read_pollutant_csv(csv)
            n_in = len(df)
            # Drop exact full-row duplicates introduced by the upstream
            # TCEQ/EPA merge. These are safe — identical rows carry zero
            # information. Non-exact duplicates (same key, different
            # measurement) are left for downstream averaging in NAAQS / daily
            # aggregation steps.
            n_dedup = len(df)
            df = df.drop_duplicates().reset_index(drop=True)
            n_after_dedup = len(df)
            if n_dedup != n_after_dedup:
                log.info(f"  dropped {n_dedup - n_after_dedup:,} exact-duplicate rows")
            df = _drop_out_of_scope(df, log)
            df = _normalize_units(df, log)
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
