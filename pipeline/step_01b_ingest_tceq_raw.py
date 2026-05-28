"""Step 01b — Ingest raw TCEQ TAMIS RD files into canonical 14-col CSVs.

v0.4.0 entry point. Replaces the v0.3.7 hybrid EPA+TCEQ ingestion path that
used pre-merged By_Pollutant CSVs as input.

Reads the 2026-05-21 TCEQ TAMIS pull (51 files):
  - 41 per-site .txt files (with A/B splits for 2 sites)
  - 10 county-level VOC AutoGC .txt files (1hr or 24hr cadence)
  - All in AQS Raw Data (RD) Transaction v1.6 format, pipe-delimited.

Routes rows into 4 output tables based on three signals:

  1. **VOC parameter code (43xxx / 45xxx)** → vocs_1hr OR vocs_24hr
     (cadence determined by source filename — *1hrAutoGC vs *24hrAutoGC)
     VOC rows are EXCLUDED from pollutant_hourly (decision #10).

  2. **Sample Duration Code 7 or X** (24hr block / 24hr average)
     → pollutant_daily_24hr. Catches site 480290060 PM10 (decision #5/#6)
     plus any future 24hr-only criteria-pollutant feeds.

  3. **Everything else** (criteria pollutants, hourly cadence)
     → By_Pollutant/<group>.csv via the canonical 14-column schema.

Per-row transformations:
  - Ozone (44201): ppb → ppm (× 0.001)
  - aqsid built from zero-padded state+county+site
  - county_name from COUNTY_NAMES lookup
  - site_name from SITE_NAMES_CANONICAL lookup (matches aq.site_registry)
  - pollutant_group from PARAM_GROUP lookup
  - data_source column DROPPED (v0.4.0 schema is TCEQ-only, decision #3)

Defensive drops (rows that pass through to nowhere):
  - 4 TSP-only sites: 480290623, 480290625, 480290626, 480291609 (decision #8)
  - Von Ormy 480291097 (decision #18 — not in pull anyway, but defensive)

Outputs (under <root>/01_Data/Processed/):
  By_Pollutant/CO_AllCounties_2015_2025.csv
  By_Pollutant/SO2_AllCounties_2015_2025.csv
  By_Pollutant/NOx_Family_AllCounties_2015_2025.csv
  By_Pollutant/Ozone_AllCounties_2015_2025.csv
  By_Pollutant/PM10_AllCounties_2015_2025.csv
  By_Pollutant/PM2.5_AllCounties_2015_2025.csv
  By_VOC/vocs_1hr_2016_2025.csv
  By_VOC/vocs_24hr_2015_2025.csv
  By_Pollutant_Daily/pollutant_daily_24hr_2015_2025.csv

Runtime: ~3-5 min on SSD for the full 9.77M-row pull.
"""

from __future__ import annotations

import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import pandas as pd

from pipeline.utils.io import (
    PipelineConfig,
    ensure_dir,
    load_config,
    write_csv,
)
from pipeline.utils.logging import get_logger, step_timer


# ---------------------------------------------------------------------------
# AQS RD v1.6 transaction format
# ---------------------------------------------------------------------------
RD_COLS = [
    "ttype", "action", "state", "county", "site", "param", "poc", "dur",
    "unit", "meth", "date", "time", "value", "null_cd", "freq", "proto",
    "q1", "q2", "q3", "q4", "q5", "q6", "q7", "q8", "q9", "q10",
    "mdl", "unc",
]
HEADER_ROWS = 11

# 24hr sampling duration codes — these route to pollutant_daily_24hr.
DAILY_24HR_DUR_CODES = {"7", "X"}


