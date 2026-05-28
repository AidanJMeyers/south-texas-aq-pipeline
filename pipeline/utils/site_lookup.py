"""v0.4.0 site registry builder.

Builds the canonical site inventory by combining four sources:

1. **Pipeline parquet data** — sites that actually have rows in:
     - data/parquet/pollutants/         (criteria hourly)
     - data/parquet/pollutant_daily_24hr/ (24hr-only criteria, e.g. site 0060)
     - data/parquet/vocs_1hr/           (1hr AutoGC VOCs)
     - data/parquet/vocs_24hr/          (24hr AutoGC VOCs)
2. **Canonical site name lookup** (SITE_NAMES_CANONICAL in step_01b)
3. **Coordinate sources** (enhanced_monitoring_sites.csv + Extra TCEQ Sites.xlsx)
4. **Disabled-site marker** (Williams Park 483551024 — still tracked for completeness)

v0.4.0 changes vs v0.3.7:
  - Drops 4 TSP-only sites entirely (623, 625, 626, 1609 — decision #8)
  - Drops 3 CPS Energy fence-line "reference" sites entirely (no data, no purpose)
  - Drops Von Ormy 480291097 (not in TCEQ pull — decision #18)
  - Drops `network` column ('TCEQ' is constant — covered by data_source removal)
  - Drops `pollutants` text column → replaced by THREE new array columns:
      * pollutant_groups_hourly[]      — criteria pollutants at hourly cadence
      * pollutant_groups_daily_24hr[]  — anything routed to pollutant_daily_24hr
      * voc_cadence                    — '1hr', '24hr', 'both', or NULL

Total v0.4.0 registry: ~40 active + 1 disabled (Williams Park) = 41 sites.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd

from pipeline.utils.io import PipelineConfig, read_parquet_dataset


# Disabled sites (registered historically but no current data in TCEQ pull)
DISABLED_SITES: dict[str, dict] = {
    "483551024": {
        "site_name": "Williams Park",
        "county_name": "Nueces",
        "state_code": 48,
        "county_code": 355,
        "site_number": 1024,
        "notes": "Disabled per 06_HTML_Reports/10_Site_Inventory_Report.html (TSP only, not in TCEQ pull)",
    },
}


def _read_aqsids_with_groups(parquet_root: Path, group_col: str = "pollutant_group") -> pd.DataFrame:
    """Return one-row-per-site with the set of pollutant groups present."""
    if not parquet_root.exists():
        return pd.DataFrame(columns=["aqsid", group_col, "site_name", "county_name",
                                      "state_code", "county_code", "site_number",
                                      "first_date", "last_date", "n_records"])
    df = read_parquet_dataset(
        parquet_root,
        columns=["aqsid", group_col, "site_name", "county_name",
                 "state_code", "county_code", "site_number", "date_local"],
    )
    g = (
        df.groupby("aqsid", dropna=False)
          .agg(
              site_name=("site_name", "first"),
              county_name=("county_name", "first"),
              state_code=("state_code", "first"),
              county_code=("county_code", "first"),
              site_number=("site_number", "first"),
              groups=(group_col, lambda s: sorted(set(s.dropna()))),
              first_date=("date_local", "min"),
              last_date=("date_local", "max"),
              n_records=("date_local", "size"),
          )
          .reset_index()
    )
    return g


def _read_vocs_aqsids(parquet_root: Path) -> pd.DataFrame:
    """One row per site with just aqsid + base attributes (no group)."""
    if not parquet_root.exists():
        return pd.DataFrame(columns=["aqsid", "site_name", "county_name",
                                      "state_code", "county_code", "site_number",
                                      "first_date", "last_date", "n_records"])
    df = read_parquet_dataset(
        parquet_root,
        columns=["aqsid", "site_name", "county_name",
                 "state_code", "county_code", "site_number", "date_local"],
    )
    g = (
        df.groupby("aqsid", dropna=False)
          .agg(
              site_name=("site_name", "first"),
              county_name=("county_name", "first"),
              state_code=("state_code", "first"),
              county_code=("county_code", "first"),
              site_number=("site_number", "first"),
              first_date=("date_local", "min"),
              last_date=("date_local", "max"),
              n_records=("date_local", "size"),
          )
          .reset_index()
    )
    return g


def _merge_coords(registry: pd.DataFrame, cfg: PipelineConfig) -> pd.DataFrame:
    """Merge lat/lon from enhanced_monitoring_sites.csv and Extra TCEQ Sites.xlsx."""
    ref_csv_path = cfg.path("site_reference")
    xlsx_path    = cfg.path("tceq_registry")

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
    return registry


def build_site_registry(cfg: PipelineConfig) -> pd.DataFrame:
    """Return the canonical v0.4.0 site registry DataFrame.

    Columns:
        aqsid, state_code, county_code, site_number,
        site_name, county_name,
        pollutant_groups_hourly       (TEXT[]) — criteria pollutants at hourly cadence
        pollutant_groups_daily_24hr   (TEXT[]) — anything in pollutant_daily_24hr
        voc_cadence                   (TEXT)   — '1hr' | '24hr' | 'both' | NULL
        n_pollutant_groups            (int)    — len(union of hourly + daily_24hr + (VOCs if voc_cadence))
        first_date, last_date         (TEXT)
        n_records                     (int)
        data_status                   (TEXT)   — 'active' | 'disabled'
        notes                         (TEXT)
        lat, lon                      (float)
    """
    # ---- Read pipeline data sources ----
    hourly  = _read_aqsids_with_groups(cfg.path("parquet_pollutants"))
    daily24 = _read_aqsids_with_groups(cfg.path("parquet_daily_24hr"))
    voc1    = _read_vocs_aqsids(cfg.path("parquet_vocs_1hr"))
    voc24   = _read_vocs_aqsids(cfg.path("parquet_vocs_24hr"))

    # ---- Index by aqsid so we can union and merge per-site ----
    all_aqsids = sorted(
        set(hourly["aqsid"]) | set(daily24["aqsid"])
        | set(voc1["aqsid"]) | set(voc24["aqsid"])
    )

    hourly_idx  = hourly.set_index("aqsid")  if len(hourly)  else None
    daily24_idx = daily24.set_index("aqsid") if len(daily24) else None
    voc1_idx    = voc1.set_index("aqsid")    if len(voc1)    else None
    voc24_idx   = voc24.set_index("aqsid")   if len(voc24)   else None

    rows: list[dict] = []
    for aqsid in all_aqsids:
        # Pull base attributes from whichever source has data (hourly first)
        for src in (hourly_idx, daily24_idx, voc1_idx, voc24_idx):
            if src is not None and aqsid in src.index:
                base = src.loc[aqsid].to_dict()
                break
        else:
            continue

        hourly_groups  = hourly_idx.loc[aqsid, "groups"]  if hourly_idx  is not None and aqsid in hourly_idx.index  else []
        daily24_groups = daily24_idx.loc[aqsid, "groups"] if daily24_idx is not None and aqsid in daily24_idx.index else []
        in_voc1  = voc1_idx  is not None and aqsid in voc1_idx.index
        in_voc24 = voc24_idx is not None and aqsid in voc24_idx.index

        voc_cadence = (
            "both" if (in_voc1 and in_voc24)
            else ("1hr" if in_voc1
            else ("24hr" if in_voc24 else None))
        )

        # First/last date and record count: max across all sources where this site appears
        first_dates = []
        last_dates  = []
        n_records   = 0
        for src in (hourly_idx, daily24_idx, voc1_idx, voc24_idx):
            if src is not None and aqsid in src.index:
                r = src.loc[aqsid]
                if pd.notna(r["first_date"]):
                    first_dates.append(r["first_date"])
                if pd.notna(r["last_date"]):
                    last_dates.append(r["last_date"])
                n_records += int(r["n_records"])

        n_groups = (
            len(set(hourly_groups) | set(daily24_groups))
            + (1 if voc_cadence else 0)
        )

        rows.append({
            "aqsid": aqsid,
            "state_code": int(base["state_code"]),
            "county_code": int(base["county_code"]),
            "site_number": int(base["site_number"]),
            "site_name": base["site_name"],
            "county_name": base["county_name"],
            "pollutant_groups_hourly":     ";".join(hourly_groups),
            "pollutant_groups_daily_24hr": ";".join(daily24_groups),
            "voc_cadence": voc_cadence or "",
            "n_pollutant_groups": n_groups,
            "first_date": min(first_dates) if first_dates else None,
            "last_date":  max(last_dates)  if last_dates  else None,
            "n_records": n_records,
            "data_status": "active",
            "notes": "",
        })

    # ---- Add disabled sites for completeness ----
    for aqsid, info in DISABLED_SITES.items():
        if aqsid in {r["aqsid"] for r in rows}:
            continue
        rows.append({
            "aqsid": aqsid,
            "state_code": info["state_code"],
            "county_code": info["county_code"],
            "site_number": info["site_number"],
            "site_name": info["site_name"],
            "county_name": info["county_name"],
            "pollutant_groups_hourly":     "",
            "pollutant_groups_daily_24hr": "",
            "voc_cadence": "",
            "n_pollutant_groups": 0,
            "first_date": None,
            "last_date":  None,
            "n_records": 0,
            "data_status": "disabled",
            "notes": info["notes"],
        })

    registry = pd.DataFrame(rows)
    registry = _merge_coords(registry, cfg)

    # Canonical column order
    cols = [
        "aqsid", "state_code", "county_code", "site_number",
        "site_name", "county_name",
        "pollutant_groups_hourly", "pollutant_groups_daily_24hr",
        "voc_cadence", "n_pollutant_groups",
        "first_date", "last_date", "n_records",
        "data_status", "notes",
        "lat", "lon",
    ]
    # Add lat/lon if merge skipped (defensive)
    for c in ("lat", "lon"):
        if c not in registry.columns:
            registry[c] = pd.NA
    registry = registry[cols]
    registry = registry.sort_values(["data_status", "county_name", "aqsid"]).reset_index(drop=True)
    return registry
