#!/usr/bin/env python3
"""
TCEQ_Append_2025_AM.py
Convert and append the 2025 TCEQ refresh files (manually pulled from
TAMIS) into the merged By_Pollutant/*.csv files in canonical 15-col
schema, with ozone unit normalization (ppb -> ppm) applied.

Designed for the Apr 28 2026 TCEQ refresh:
  TCEQ_Ozone_111325-010126_8sites.txt
  TCEQ_NOx_112225-010126_4sites.txt

Improvements over the v0.3.6 EPA refresh script:
  * Uses CANONICAL site_name from a hardcoded lookup (matches what
    aq.site_registry has) so we don't introduce duplicate site_name
    values like the EPA refresh did.
  * Ozone (44201) values are multiplied by 0.001 (TCEQ ppb -> EPA ppm),
    matching the pipeline's UNIT_CONVERSIONS rule in step 01.
  * Dedup on (aqsid, date_local, time_local, parameter_code, poc,
    data_source) before append, so re-running the script is idempotent.

Usage:
    cd "C:\\Users\\aidan\\OneDrive\\Desktop\\AirQuality South TX"
    python notebooks/TCEQ_Append_2025_AM.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "!Final Raw Data" / "TCEQ Data - Missing Sites"
CSV_DIR = ROOT / "01_Data" / "Processed" / "By_Pollutant"

# -----------------------------------------------------------------------------
# Files to ingest (path, pollutant_group, csv_target, default_pollutant_name)
# -----------------------------------------------------------------------------
INGEST_FILES = [
    (
        RAW_DIR / "TCEQ_Ozone_111325-010126_8sites.txt",
        "Ozone",
        CSV_DIR / "Ozone_AllCounties_2015_2025.csv",
    ),
    (
        RAW_DIR / "TCEQ_NOx_112225-010126_4sites.txt",
        "NOx_Family",
        CSV_DIR / "NOx_Family_AllCounties_2015_2025.csv",
    ),
]

# AQS RD Transaction v1.6 columns (27 fields, pipe-delimited)
RD_COLS = [
    "ttype", "action", "state", "county", "site", "param", "poc", "dur",
    "unit", "meth", "date", "time", "value", "null_cd", "freq", "proto",
    "q1", "q2", "q3", "q4", "q5", "q6", "q7", "q8", "q9", "q10",
    "mdl", "unc",
]

# AQS parameter code -> (pollutant_name, pollutant_group)
PARAM_LOOKUP = {
    42101: ("CO",    "CO"),
    42401: ("SO2",   "SO2"),
    42601: ("NO",    "NOx_Family"),
    42602: ("NO2",   "NOx_Family"),
    42603: ("NOx",   "NOx_Family"),
    44201: ("Ozone", "Ozone"),
    81102: ("PM10",  "PM10"),
    85101: ("PM10",  "PM10"),
    88101: ("PM2.5", "PM2.5"),
    88500: ("PM2.5", "PM2.5"),
    88502: ("PM2.5", "PM2.5"),
}

# Canonical site_name from aq.site_registry — DO NOT change format.
# Adding a new TCEQ site? Look it up via the Neon MCP query:
#     SELECT aqsid, site_name FROM aq.site_registry WHERE aqsid = '...';
SITE_NAMES = {
    # Bexar (county 029) TCEQ sites in this refresh
    "480290055": "CPS Pecan Valley_0055",
    "480290501": "Elm Creek Elementary_0501",
    "480290502": "Fair Oaks Ranch_0502",
    "480291610": "Government Canyon_1610",
    # Comal (county 091)
    "480910503": "Bulverde Elementary_0503",
    "480910505": "City of Garden Ridge_0505",
    # Guadalupe (county 187)
    "481870504": "New Braunfels Airport_0504",
    "481870506": "Seguin Outdoor Learning Center_0506",
}

COUNTY_NAMES = {
    "029": "Bexar",
    "091": "Comal",
    "187": "Guadalupe",
}

# Canonical 15-column schema (matches step_01_build_pollutant_store output)
CANONICAL_COLS = [
    "state_code", "county_code", "site_number", "parameter_code", "poc",
    "date_local", "time_local", "sample_measurement", "method_code",
    "county_name", "pollutant_name", "aqsid", "data_source",
    "pollutant_group", "site_name",
]

# Ozone TCEQ rows are reported in ppb; pipeline standardizes to EPA ppm.
OZONE_PPB_TO_PPM = 0.001


def parse_rd_file(path: Path) -> pd.DataFrame:
    """Read an AQS Raw Data transaction file (pipe-delimited)."""
    df = pd.read_csv(
        path, sep="|", skiprows=11, names=RD_COLS,
        engine="python", on_bad_lines="skip",
    )
    df = df[df["ttype"] == "RD"].copy()
    return df


def to_canonical(raw: pd.DataFrame, pollutant_group: str) -> pd.DataFrame:
    """Map raw RD rows -> canonical 15-column schema."""
    out = pd.DataFrame({
        "state_code":         raw["state"].astype(int),
        "county_code":        raw["county"].astype(int),
        "site_number":        raw["site"].astype(int),
        "parameter_code":     raw["param"].astype(int),
        "poc":                raw["poc"].astype(int),
        "date_local":         pd.to_datetime(raw["date"], format="%Y%m%d").dt.strftime("%Y-%m-%d"),
        "time_local":         raw["time"].astype(str).str.zfill(5),
        "sample_measurement": raw["value"].astype(float),
        "method_code":        raw["meth"].astype(int),
    })
    out["aqsid"] = (
        out["state_code"].astype(str).str.zfill(2)
        + out["county_code"].astype(str).str.zfill(3)
        + out["site_number"].astype(str).str.zfill(4)
    )
    out["county_name"]    = out["county_code"].astype(str).str.zfill(3).map(COUNTY_NAMES).fillna("")
    out["pollutant_name"] = out["parameter_code"].map(lambda c: PARAM_LOOKUP.get(c, (str(c), ""))[0])
    out["data_source"]    = "TCEQ"
    out["pollutant_group"] = pollutant_group
    out["site_name"]      = out["aqsid"].map(SITE_NAMES).fillna("UNKNOWN_" + out["aqsid"])

    # Drop rows for unknown sites (defensive — should never happen for these files)
    unknown = out[out["site_name"].str.startswith("UNKNOWN_")]
    if len(unknown):
        print(f"  WARNING: {len(unknown)} rows have unknown aqsid: "
              f"{sorted(unknown['aqsid'].unique())}")

    # Ozone TCEQ ppb -> EPA ppm (matches step 01 UNIT_CONVERSIONS)
    if pollutant_group == "Ozone":
        ozone_mask = out["parameter_code"] == 44201
        n_normalized = ozone_mask.sum()
        out.loc[ozone_mask, "sample_measurement"] *= OZONE_PPB_TO_PPM
        print(f"  unit normalize: ozone ppb -> ppm  ({n_normalized:,} rows × {OZONE_PPB_TO_PPM})")

    return out[CANONICAL_COLS]


def append_to_csv(target: Path, new: pd.DataFrame) -> None:
    """Append new rows to target CSV with dedup on the 6-col uniqueness key."""
    if not target.exists():
        print(f"  X target CSV not found: {target}")
        return
    existing = pd.read_csv(target, dtype={"aqsid": str, "site_name": str},
                            low_memory=False)
    before_rows  = len(existing)
    before_sites = existing["aqsid"].nunique()

    merged = pd.concat([existing, new], ignore_index=True)
    dedup_key = ["aqsid", "date_local", "time_local",
                 "parameter_code", "poc", "data_source"]
    merged = merged.drop_duplicates(subset=dedup_key, keep="first").reset_index(drop=True)

    after_rows  = len(merged)
    after_sites = merged["aqsid"].nunique()
    truly_new   = after_rows - before_rows

    print(f"  was {before_rows:,} rows / {before_sites} sites")
    print(f"  new rows in delta: {len(new):,}")
    print(f"  truly new (not duplicates): {truly_new:,}")
    print(f"  now {after_rows:,} rows / {after_sites} sites")

    merged.to_csv(target, index=False)
    print(f"  OK wrote {target}")


def main() -> None:
    print("=" * 70)
    print("TCEQ APPEND  -  2025 trailing-edge refresh")
    print("=" * 70)

    for raw_path, pollutant_group, target in INGEST_FILES:
        print(f"\n--- {raw_path.name}  ({pollutant_group}) ---")
        if not raw_path.exists():
            print(f"  X file not found, skipping")
            continue

        raw = parse_rd_file(raw_path)
        print(f"  raw RD rows: {len(raw):,}")
        print(f"  unique sites: {raw[['state','county','site']].drop_duplicates().shape[0]}")
        print(f"  date range: {raw['date'].min()} .. {raw['date'].max()}")

        delta = to_canonical(raw, pollutant_group)
        print(f"  canonical rows: {len(delta):,}")
        print(f"  sites in delta: {sorted(delta['aqsid'].unique())}")

        append_to_csv(target, delta)

    print("\n" + "=" * 70)
    print("DONE  OK")
    print("=" * 70)
    print("\nNext steps:")
    print("  Option A (full pipeline rerun, ~20 min):")
    print("    python pipeline/run_pipeline.py --only '00,01,03,04,05'")
    print("    python notebooks/finish_hourly_tables_AM.py  # COPY-based reload to Neon")
    print("\n  Option B (parquet rebuild + Neon reload, fastest):")
    print("    python pipeline/run_pipeline.py --only '01,03,04,05'")
    print("    python notebooks/finish_hourly_tables_AM.py")


if __name__ == "__main__":
    main()