# ---------------------------------------------------------------------------
# AQS parameter code → (friendly name, pollutant group)
# ---------------------------------------------------------------------------
# Criteria pollutants and the canonical TCEQ VOC AutoGC menu (47 species).
# See !Archive_v0_3_7/inventory/parameter_reference.md for the full table.
PARAM_GROUP: dict[int, tuple[str, str]] = {
    # ----- Criteria pollutants -----
    42101: ("CO",            "CO"),
    42401: ("SO2",           "SO2"),
    42601: ("NO",            "NOx_Family"),
    42602: ("NO2",           "NOx_Family"),
    42603: ("NOx",           "NOx_Family"),
    44201: ("Ozone",         "Ozone"),
    81102: ("PM10 STP",      "PM10"),
    88101: ("PM2.5 FRM/FEM", "PM2.5"),
    88502: ("PM2.5 (any method)", "PM2.5"),
    # ----- VOCs: Paraffins -----
    43202: ("Ethane",                 "VOCs"),
    43205: ("Propane",                "VOCs"),
    43212: ("n-Butane",               "VOCs"),
    43214: ("Isobutane",              "VOCs"),
    43220: ("n-Pentane",              "VOCs"),
    43221: ("Isopentane",             "VOCs"),
    43231: ("n-Hexane",               "VOCs"),
    43232: ("n-Heptane",              "VOCs"),
    43233: ("n-Octane",               "VOCs"),
    43235: ("n-Nonane",               "VOCs"),
    43238: ("n-Decane",               "VOCs"),
    43244: ("2,2-Dimethylbutane",     "VOCs"),
    43247: ("2,4-Dimethylpentane",    "VOCs"),
    43249: ("3-Methylhexane",         "VOCs"),
    43250: ("2,2,4-Trimethylpentane", "VOCs"),
    43252: ("2,3,4-Trimethylpentane", "VOCs"),
    43253: ("3-Methylheptane",        "VOCs"),
    43263: ("2-Methylhexane",         "VOCs"),
    43291: ("2-Methylpentane",        "VOCs"),
    43954: ("n-Undecane",             "VOCs"),
    43960: ("2-Methylheptane",        "VOCs"),
    # ----- VOCs: Cycloalkanes -----
    43242: ("Cyclopentane",           "VOCs"),
    43248: ("Cyclohexane",            "VOCs"),
    43261: ("Methylcyclohexane",      "VOCs"),
    43262: ("Methylcyclopentane",     "VOCs"),
    # ----- VOCs: Olefins / dienes / alkynes -----
    43203: ("Ethylene",               "VOCs"),
    43204: ("Propylene",              "VOCs"),
    43206: ("Acetylene",              "VOCs"),
    43216: ("trans-2-Butene",         "VOCs"),
    43217: ("cis-2-Butene",           "VOCs"),
    43218: ("1,3-Butadiene",          "VOCs"),
    43224: ("1-Pentene",              "VOCs"),
    43226: ("trans-2-Pentene",        "VOCs"),
    43227: ("cis-2-Pentene",          "VOCs"),
    43228: ("2-Methyl-2-butene",      "VOCs"),
    43243: ("Isoprene",               "VOCs"),
    43280: ("1-Butene",               "VOCs"),
    # ----- VOCs: Aromatics (BTEX and beyond) -----
    45109: ("m/p-Xylene",             "VOCs"),
    45201: ("Benzene",                "VOCs"),
    45202: ("Toluene",                "VOCs"),
    45203: ("Ethylbenzene",           "VOCs"),
    45204: ("o-Xylene",               "VOCs"),
    45207: ("1,3,5-Trimethylbenzene", "VOCs"),
    45208: ("1,2,4-Trimethylbenzene", "VOCs"),
    45209: ("n-Propylbenzene",        "VOCs"),
    45210: ("Isopropylbenzene",       "VOCs"),
    45220: ("Styrene",                "VOCs"),
    45225: ("1,2,3-Trimethylbenzene", "VOCs"),
}


# ---------------------------------------------------------------------------
# Texas county FIPS code → county name
# ---------------------------------------------------------------------------
# 13 counties in the project scope. Source: US Census Bureau Texas FIPS.
COUNTY_NAMES: dict[str, str] = {
    "013": "Atascosa",
    "029": "Bexar",
    "061": "Cameron",
    "091": "Comal",
    "187": "Guadalupe",
    "215": "Hidalgo",
    "255": "Karnes",
    "273": "Kleberg",
    "323": "Maverick",
    "355": "Nueces",
    "469": "Victoria",
    "479": "Webb",
    "493": "Wilson",
}


