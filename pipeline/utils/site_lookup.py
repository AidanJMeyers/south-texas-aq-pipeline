"""Canonical South Texas AQ site registry.

Builds the authoritative site inventory by combining four sources:

1. **Pipeline data** — the sites that actually have measurement rows in
   ``data/parquet/daily/`` after step 04. These are the truly active sites
   you can query against.
2. **Enhanced monitoring sites CSV** — ``01_Data/Reference/enhanced_monitoring_sites.csv``
   provides AQS-verified lat/lon for 29 sites.
3. **Extra TCEQ Sites workbook** — ``!Final Raw Data/Extra TCEQ Sites.xlsx``
   provides lat/lon for 18 additional TCEQ CAMS sites.
4. **Site inventory report** — ``06_HTML_Reports/10_Site_Inventory_Report.html``.

Each row carries a ``data_status`` tag:

    ``active``    — has measurement rows in the pipeline
    ``reference`` — CPS fence-line monitors; registered but no data
    ``pending``   — raw data not yet downloaded from TCEQ TAMIS
    ``disabled``  — historically registered but the station is no longer
                    active (Williams Park 483551024 — confirmed per
                    10_Site_Inventory_Report.html)

**Calaveras distinction:** AQSID ``480290059`` is **Calaveras Lake** (the
EPA-operated monitor, 5.8+ years of data from Calaveras Lake proper).
AQSID ``480291609`` is **Calaveras Lake Park** (a separate TCEQ monitor
at the nearby park). They are DIFFERENT physical stations — do NOT
deduplicate. Calaveras Lake Park currently has no raw data in the project;
it is listed as ``pending``.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from pipeline.utils.io import PipelineConfig, read_pollutant_csv


# Sites known to be reference-only (CPS Energy fence-line monitors)
REFERENCE_ONLY_SITES = {
    "480290623": "Gardner Rd. Gas SubStation",
    "480290625": "Gate 9A CPS",
    "480290626": "Gate 58 CPS",
}

# Sites awaiting raw-data download from TCEQ TAMIS.
# Calaveras Lake Park (480291609) is a SEPARATE TCEQ monitor from
# Calaveras Lake (480290059, EPA) — not an alias. It has no raw data
# downloaded into the project yet.
PENDING_SITES = {
    "480291609": ("Calaveras Lake Park", "Bexar", 29),
}

# Sites that appear in the inventory as historically registered but are
# confirmed **disabled** per 06_HTML_Reports/10_Site_Inventory_Report.html
DISABLED_SITES = {
    "483551024": ("Williams Park", "Nueces", 355),
}


def build_site_registry(cfg: PipelineConfig) -> pd.DataFrame:
    """Return the canonical 47-site registry as a DataFrame.

    Columns:
        aqsid, state_code, county_code, site_number, site_name, county_name,
        network (EPA/TCEQ/BOTH/''),
        pollutants (;-separated), n_pollutants,
        first_date, last_date, n_records,
        data_status,
            - active     = has measurement data in the pipeline
            - reference  = CPS fence-line, registered but no data
            - pending    = needs TCEQ TAMIS download
            - disabled   = confirmed disabled in inventory report
            - tceq_alias = TCEQ internal alias; data written under another AQSID
        co_located_with  (cross-reference AQSID or empty),
        notes (free text about the row),
        lat, lon
    """
    # ---- 1. Active sites from the pipeline CSVs -------------------------
    pollutant_dir = cfg.path("processed_pollutant")
    csvs = sorted(pollutant_dir.glob("*_AllCounties_*.csv"))
    if not csvs:
        raise FileNotFoundError(f"No pollutant CSVs found in {pollutant_dir}")

    key_cols = [
        "aqsid", "state_code", "county_code", "site_number",
        "site_name", "county_name", "data_source", "pollutant_group",
        "date_local",
    ]
    frames = [read_pollutant_csv(csv)[key_cols].copy() for csv in csvs]
    allrows = pd.concat(frames, ignore_index=True)
    allrows["county_name"] = allrows["county_name"].astype(str).str.title()

    active = (
        allrows.groupby(["aqsid", "state_code", "county_code", "site_number"], dropna=False)
        .agg(
            site_name=("site_name", "first"),
            county_name=("county_name", "first"),
            networks=("data_source", lambda s: sorted(set(s.dropna()))),
            pollutants=("pollutant_group", lambda s: sorted(set(s.dropna()))),
            first_date=("date_local", "min"),
            last_date=("date_local", "max"),
            n_records=("date_local", "size"),
        )
        .reset_index()
    )
    active["network"] = active["networks"].apply(
        lambda nets: "BOTH" if len(nets) > 1 else (nets[0] if nets else "")
    )
    active["n_pollutants"] = active["pollutants"].str.len()
    active["pollutants"] = active["pollutants"].apply(lambda lst: ";".join(lst))
    active = active.drop(columns=["networks"])
    active["data_status"] = "active"
    active["co_located_with"] = ""
    active["notes"] = ""

    # ---- 2. Reference-only CPS fence-line sites -------------------------
    ref_rows = []
    for aqsid, name in REFERENCE_ONLY_SITES.items():
        ref_rows.append({
            "aqsid": aqsid,
            "state_code": 48,
            "county_code": 29,
            "site_number": int(aqsid[-4:]),
            "site_name": name,
            "county_name": "Bexar",
            "network": "TCEQ",
            "pollutants": "",
            "n_pollutants": 0,
            "first_date": pd.NaT,
            "last_date": pd.NaT,
            "n_records": 0,
            "data_status": "reference",
            "co_located_with": "",
            "notes": "CPS Energy fence-line monitor; registered in inventory, no measurement data",
        })

    active_ids = set(active["aqsid"])

    # ---- 3. Sites pending TCEQ TAMIS download ---------------------------
    pending_rows = []
    for aqsid, (name, county, county_code) in PENDING_SITES.items():
        if aqsid in active_ids:
            continue  # already has data; promoted to active automatically
        pending_rows.append({
            "aqsid": aqsid,
            "state_code": 48,
            "county_code": county_code,
            "site_number": int(aqsid[-4:]),
            "site_name": name,
            "county_name": county,
            "network": "TCEQ",
            "pollutants": "",
            "n_pollutants": 0,
            "first_date": pd.NaT,
            "last_date": pd.NaT,
            "n_records": 0,
            "data_status": "pending",
            "co_located_with": "",
            "notes": "Raw data not yet downloaded from TCEQ TAMIS",
        })

    # ---- 4. Disabled sites ----------------------------------------------
    disabled_rows = []
    for aqsid, (name, county, county_code) in DISABLED_SITES.items():
        disabled_rows.append({
            "aqsid": aqsid,
            "state_code": 48,
            "county_code": county_code,
            "site_number": int(aqsid[-4:]),
            "site_name": name,
            "county_name": county,
            "network": "TCEQ",
            "pollutants": "",
            "n_pollutants": 0,
            "first_date": pd.NaT,
            "last_date": pd.NaT,
            "n_records": 0,
            "data_status": "disabled",
            "co_located_with": "",
            "notes": "Disabled per 06_HTML_Reports/10_Site_Inventory_Report.html",
        })

    registry = pd.concat(
        [active, pd.DataFrame(ref_rows), pd.DataFrame(pending_rows),
         pd.DataFrame(disabled_rows)],
        ignore_index=True,
    )

    # ---- 5. Coordinate merge (CSV + xlsx) -------------------------------
    ref_csv_path = cfg.path("site_reference")
    xlsx_path = cfg.path("tceq_registry")

    coord_frames: list[pd.DataFrame] = []
    if ref_csv_path.exists():
        ref_csv = pd.read_csv(ref_csv_path, dtype={"aqsid": str})
        if {"latitude", "longitude"}.issubset(ref_csv.columns):
            coord_frames.append(
                ref_csv[["aqsid", "latitude", "longitude"]].rename(
                    columns={"latitude": "lat", "longitude": "lon"}
                )
            )

    if xlsx_path.exists():
        try:
            xlsx = pd.read_excel(xlsx_path, sheet_name="Missing Sites")
            xlsx["aqsid"] = xlsx["AQS Site ID"].astype(str)
            coord_frames.append(
                xlsx[["aqsid", "Latitude", "Longitude"]].rename(
                    columns={"Latitude": "lat", "Longitude": "lon"}
                )
            )
        except Exception:
            pass

    if coord_frames:
        coords = (
            pd.concat(coord_frames, ignore_index=True)
            .drop_duplicates(subset=["aqsid"], keep="first")
        )
        registry = registry.merge(coords, on="aqsid", how="left")
    else:
        registry["lat"] = pd.NA
        registry["lon"] = pd.NA

    # Canonical column order
    cols = [
        "aqsid", "state_code", "county_code", "site_number",
        "site_name", "county_name", "network",
        "pollutants", "n_pollutants",
        "first_date", "last_date", "n_records",
        "data_status", "co_located_with", "notes",
        "lat", "lon",
    ]
    # Add lat/lon columns if they don't exist yet (the merge block below adds them)
    for c in ("lat", "lon"):
        if c not in registry.columns:
            registry[c] = pd.NA
    registry = registry[[c for c in cols if c in registry.columns]]
    registry = registry.sort_values(
        ["data_status", "county_name", "aqsid"]
    ).reset_index(drop=True)
    return registry
