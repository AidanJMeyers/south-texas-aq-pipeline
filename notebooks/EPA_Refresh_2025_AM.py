#!/usr/bin/env python3
"""
EPA AQS TARGETED 2025 REFRESH (v2.1) — for the South Texas AQ pipeline
========================================================================

A focused refresh of the EPA-side 2025 data only, based on the gap
analysis run against Neon on 2026-04-22. Replaces the original
exhaustive download script — pulls ONLY what's actually missing,
skips dead sensors, and outputs a single delta CSV in canonical
15-column pipeline schema.

WHAT THIS SCRIPT DOES (vs. the original v2.0):
  * 30 targeted (county, parameter) API calls instead of 47×11×11=5,687
  * No by-pollutant or by-site file fan-out — just one delta CSV
  * Skips 6 known-dead sensors (verified via Neon — see DEAD_SENSORS)
  * Writes directly into the canonical 15-column schema the pipeline
    consumes (no separate reorg/merge step needed)
  * Optional --neon-upsert flag pushes the delta straight to
    aq.pollutant_hourly using ON CONFLICT DO NOTHING

USAGE:
  # Local / Colab — just produce the delta CSV
  python EPA_Refresh_2025_AM.py

  # Also append to the merged By_Pollutant CSVs (pipeline ingestion path)
  python EPA_Refresh_2025_AM.py --append-csv

  # Also push directly into Neon's aq.pollutant_hourly (fastest path)
  python EPA_Refresh_2025_AM.py --neon-upsert

  # Both
  python EPA_Refresh_2025_AM.py --append-csv --neon-upsert

OUTPUT:
  aqs_refresh_output/EPA_delta_<YYYYMMDD_HHMM>.csv
  aqs_refresh_output/refresh_summary_<YYYYMMDD_HHMM>.json
  aqs_refresh_output/refresh_log.txt

Melaram Lab | Texas A&M University–Corpus Christi
Pipeline version compatibility: 0.3.5+
Authored: 2026-04-22
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests


# =============================================================================
# CREDENTIALS
# =============================================================================
# Replace with your AQS API credentials, or set the env vars
# AQS_EMAIL and AQS_KEY before running. Leave hardcoded values for Colab
# convenience but DO NOT commit them to git.
EMAIL = os.environ.get("AQS_EMAIL", "ameyers@rollins.edu")
KEY   = os.environ.get("AQS_KEY",   "sandhare72")

# Neon connection — required only with --neon-upsert
NEON_URL = os.environ.get("AQ_POSTGRES_URL")

# =============================================================================
# CONFIGURATION
# =============================================================================
API_BASE   = "https://aqs.epa.gov/data/api"
STATE      = "48"               # Texas
EDATE      = "20251231"          # End of 2025
OUTPUT_DIR = Path("aqs_refresh_output")
RUN_TS     = datetime.now().strftime("%Y%m%d_%H%M")

# AQS parameter code -> (pollutant_name, pollutant_group)
PARAM_LOOKUP: dict[str, tuple[str, str]] = {
    "42101": ("CO",    "CO"),
    "42401": ("SO2",   "SO2"),
    "42601": ("NO",    "NOx_Family"),
    "42602": ("NO2",   "NOx_Family"),
    "42603": ("NOx",   "NOx_Family"),
    "44201": ("Ozone", "Ozone"),
    "81102": ("PM10",  "PM10"),
    "85101": ("PM10",  "PM10"),
    "88101": ("PM2.5", "PM2.5"),
    "88500": ("PM2.5", "PM2.5"),
    "88502": ("PM2.5", "PM2.5"),
}

# County FIPS -> human name (title case, matches pipeline's normalized form)
COUNTY_NAMES: dict[str, str] = {
    "013": "Atascosa",
    "029": "Bexar",
    "061": "Cameron",
    "215": "Hidalgo",
    "255": "Karnes",
    "273": "Kleberg",
    "323": "Maverick",
    "355": "Nueces",
    "469": "Victoria",
    "479": "Webb",
    "493": "Wilson",
}

# =============================================================================
# THE GAP TARGETS — derived from Neon MCP query on 2026-04-22
# =============================================================================
# (county_code, param_code) -> bdate (YYYYMMDD) for earliest needed data.
# One API call per row. ~30 calls total.
#
# Where multiple sites in the same (county, param) have different cutoffs,
# we use the EARLIEST one (over-pulls slightly for newer sites — dedup
# handles it).
GAP_TARGETS: list[tuple[str, str, str, str]] = [
    # (county_code, param_code, bdate, comment)

    # Atascosa - Pleasanton PM2.5 (last 2025-09-30)
    ("013", "88101", "20251001", "Pleasanton PM2.5"),
    ("013", "88502", "20251001", "Pleasanton PM2.5 non-FRM"),

    # Bexar - mixed cutoffs; earliest=09-30 for PM2.5/PM10, 10-31 for gases
    ("029", "42101", "20251101", "Bexar CO (Converse)"),
    ("029", "42401", "20251101", "Bexar SO2 (Calaveras)"),
    ("029", "42601", "20251101", "Bexar NO (NOx_Family)"),
    ("029", "42602", "20251101", "Bexar NO2"),
    ("029", "42603", "20251101", "Bexar NOx"),
    ("029", "44201", "20251101", "Bexar Ozone"),
    ("029", "81102", "20251001", "Bexar PM10 (Palo Alto, Windcrest)"),
    ("029", "88101", "20251001", "Bexar PM2.5 (multiple sites)"),
    ("029", "88502", "20251001", "Bexar PM2.5 non-FRM"),

    # Cameron - mostly through 11-30 + Port Isabel through 11-26
    ("061", "44201", "20251127", "Cameron Ozone (Harlingen)"),
    ("061", "88101", "20251127", "Cameron PM2.5 (Brownsville Roca, Port Isabel)"),
    ("061", "88502", "20251127", "Cameron PM2.5 non-FRM"),

    # Hidalgo - through 11-30
    ("215", "44201", "20251201", "Hidalgo Ozone (Mission)"),
    ("215", "81102", "20251201", "Hidalgo PM10 (Mission)"),
    ("215", "88101", "20251201", "Hidalgo PM2.5 (Mission, Edinburg)"),
    ("215", "88502", "20251201", "Hidalgo PM2.5 non-FRM"),

    # Karnes - Karnes City NOx_Family through 10-31
    ("255", "42601", "20251101", "Karnes City NO"),
    ("255", "42602", "20251101", "Karnes City NO2"),
    ("255", "42603", "20251101", "Karnes City NOx"),

    # Kleberg - Kingsville PM2.5 last 2025-05-07 (likely failed; try anyway)
    ("273", "88101", "20250508", "Kingsville PM2.5 (possible mid-2025 failure)"),
    ("273", "88502", "20250508", "Kingsville PM2.5 non-FRM"),

    # Maverick - Eagle Pass PM2.5
    ("323", "88101", "20251201", "Eagle Pass PM2.5"),
    ("323", "88502", "20251201", "Eagle Pass PM2.5 non-FRM"),

    # Nueces - through 11-30 across all
    ("355", "42401", "20251201", "Nueces SO2"),
    ("355", "44201", "20251201", "Nueces Ozone"),
    ("355", "81102", "20251201", "Nueces PM10 (CC Holly)"),
    ("355", "88101", "20251201", "Nueces PM2.5"),
    ("355", "88502", "20251201", "Nueces PM2.5 non-FRM"),

    # Victoria
    ("469", "44201", "20251201", "Victoria Ozone"),

    # Webb - Vidaurri CO/Ozone trailing edge + PM10 through 09-28
    ("479", "42101", "20251124", "Webb CO (Laredo Vidaurri)"),
    ("479", "44201", "20251127", "Webb Ozone (Laredo Vidaurri)"),
    ("479", "81102", "20251001", "Webb PM10 (Vidaurri, Santa Maria)"),
    ("479", "88101", "20251201", "Webb PM2.5 (Laredo Hachar)"),
    ("479", "88502", "20251201", "Webb PM2.5 non-FRM"),

    # Wilson - Floresville NOx_Family through 10-31
    ("493", "42601", "20251101", "Floresville NO"),
    ("493", "42602", "20251101", "Floresville NO2"),
    ("493", "42603", "20251101", "Floresville NOx"),
]

# =============================================================================
# DEAD SENSORS — DO NOT QUERY (skipped automatically; documented for clarity)
# =============================================================================
DEAD_SENSORS: list[tuple[str, str, str]] = [
    # (aqsid, pollutant, last_seen_date)
    ("480290053", "PM10",  "2019-11-29"),  # Live Oak
    ("480291080", "SO2",   "2023-03-13"),  # Heritage MS SO2_1080
    ("480610006", "Ozone", "2017-12-31"),  # Brownsville
    ("480610006", "PM2.5", "2023-04-04"),  # Brownsville
    ("482151046", "PM10",  "2020-10-30"),  # Edinburg
    ("484790017", "CO",    "2017-06-25"),  # Laredo Santa Maria
]


# =============================================================================
# UTILITIES
# =============================================================================
def make_aqsid(state_code: int | str, county_code: int | str, site_number: int | str) -> str:
    return (str(state_code).zfill(2) +
            str(county_code).zfill(3) +
            str(site_number).zfill(4))


def make_site_name(county_name: str, site_number: int | str) -> str:
    return f"{re.sub(r'[^A-Za-z0-9]', '', str(county_name))}_{str(site_number).zfill(4)}"


def aqs_get(endpoint: str, params: dict, max_retries: int = 3) -> list | None:
    """One AQS API call with retry / backoff. Returns list of records or None."""
    url = f"{API_BASE}/{endpoint}"
    params = {**params, "email": EMAIL, "key": KEY}
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, params=params, timeout=120)
            data = resp.json()
            header = data.get("Header", [{}])
            if isinstance(header, list):
                header = header[0] if header else {}
            status = str(header.get("status", "")).lower()
            if "success" in status:
                return data.get("Data", [])
            if "no data" in status or "no matching" in str(header).lower():
                return None
            if attempt < max_retries - 1:
                time.sleep(5 * (attempt + 1))
        except requests.exceptions.Timeout:
            if attempt < max_retries - 1:
                time.sleep(10)
        except Exception as e:
            print(f"    request error: {e}")
            if attempt < max_retries - 1:
                time.sleep(5)
    return None


def to_canonical_schema(raw_rows: list, param_code: str, county_code: str) -> pd.DataFrame:
    """Convert AQS API response rows -> the pipeline's 15-column schema."""
    if not raw_rows:
        return pd.DataFrame()

    df = pd.DataFrame(raw_rows)
    pollutant_name, pollutant_group = PARAM_LOOKUP[param_code]
    county_name = COUNTY_NAMES.get(county_code, "")

    out = pd.DataFrame({
        "state_code":         df.get("state_code"),
        "county_code":        df.get("county_code"),
        "site_number":        df.get("site_number"),
        "parameter_code":     df.get("parameter_code", param_code).astype(int),
        "poc":                df.get("poc"),
        "date_local":         df.get("date_local"),
        "time_local":         df.get("time_local"),
        "sample_measurement": df.get("sample_measurement"),
        "method_code":        df.get("method_code"),
    })
    # Cast int columns explicitly (some come back as strings)
    for c in ("state_code", "county_code", "site_number", "poc", "method_code"):
        out[c] = pd.to_numeric(out[c], errors="coerce").astype("Int32")
    out["county_name"]     = county_name
    out["pollutant_name"]  = pollutant_name
    out["aqsid"]           = (out["state_code"].astype(str).str.zfill(2)
                              + out["county_code"].astype(str).str.zfill(3)
                              + out["site_number"].astype(str).str.zfill(4))
    out["data_source"]     = "EPA"
    out["pollutant_group"] = pollutant_group
    out["site_name"]       = (county_name + "_" + out["site_number"].astype(str).str.zfill(4))

    # Drop rows with no measurement (AQS sometimes returns null-flagged rows)
    out = out.dropna(subset=["sample_measurement"]).reset_index(drop=True)

    # Drop dead-sensor rows defensively (shouldn't appear but belt + suspenders)
    dead_keys = {(a, p) for a, p, _ in DEAD_SENSORS}
    out = out[~out.apply(
        lambda r: (r["aqsid"], r["pollutant_group"]) in dead_keys
                  or (r["aqsid"], r["pollutant_name"]) in dead_keys,
        axis=1,
    )].reset_index(drop=True)
    return out