# ---------------------------------------------------------------------------
# Canonical site_name lookup (matches aq_v0_3_7_epa.site_registry)
# ---------------------------------------------------------------------------
# Built from !Archive_v0_3_7/db_metadata/02_site_registry.csv. Adding a new
# TCEQ site? Look it up via Neon MCP query:
#     SELECT aqsid, site_name FROM aq_v0_3_7_epa.site_registry WHERE aqsid = '...';
# or pick a name from the TCEQ site directory and keep the trailing
# _XXXX last-4-of-AQSID suffix for disambiguation.
SITE_NAMES_CANONICAL: dict[str, str] = {
    # Atascosa
    "480131090": "Pleasanton_1090",
    # Bexar
    "480290032": "San Antonio Northwest_0032",
    "480290052": "Camp Bullis_0052",
    "480290053": "Live Oak_0053",
    "480290055": "CPS Pecan Valley_0055",
    "480290059": "Calaveras Lake_0059",
    "480290060": "San Antonio Palo Alto_0060",
    "480290501": "Elm Creek Elementary_0501",
    "480290502": "Fair Oaks Ranch_0502",
    "480290622": "Heritage Middle School_0622",
    "480290677": "San Antonio Old Hwy 90_0677",
    "480291069": "Converse_1069",
    "480291080": "Heritage MS SO2_1080",
    "480291087": "Windcrest_1087",
    "480291091": "San Antonio Red Hill Lane_1091",
    "480291610": "Government Canyon_1610",
    # Cameron
    "480610006": "Brownsville_0006",
    "480611023": "Harlingen_1023",
    "480611098": "Brownsville Roca_1098",
    "480612004": "Port Isabel_2004",
    # Comal
    "480910503": "Bulverde Elementary_0503",
    "480910505": "City of Garden Ridge_0505",
    "480911088": "New Braunfels Oak Run Parkway_1088",
    # Guadalupe
    "481870504": "New Braunfels Airport_0504",
    "481870506": "Seguin Outdoor Learning Center_0506",
    # Hidalgo
    "482150043": "Mission_0043",
    "482151046": "Edinburg_1046",
    # Karnes
    "482551070": "Karnes City_1070",
    # Kleberg
    "482730314": "Kingsville_0314",
    # Maverick
    "483230004": "Eagle Pass_0004",
    # Nueces
    "483550025": "Corpus Christi West_0025",
    "483550026": "Corpus Christi Tuloso_0026",
    "483550029": "Corpus Christi Hillcrest_0029",
    "483550032": "Corpus Christi Dona Park_0032",
    "483550034": "Corpus Christi Holly_0034",
    "483550083": "Corpus Christi Palm_0083",
    # Victoria
    "484690003": "Victoria_0003",
    # Webb
    "484790016": "Laredo Vidaurri_0016",
    "484790017": "Laredo Santa Maria_0017",
    "484790313": "Laredo Hachar_0313",
    # Wilson
    "484931038": "Floresville_1038",
}


# ---------------------------------------------------------------------------
# Sites dropped from v0.4.0 entirely (defensive — they shouldn't be in pull)
# ---------------------------------------------------------------------------
DROPPED_AQSIDS = {
    "480290623",  # Gardner Rd. Gas SubStation (CPS fence-line, no data)
    "480290625",  # Gate 9A CPS (CPS fence-line, no data)
    "480290626",  # Gate 58 CPS (CPS fence-line, no data)
    "480291609",  # Calaveras Lake Park (TSP-only — decision #8)
    "480291097",  # Von Ormy_1097 (not in TCEQ pull — decision #18)
    "483551024",  # Williams Park (disabled, no data)
}


# ---------------------------------------------------------------------------
# Canonical 14-column output schema (no data_source — decision #3)
# ---------------------------------------------------------------------------
CANONICAL_COLS = [
    "state_code", "county_code", "site_number", "parameter_code", "poc",
    "date_local", "time_local", "sample_measurement", "method_code",
    "county_name", "pollutant_name", "aqsid", "pollutant_group", "site_name",
]

# Output filenames (under each subdirectory)
CRITERIA_CSV_NAMES = {
    "CO":         "CO_AllCounties_2015_2025.csv",
    "SO2":        "SO2_AllCounties_2015_2025.csv",
    "NOx_Family": "NOx_Family_AllCounties_2015_2025.csv",
    "Ozone":      "Ozone_AllCounties_2015_2025.csv",
    "PM10":       "PM10_AllCounties_2015_2025.csv",
    "PM2.5":      "PM2.5_AllCounties_2015_2025.csv",
}
VOC_1HR_CSV_NAME    = "vocs_1hr_2016_2025.csv"
VOC_24HR_CSV_NAME   = "vocs_24hr_2015_2025.csv"
DAILY_24HR_CSV_NAME = "pollutant_daily_24hr_2015_2025.csv"


