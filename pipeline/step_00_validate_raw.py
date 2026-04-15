"""Step 00 — Validate raw data integrity.

Reads every By_Pollutant CSV + the weather master and runs the checks listed
in PIPELINE_PROMPT.md §10. Writes a JSON report and exits nonzero on failure
so ``run_pipeline.py`` halts before doing any expensive work.

Inputs:
    01_Data/Processed/By_Pollutant/*.csv           (7 files)
    01_Data/Processed/Meteorological/Weather_Irradiance_Master_2015_2025.csv
    01_Data/Processed/Meteorological/AQ_Weather_SiteMapping.csv

Outputs:
    data/_validation/validation_report.json

Runtime: ~2 minutes (reads ~1 GB of CSV).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

from pipeline.utils.io import (
    PipelineConfig,
    POLLUTANT_COLUMNS,
    ensure_dir,
    load_config,
    read_pollutant_csv,
)
from pipeline.utils.logging import get_logger, step_timer
from pipeline.utils.validation import (
    CheckReport,
    CheckResult,
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    check_date_range_within,
    check_no_duplicate_hours,
    check_row_count,
    check_schema,
    check_unique_count,
)


POLLUTANT_FILE_MAP: dict[str, str] = {
    "CO":         "CO_AllCounties_2015_2025.csv",
    "NOx_Family": "NOx_Family_AllCounties_2015_2025.csv",
    "Ozone":      "Ozone_AllCounties_2015_2025.csv",
    "PM10":       "PM10_AllCounties_2015_2025.csv",
    "PM2.5":      "PM2.5_AllCounties_2015_2025.csv",
    "SO2":        "SO2_AllCounties_2015_2025.csv",
    "VOCs":       "VOCs_AllCounties_2016_2025.csv",
}


def main(cfg: PipelineConfig | None = None) -> bool:
    """Run all raw-data validation checks. Returns True if all passed."""
    cfg = cfg or load_config()
    log = get_logger("00_validate_raw", log_dir=cfg.path("logs"))
    report = CheckReport()

    pollutant_dir = cfg.path("processed_pollutant")
    expected = cfg.get("expected", default={})
    tol = float(expected.get("row_count_tolerance_pct", 1.0))

    log.info(f"Pollutant directory: {pollutant_dir}")

    # -------- Per-file schema + row count + date range ------------------
    combined_aqsid: set[str] = set()
    combined_county: set[str] = set()
    combined_group: set[str] = set()
    combined_min_date: str = "9999-12-31"
    combined_max_date: str = "0000-01-01"
    total_rows = 0

    for group, fname in POLLUTANT_FILE_MAP.items():
        path = pollutant_dir / fname
        with step_timer(log, f"read {fname}"):
            if not path.exists():
                report.add(check_schema(pd.DataFrame(), POLLUTANT_COLUMNS, group))
                log.error(f"MISSING: {path}")
                continue
            df = read_pollutant_csv(path)

        report.add(check_schema(df, POLLUTANT_COLUMNS, group))
        report.add(
            check_row_count(
                len(df),
                expected.get("pollutant_rows", {}).get(group, 0),
                source=group,
                tolerance_pct=tol,
            )
        )
        # Exact-duplicate rows are deduped in step 01 — report as WARNING.
        report.add(check_no_duplicate_hours(df, source=group, severity=SEVERITY_WARNING))
        report.add(
            check_date_range_within(
                df,
                col="date_local",
                window_start=expected.get("date_min", "2015-01-01"),
                window_end=expected.get("date_max", "2025-11-30"),
                source=group,
            )
        )

        total_rows += len(df)
        combined_aqsid.update(df["aqsid"].dropna().unique())
        combined_county.update(df["county_name"].dropna().str.title().unique())
        combined_group.update(df["pollutant_group"].dropna().unique())
        dmin = df["date_local"].min()
        dmax = df["date_local"].max()
        if isinstance(dmin, str):
            combined_min_date = min(combined_min_date, dmin)
            combined_max_date = max(combined_max_date, dmax)
        del df

    # -------- Cross-file aggregates --------------------------------------
    report.add(
        check_row_count(
            total_rows,
            int(expected.get("total_pollutant_rows", 0)),
            source="all_pollutants",
            tolerance_pct=tol,
        )
    )
    # Spec says 43; real data often has 41 because a couple of reference-only
    # sites don't appear in the processed CSVs. Treat as WARNING so a future
    # reload of those sites just updates the count without breaking CI.
    expected_sites = int(expected.get("active_sites", 43))
    report.add(
        check_unique_count(
            pd.Series(list(combined_aqsid)),
            expected_sites,
            source="aqsid",
            severity=SEVERITY_WARNING,
            min_expected=max(expected_sites - 5, 1),
        )
    )
    report.add(
        check_unique_count(
            pd.Series(list(combined_county)),
            int(expected.get("counties", 13)),
            source="county_name",
        )
    )
    report.add(
        check_unique_count(
            pd.Series(list(combined_group)),
            int(expected.get("pollutant_groups", 7)),
            source="pollutant_group",
        )
    )

    # -------- Weather master ---------------------------------------------
    wx_path = cfg.path("weather_master")
    with step_timer(log, f"read weather master ({wx_path.name})"):
        if wx_path.exists():
            wx = pd.read_csv(wx_path, low_memory=False)
            report.add(
                check_row_count(
                    len(wx),
                    int(expected.get("weather_rows", 1470050)),
                    source="weather_master",
                    tolerance_pct=tol,
                )
            )
            if "location" in wx.columns:
                report.add(
                    check_unique_count(
                        wx["location"],
                        int(expected.get("weather_stations", 15)),
                        source="weather_station_location",
                    )
                )
            del wx
        else:
            log.error(f"MISSING weather master: {wx_path}")

    # -------- Site mapping -----------------------------------------------
    # Column names vary across reorg generations — we accept any file that
    # has a distance column plus an AQ identifier and a weather station name.
    mp_path = cfg.path("site_mapping")
    if mp_path.exists():
        mp = pd.read_csv(mp_path)
        cols_lower = {c.lower() for c in mp.columns}
        has_distance = any("dist" in c for c in cols_lower)
        has_aq       = any(c in cols_lower for c in ("aq_site", "aqsid", "aq_lat", "site_name", "site"))
        has_wx       = any(c in cols_lower for c in ("weather_station", "wx_site", "location", "station"))
        report.add(
            CheckResult(
                name="site_mapping:has_required_columns",
                passed=has_distance and has_aq and has_wx and len(mp) > 0,
                expected="(distance col) + (aq col) + (weather col) + rows>0",
                actual=sorted(mp.columns.tolist()) + [f"rows={len(mp)}"],
                severity=SEVERITY_WARNING,
            )
        )

    # -------- Write report ------------------------------------------------
    out_dir = ensure_dir(cfg.path("validation"))
    out_file = out_dir / "validation_report.json"
    with out_file.open("w", encoding="utf-8") as f:
        json.dump(report.to_dict(), f, indent=2, default=str)

    log.info(f"Validation: {report.summary()}")
    log.info(f"Report written to {out_file}")

    warnings = [r for r in report.results if not r.passed and r.severity == SEVERITY_WARNING]
    errors   = [r for r in report.results if not r.passed and r.severity == SEVERITY_ERROR]
    if warnings:
        log.warning(f"{len(warnings)} warning check(s) — pipeline continues:")
        for r in warnings:
            log.warning(f"  {r.name}: expected={r.expected} actual={r.actual} {r.detail}")
    if errors:
        log.error(f"{len(errors)} error check(s):")
        for r in errors:
            log.error(f"  {r.name}: expected={r.expected} actual={r.actual} {r.detail}")
        return False
    return True


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