# =============================================================================
# PHASE 1 - Pull
# =============================================================================
def pull_gap_targets() -> tuple[pd.DataFrame, dict]:
    print("\n" + "=" * 70)
    print(f"EPA TARGETED REFRESH — {len(GAP_TARGETS)} gap pulls planned")
    print("=" * 70)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    log_path = OUTPUT_DIR / "refresh_log.txt"
    log_lines: list[str] = [f"Refresh run: {RUN_TS}",
                             f"EDATE: {EDATE}",
                             f"Gap targets: {len(GAP_TARGETS)}",
                             ""]

    deltas: list[pd.DataFrame] = []
    summary = {"runs": [], "total_rows": 0, "started": RUN_TS}

    for i, (county_code, param_code, bdate, comment) in enumerate(GAP_TARGETS, 1):
        county_name = COUNTY_NAMES.get(county_code, county_code)
        poll_name, poll_group = PARAM_LOOKUP[param_code]
        tag = f"{county_name:>10s} · {poll_name:<6s} · param {param_code} · {bdate} → {EDATE}"
        print(f"[{i:>2}/{len(GAP_TARGETS)}] {tag}  — {comment}")

        raw = aqs_get("sampleData/byCounty", {
            "param":   param_code,
            "bdate":   bdate,
            "edate":   EDATE,
            "state":   STATE,
            "county":  county_code,
        })
        rows_returned = len(raw) if raw else 0

        if rows_returned:
            df = to_canonical_schema(raw, param_code, county_code)
            print(f"          → {len(df):,} canonical rows ({df['aqsid'].nunique()} sites)")
            deltas.append(df)
        else:
            df = pd.DataFrame()
            print(f"          → no data returned")

        summary["runs"].append({
            "county_code": county_code,
            "county_name": county_name,
            "param_code":  param_code,
            "pollutant":   poll_name,
            "bdate":       bdate,
            "edate":       EDATE,
            "rows_raw":    rows_returned,
            "rows_kept":   len(df),
            "comment":     comment,
        })
        log_lines.append(f"{tag}  raw={rows_returned}  kept={len(df)}  ({comment})")
        time.sleep(0.5)  # rate-limit (AQS allows ~5 req/sec)

    delta = pd.concat(deltas, ignore_index=True) if deltas else pd.DataFrame()
    summary["total_rows"] = len(delta)
    summary["finished"] = datetime.now().strftime("%Y%m%d_%H%M")

    log_lines.append("")
    log_lines.append(f"TOTAL canonical rows pulled: {len(delta):,}")
    if not delta.empty:
        log_lines.append(f"Unique sites in delta:        {delta['aqsid'].nunique()}")
        log_lines.append(f"Pollutants in delta:          {sorted(delta['pollutant_group'].unique())}")
        log_lines.append(f"Date range in delta:          {delta['date_local'].min()} .. {delta['date_local'].max()}")

    log_path.write_text("\n".join(log_lines), encoding="utf-8")
    return delta, summary