# ---------------------------------------------------------------------------
# File classification
# ---------------------------------------------------------------------------
def detect_file_kind(name: str) -> tuple[str, str | None, str | None]:
    """Classify file → (kind, identifier, ab_or_cadence).

    Returns:
        ("site", aqsid_9digit, ab_tag_or_None)
        ("voc",  county_label, "1hr" | "24hr")
        ("unknown", None, None)
    """
    if "VOC" in name.upper():
        county = re.split(r"_VOCS?", name, flags=re.IGNORECASE)[0]
        cadence = "1hr" if "1hr" in name.lower() else "24hr"
        return ("voc", county, cadence)
    base = name.replace(".txt", "")
    m = re.match(r"^(\d{9})(?:_([A-Za-z].*))?$", base)
    if m:
        return ("site", m.group(1), m.group(2))
    return ("unknown", None, None)


# ---------------------------------------------------------------------------
# Per-file parsing
# ---------------------------------------------------------------------------
def parse_rd_file(path: Path) -> pd.DataFrame:
    """Read one AQS RD TXT file as a DataFrame with the RD_COLS schema."""
    df = pd.read_csv(
        path,
        sep="|",
        skiprows=HEADER_ROWS,
        names=RD_COLS,
        engine="c",
        on_bad_lines="skip",
        dtype=str,
    )
    df = df[df["ttype"] == "RD"].copy()
    return df


def to_canonical(raw: pd.DataFrame) -> pd.DataFrame:
    """Map RD-format raw rows → canonical 14-column schema."""
    out = pd.DataFrame({
        "state_code":         raw["state"].astype(int),
        "county_code":        raw["county"].astype(int),
        "site_number":        raw["site"].astype(int),
        "parameter_code":     raw["param"].astype(int),
        "poc":                raw["poc"].astype(int),
        "date_local":         pd.to_datetime(raw["date"], format="%Y%m%d").dt.strftime("%Y-%m-%d"),
        "time_local":         raw["time"].astype(str).str.zfill(5),
        "sample_measurement": pd.to_numeric(raw["value"], errors="coerce"),
        "method_code":        pd.to_numeric(raw["meth"], errors="coerce").astype("Int32"),
    })
    out["aqsid"] = (
        out["state_code"].astype(str).str.zfill(2)
        + out["county_code"].astype(str).str.zfill(3)
        + out["site_number"].astype(str).str.zfill(4)
    )
    out["county_name"] = (
        out["county_code"].astype(str).str.zfill(3).map(COUNTY_NAMES).fillna("")
    )
    # Parameter-derived columns
    out["pollutant_name"]  = out["parameter_code"].map(lambda c: PARAM_GROUP.get(c, (f"AQS_{c}", "UNKNOWN"))[0])
    out["pollutant_group"] = out["parameter_code"].map(lambda c: PARAM_GROUP.get(c, (f"AQS_{c}", "UNKNOWN"))[1])
    out["site_name"]       = out["aqsid"].map(SITE_NAMES_CANONICAL).fillna("UNKNOWN_" + out["aqsid"])
    # Preserve sample duration code for routing — temporary column, dropped before output
    out["_dur"] = raw["dur"].astype(str)
    return out


def normalize_ozone_units(df: pd.DataFrame, log) -> pd.DataFrame:
    """TCEQ reports ozone in ppb; EPA/pipeline canonical unit is ppm. ×0.001."""
    mask = df["parameter_code"] == 44201
    n = int(mask.sum())
    if n:
        df.loc[mask, "sample_measurement"] = df.loc[mask, "sample_measurement"] * 0.001
        log.info(f"  unit normalize: ozone ppb -> ppm ({n:,} rows × 0.001)")
    return df


def drop_excluded_sites(df: pd.DataFrame, log) -> pd.DataFrame:
    """Drop rows for sites that are not part of v0.4.0 (decisions #8, #18)."""
    mask = df["aqsid"].isin(DROPPED_AQSIDS)
    n = int(mask.sum())
    if n:
        which = sorted(df.loc[mask, "aqsid"].unique())
        log.warning(f"  defensive drop: {n:,} rows for {len(which)} excluded AQSIDs: {which}")
        df = df.loc[~mask].copy()
    return df


