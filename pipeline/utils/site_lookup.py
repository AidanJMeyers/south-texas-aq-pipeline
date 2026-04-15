"""Canonical South Texas AQ site registry.

Builds the authoritative 47-site inventory by combining four sources:

1. **Pipeline data** — the sites that actually have measurement rows in
   ``data/parquet/daily/`` after step 04. These are the truly active sites
   you can query against. Currently 41.
2. **Enhanced monitoring sites CSV** — ``01_Data/Reference/enhanced_monitoring_sites.csv``
   provides AQS-verified lat/lon for 29 sites (mostly EPA + a few TCEQ).
3. **Extra TCEQ Sites workbook** — ``!Final Raw Data/Extra TCEQ Sites.xlsx``
   provides lat/lon for 18 additional TCEQ CAMS sites.
4. **Site inventory report** — ``06_HTML_Reports/10_Site_Inventory_Report.html``
   lists all 47 sites known to the project.

Each output row carries a ``data_status`` tag so downstream consumers know
exactly what they're looking at:

    ``active``        — has measurement rows in the pipeline (41 sites)
    ``reference``     — CPS fence-line monitors; registered but no data
    ``pending``       — raw data not yet downloaded from TCEQ TAMIS
                        (Corpus Christi Palm 483550083)
    ``disabled``      — historically registered but the station is no
                        longer active (Williams Park 483551024 —
                        confirmed disabled in the site inventory report)

**Calaveras Lake note:** AQSID 480290059 (EPA) and 480291609 (TCEQ) both
appear in registry sources, but **only 480290059 is ever used as the AQSID
on actual measurement records** — even in raw files pulled from TCEQ TAMIS.
480291609 is a TCEQ-internal alias that exists in the site metadata but
never as a measurement ID. The two IDs are tracked as distinct registry
rows with a ``co_located_with`` cross-reference. They are **not** joined or
deduplicated — any "dedup" of the two would be meaningless because only
one of them ever carries data.
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

# Sites awaiting raw-data download from TCEQ TAMIS
PENDING_SITES = {
    "483550083": "Corpus Christi Palm",
}

# Sites that appear in the inventory as historically registered but are
# confirmed **disabled** per 06_HTML_Reports/10_Site_Inventory_Report.html
DISABLED_SITES = {
    "483551024": "Williams Park",
}

# TCEQ-internal aliases for physical locations whose measurement data is
# ALWAYS written under a different AQSID. Keys here never appear as an
# AQSID on actual measurement rows. This is informational only — the
# pipeline never joins or dedupes on these pairs.
TCEQ_INTERNAL_ALIASES: dict[str, dict] = {
    "480291609": {
        "site_name": "Calaveras Lake (TCEQ)",
        "county_name": "Bexar",
        "co_located_with": "480290059",  # EPA AQSID where data is written
        "note": "TCEQ registry alias; measurement data always recorded under EPA AQSID 480290059",
    },
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

    # ---- 3. Sites pending TCEQ TAMIS download ---------------------------
    pending_rows = []
    for aqsid, name in PENDING_SITES.items():
        pending_rows.append({
            "aqsid": aqsid,
            "state_code": 48,
            "county_code": 355,
            "site_number": int(aqsid[-4:]),
            "site_name": name,
            "county_name": "Nueces",
            "network": "TCEQ",
            "pollutants": "VOCs",
            "n_pollutants": 1,
            "first_date": pd.NaT,
            "last_date": pd.NaT,
            "n_records": 0,
            "data_status": "pending",
            "co_located_with": "",
            "notes": "VOCs AutoGC data not yet downloaded from TCEQ TAMIS; raw file was mislabeled with this site's name but contained Bexar data",
        })

    # ---- 4. Disabled sites ----------------------------------------------
    disabled_rows = []
    for aqsid, name in DISABLED_SITES.items():
        disabled_rows.append({
            "aqsid": aqsid,
            "state_code": 48,
            "county_code": 355,
            "site_number": int(aqsid[-4:]),
            "site_name": name,
            "county_name": "Nueces",
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

    # ---- 5. TCEQ internal aliases (informational) -----------------------
    alias_rows = []
    for aqsid, info in TCEQ_INTERNAL_ALIASES.items():
        alias_rows.append({
            "aqsid": aqsid,
            "state_code": 48,
            "county_code": int(aqsid[2:5]),
            "site_number": int(aqsid[-4:]),
            "site_name": info["site_name"],
            "county_name": info["county_name"],
            "network": "TCEQ",
            "pollutants": "",
            "n_pollutants": 0,
            "first_date": pd.NaT,
            "last_date": pd.NaT,
            "n_records": 0,
            "data_status": "tceq_alias",
            "co_located_with": info["co_located_with"],
            "notes": info["note"],
        })

    registry = pd.concat(
        [active, pd.DataFrame(ref_rows), pd.DataFrame(pending_rows),
         pd.DataFrame(disabled_rows), pd.DataFrame(alias_rows)],
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