# =============================================================================
# PHASE 2 - Optional appends
# =============================================================================
def append_to_bypollutant_csvs(delta: pd.DataFrame, root: Path) -> None:
    """Append new rows to 01_Data/Processed/By_Pollutant/{group}_AllCounties_*.csv.
    Dedups before write (in case any rows already exist)."""
    if delta.empty:
        print("  (no rows to append)")
        return

    bypoll = root / "01_Data" / "Processed" / "By_Pollutant"
    if not bypoll.exists():
        print(f"  ✗ {bypoll} not found — skip --append-csv")
        return

    # Filename mapping by pollutant_group
    fname_map = {
        "CO":         "CO_AllCounties_2015_2025.csv",
        "NOx_Family": "NOx_Family_AllCounties_2015_2025.csv",
        "Ozone":      "Ozone_AllCounties_2015_2025.csv",
        "PM10":       "PM10_AllCounties_2015_2025.csv",
        "PM2.5":      "PM2.5_AllCounties_2015_2025.csv",
        "SO2":        "SO2_AllCounties_2015_2025.csv",
    }

    for group, group_df in delta.groupby("pollutant_group"):
        fname = fname_map.get(group)
        if not fname:
            print(f"  ✗ unknown pollutant_group {group} — skipping")
            continue
        target = bypoll / fname
        existing = pd.read_csv(target, dtype={"aqsid": str, "site_name": str},
                                low_memory=False) if target.exists() else pd.DataFrame()

        merged = pd.concat([existing, group_df], ignore_index=True)
        before = len(merged)
        merged = merged.drop_duplicates(
            subset=["aqsid", "date_local", "time_local",
                    "parameter_code", "poc", "data_source"],
            keep="first",
        ).reset_index(drop=True)
        added = len(merged) - len(existing)
        print(f"  {group:<11s} {fname}  +{added:,} new rows "
              f"(was {len(existing):,} → now {len(merged):,})")
        merged.to_csv(target, index=False)