def warn_unknown_sites(df: pd.DataFrame, log) -> None:
    """Log a warning if any site_name resolved to UNKNOWN_<aqsid>."""
    unk = df[df["site_name"].str.startswith("UNKNOWN_")]
    if len(unk):
        which = sorted(unk["aqsid"].unique())
        log.warning(
            f"  unknown site_name for {len(unk):,} rows across "
            f"{len(which)} AQSIDs: {which}. "
            "Add to SITE_NAMES_CANONICAL in step_01b_ingest_tceq_raw.py."
        )


def warn_unknown_params(df: pd.DataFrame, log) -> None:
    """Log a warning if any parameter_code mapped to UNKNOWN group."""
    unk = df[df["pollutant_group"] == "UNKNOWN"]
    if len(unk):
        which = sorted(unk["parameter_code"].unique())
        log.warning(
            f"  unknown pollutant_group for {len(unk):,} rows across "
            f"{len(which)} parameter_codes: {which}. "
            "Add to PARAM_GROUP in step_01b_ingest_tceq_raw.py."
        )


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------
def route_to_outputs(
    df: pd.DataFrame,
    voc_cadence: str | None,
    log,
) -> dict[str, pd.DataFrame]:
    """Split a canonical-schema frame into output buckets.

    Routing rules (in order, mutually exclusive):
      1. VOC pollutant_group AND we're inside a VOC county file
         → voc_1hr or voc_24hr (cadence comes from filename, not row)
      2. Any row with sample duration code in DAILY_24HR_DUR_CODES
         → pollutant_daily_24hr
      3. Criteria pollutant in hourly cadence
         → pollutant_<group> (CO, SO2, NOx_Family, Ozone, PM10, PM2.5)
      4. Anything else (UNKNOWN groups, dur codes we don't recognize)
         → dropped with a warning
    """
    out: dict[str, pd.DataFrame] = {}

    # ---- Rule 1: VOC rows from county files -----------------------------
    if voc_cadence is not None:
        # Inside a VOC county file. Everything goes to vocs_<cadence> regardless
        # of pollutant_group (defensively — file should only contain VOCs).
        bucket = f"voc_{voc_cadence}"
        out[bucket] = df.copy()
        return out

    # ---- Rule 2: Site files — split by sample duration code -------------
    is_daily = df["_dur"].isin(DAILY_24HR_DUR_CODES)
    daily_df = df.loc[is_daily]
    hourly_df = df.loc[~is_daily]

    if len(daily_df):
        # These rows route to pollutant_daily_24hr regardless of pollutant_group
        # (typically just site 480290060 PM10).
        out["daily_24hr"] = daily_df

    # ---- Rule 3/4: Hourly rows split by pollutant_group ----------------
    for group, sub in hourly_df.groupby("pollutant_group", sort=False):
        if group == "UNKNOWN":
            log.warning(f"  {len(sub):,} rows have UNKNOWN pollutant_group — dropped")
            continue
        if group == "VOCs":
            # VOC rows in a site file (unusual — VOCs are normally in county files).
            # Log loudly because this means our routing assumption is wrong somewhere.
            log.warning(
                f"  {len(sub):,} VOC rows in a site file (not a county VOC file) — "
                "routing to voc_1hr defensively, please investigate"
            )
            out["voc_1hr"] = pd.concat([out.get("voc_1hr"), sub]) if "voc_1hr" in out else sub
            continue
        out[f"criteria_{group}"] = sub

    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def _resolve_tceq_dir(cfg: PipelineConfig, log) -> Path:
    """Try the primary raw_tceq path, fall back to raw_tceq_fallback."""
    primary = cfg.path("raw_tceq")
    if primary.exists() and any(primary.glob("*.txt")):
        log.info(f"raw_tceq (primary): {primary}")
        return primary

    fallback_raw = cfg.raw["paths"].get("raw_tceq_fallback")
    if fallback_raw:
        fb = Path(fallback_raw).expanduser().resolve()
        if fb.exists() and any(fb.glob("*.txt")):
            log.warning(
                f"raw_tceq primary {primary} not found or empty; "
                f"using fallback: {fb}"
            )
            return fb

    raise FileNotFoundError(
        f"No TCEQ .txt files found at primary {primary} "
        f"or fallback {fallback_raw}. Check config.yaml:paths.raw_tceq."
    )


def main(cfg: PipelineConfig | None = None) -> bool:
    cfg = cfg or load_config()
    log = get_logger("01b_ingest_tceq_raw", log_dir=cfg.path("logs"))

    log.info("=" * 70)
    log.info("Step 01b — TCEQ raw ingestion (v0.4.0)")
    log.info("=" * 70)

    in_dir = _resolve_tceq_dir(cfg, log)
    files = sorted(p for p in in_dir.iterdir() if p.suffix == ".txt")
    log.info(f"Found {len(files)} TXT files to ingest")

    # Output buckets: accumulate per-file canonical frames into these,
    # then concat + dedup + write at the end.
    buckets: dict[str, list[pd.DataFrame]] = defaultdict(list)
    file_stats: list[dict] = []

    t_all = time.time()
    for i, path in enumerate(files, 1):
        kind, ident, tag = detect_file_kind(path.name)
        with step_timer(log, f"[{i:>2}/{len(files)}] {path.name} ({kind})"):
            try:
                raw = parse_rd_file(path)
            except Exception as e:
                log.error(f"  PARSE FAILED for {path.name}: {e}")
                continue
            if not len(raw):
                log.warning(f"  no RD rows in {path.name}, skipping")
                continue

            canon = to_canonical(raw)
            n_raw = len(canon)

            canon = drop_excluded_sites(canon, log)
            warn_unknown_sites(canon, log)
            warn_unknown_params(canon, log)
            canon = normalize_ozone_units(canon, log)

            voc_cadence = tag if kind == "voc" else None
            out_buckets = route_to_outputs(canon, voc_cadence, log)
            for bucket, sub in out_buckets.items():
                buckets[bucket].append(sub)

            file_stats.append({
                "file": path.name,
                "kind": kind,
                "identifier": ident,
                "raw_rows": n_raw,
                "buckets": {b: len(s) for b, s in out_buckets.items()},
            })

    log.info(f"\n--- All {len(files)} files parsed in {time.time()-t_all:.1f}s ---")

    # Concat each bucket, dedup, and write -----------------------------------
    out_dir_root = cfg.root / "01_Data" / "Processed"
    out_pol = ensure_dir(out_dir_root / "By_Pollutant")
    out_voc = ensure_dir(out_dir_root / "By_VOC")
    out_d24 = ensure_dir(out_dir_root / "By_Pollutant_Daily")

    dedup_key = ["aqsid", "date_local", "time_local", "parameter_code", "poc"]

    grand_total_in  = 0
    grand_total_out = 0

    log.info("\n--- Writing outputs ---")
    for bucket, frames in buckets.items():
        if not frames:
            continue
        merged = pd.concat(frames, ignore_index=True, sort=False)
        n_before = len(merged)
        merged = merged.drop_duplicates(subset=dedup_key, keep="first").reset_index(drop=True)
        n_after = len(merged)
        n_dropped = n_before - n_after
        # Strip the temporary _dur column before writing.
        merged = merged.drop(columns=[c for c in merged.columns if c not in CANONICAL_COLS])
        # Enforce column order.
        merged = merged[CANONICAL_COLS]

        # Determine output path
        if bucket.startswith("criteria_"):
            group = bucket[len("criteria_"):]
            target = out_pol / CRITERIA_CSV_NAMES[group]
        elif bucket == "voc_1hr":
            target = out_voc / VOC_1HR_CSV_NAME
        elif bucket == "voc_24hr":
            target = out_voc / VOC_24HR_CSV_NAME
        elif bucket == "daily_24hr":
            target = out_d24 / DAILY_24HR_CSV_NAME
        else:
            log.warning(f"  unknown bucket {bucket!r}, skipping write")
            continue

        write_csv(merged, target)
        grand_total_in  += n_before
        grand_total_out += n_after
        log.info(
            f"  {bucket:>18}  rows {n_before:>9,} -> {n_after:>9,} "
            f"(dropped {n_dropped:>7,} dupes)  -> {target.name}"
        )

    log.info(
        f"\nTOTAL  in={grand_total_in:,}  out={grand_total_out:,}  "
        f"dedup-dropped={grand_total_in - grand_total_out:,}"
    )
    log.info(f"Total runtime: {(time.time()-t_all)/60:.1f} min")
    return True


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