def upsert_to_neon(delta: pd.DataFrame) -> None:
    """Push delta directly into aq.pollutant_hourly via temp-table + INSERT...ON CONFLICT.
    Uses chunked upserts to stay under the Postgres 65k-parameter limit."""
    if delta.empty:
        print("  (no rows to upsert)")
        return
    if not NEON_URL:
        print("  ✗ AQ_POSTGRES_URL not set — skip --neon-upsert")
        return

    try:
        from sqlalchemy import create_engine, text
    except ImportError:
        print("  ✗ sqlalchemy not installed — pip install 'sqlalchemy>=2.0' 'psycopg[binary]>=3.1'")
        return

    engine = create_engine(NEON_URL, pool_pre_ping=True, future=True)

    # Add the derived columns the parquet has but the canonical schema doesn't
    df = delta.copy()
    df["datetime"] = pd.to_datetime(df["date_local"].astype(str) + " " + df["time_local"].astype(str),
                                     errors="coerce")
    df["year"]   = df["datetime"].dt.year.astype("Int16")
    df["month"]  = df["datetime"].dt.month.astype("Int8")
    df["hour"]   = df["datetime"].dt.hour.astype("Int8")
    season_map = {12:"DJF",1:"DJF",2:"DJF",3:"MAM",4:"MAM",5:"MAM",
                   6:"JJA",7:"JJA",8:"JJA",9:"SON",10:"SON",11:"SON"}
    df["season"] = df["month"].map(season_map).astype("string")
    df = df.dropna(subset=["datetime", "year"]).reset_index(drop=True)

    print(f"  upserting {len(df):,} rows into aq.pollutant_hourly ...")
    # Stage in a temp table, then INSERT ... ON CONFLICT DO NOTHING using
    # (aqsid, datetime, parameter_code, poc) as the dedup key.
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS pg_temp.delta_in"))
        conn.execute(text("CREATE TEMP TABLE delta_in (LIKE aq.pollutant_hourly INCLUDING DEFAULTS)"))
    df.to_sql("delta_in", engine, if_exists="append", index=False, method="multi",
              chunksize=4000, schema=None)
    with engine.begin() as conn:
        # Add a uniqueness constraint to the destination if not already present
        conn.execute(text(
            "DO $$ BEGIN "
            "  IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname='ux_pollutant_hourly_dedup') THEN "
            "    CREATE UNIQUE INDEX ux_pollutant_hourly_dedup "
            "      ON aq.pollutant_hourly (aqsid, datetime, parameter_code, poc); "
            "  END IF; "
            "END $$;"
        ))
        result = conn.execute(text(
            "INSERT INTO aq.pollutant_hourly "
            "SELECT * FROM delta_in "
            "ON CONFLICT (aqsid, datetime, parameter_code, poc) DO NOTHING"
        ))
        inserted = result.rowcount if result.rowcount is not None else -1
    print(f"  inserted {inserted} new rows (duplicates ignored).")


# =============================================================================
# MAIN
# =============================================================================
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--append-csv", action="store_true",
                         help="Append delta to 01_Data/Processed/By_Pollutant/*.csv")
    parser.add_argument("--neon-upsert", action="store_true",
                         help="Push delta directly into Neon's aq.pollutant_hourly")
    parser.add_argument("--root", type=Path, default=Path("."),
                         help="Project root (default: cwd) — only used with --append-csv")
    args = parser.parse_args()

    print("\n" + "=" * 70)
    print("EPA AQS TARGETED 2025 REFRESH (v2.1)")
    print("=" * 70)
    print(f"  Email:        {EMAIL}")
    print(f"  Output dir:   {OUTPUT_DIR.resolve()}")
    print(f"  Pull targets: {len(GAP_TARGETS)}")
    print(f"  Skipping:     {len(DEAD_SENSORS)} dead sensors (decommissioned)")
    print(f"  Started:      {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    delta, summary = pull_gap_targets()

    out_csv = OUTPUT_DIR / f"EPA_delta_{RUN_TS}.csv"
    out_summary = OUTPUT_DIR / f"refresh_summary_{RUN_TS}.json"
    delta.to_csv(out_csv, index=False)
    out_summary.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\n  Delta CSV:    {out_csv}  ({len(delta):,} rows)")
    print(f"  Summary JSON: {out_summary}")

    if args.append_csv:
        print("\n--- Appending delta to By_Pollutant CSVs ---")
        append_to_bypollutant_csvs(delta, args.root)
        print("\nNext step: re-run the pipeline to propagate to Neon:")
        print(f"  python pipeline/run_pipeline.py --only '00,01,03,04,05,07'")

    if args.neon_upsert:
        print("\n--- Upserting delta directly into Neon ---")
        upsert_to_neon(delta)
        print("\nDirect upsert complete. The hourly table is current.")
        print("Daily aggregates / NAAQS will refresh next time you run the pipeline.")

    print("\n" + "=" * 70)
    print("DONE")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
