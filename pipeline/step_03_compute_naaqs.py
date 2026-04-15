"""Step 03 — Compute NAAQS design values.

For every (site, year) combination, compute the applicable NAAQS design
values using the pure functions in ``pipeline.utils.naaqs``. The result is
a long-format table with one row per (aqsid, year, metric) plus the raw
value, NAAQS standard level, and an ``exceeds`` boolean.

This is the highest-value missing piece — before this step, the project had
NO proper design value computation, only threshold screening.

Inputs:
    data/parquet/pollutants/

Outputs:
    data/parquet/naaqs/design_values.parquet
    data/csv/naaqs_design_values.csv

Runtime: ~2–4 minutes.
"""

from __future__ import annotations

import sys

import pandas as pd

from pipeline.utils.io import (
    PipelineConfig,
    ensure_dir,
    load_config,
    read_parquet_dataset,
    write_csv,
    write_parquet_partitioned,
)
from pipeline.utils.logging import get_logger, step_timer
from pipeline.utils.naaqs import METRIC_DISPATCH


# NO2 within the NOx_Family pollutant group is parameter_code 42602
NO2_PARAMETER_CODE = 42602


def _site_timeseries(df: pd.DataFrame) -> pd.Series:
    """Pivot a per-site subset to a DatetimeIndex'd hourly Series."""
    s = df.set_index("datetime")["sample_measurement"].sort_index()
    # Some sites have multiple POCs running simultaneously — average across
    # POCs at the same timestamp so downstream rolling windows work cleanly.
    if s.index.duplicated().any():
        s = s.groupby(level=0).mean()
    return s


def _compute_group(
    pollutant_group: str,
    df: pd.DataFrame,
    cfg: PipelineConfig,
) -> pd.DataFrame:
    """Apply all metrics for ``pollutant_group`` to every site in ``df``."""
    rows: list[dict] = []
    dq = cfg.get("data_quality", default={})
    min_hours_daily = int(dq.get("pm_daily_min_hours", 18))
    min_hours_8hr   = int(dq.get("ozone_8hr_min_hours", 6))

    metrics = METRIC_DISPATCH.get(pollutant_group, [])
    if not metrics:
        return pd.DataFrame()

    # For NOx_Family we restrict to the NO2 parameter only
    if pollutant_group == "NOx_Family":
        df = df[df["parameter_code"] == NO2_PARAMETER_CODE]

    for aqsid, site_df in df.groupby("aqsid"):
        series = _site_timeseries(site_df)
        for metric_name, func, units, standard in metrics:
            # Dispatch functions take different keyword args; use try/except
            # to cover the 8-hr vs daily completeness variants.
            try:
                if metric_name.endswith("_8hr_4th_max") or metric_name == "co_8hr_max":
                    out = func(series, min_hours_8hr=min_hours_8hr)
                elif metric_name == "co_1hr_max":
                    out = func(series)
                else:
                    out = func(series, min_hours_daily=min_hours_daily)
            except TypeError:
                out = func(series)

            for year, value in out.items():
                if pd.isna(value):
                    continue
                rows.append({
                    "aqsid": aqsid,
                    "year": int(year),
                    "pollutant_group": pollutant_group,
                    "metric": metric_name,
                    "value": float(value),
                    "units": units,
                    "naaqs_level": standard,
                    "exceeds": bool(standard is not None and value > standard),
                    "site_name": site_df["site_name"].iloc[0] if "site_name" in site_df else "",
                    "county_name": site_df["county_name"].iloc[0] if "county_name" in site_df else "",
                })
    return pd.DataFrame(rows)


def main(cfg: PipelineConfig | None = None) -> bool:
    cfg = cfg or load_config()
    log = get_logger("03_compute_naaqs", log_dir=cfg.path("logs"))

    pq_pollutants = cfg.path("parquet_pollutants")
    if not pq_pollutants.exists():
        log.error(f"Pollutant parquet store not found: {pq_pollutants}  (run step 01 first)")
        return False

    frames: list[pd.DataFrame] = []
    for group in METRIC_DISPATCH.keys():
        with step_timer(log, f"compute NAAQS for {group}"):
            df = read_parquet_dataset(
                pq_pollutants,
                columns=[
                    "aqsid", "datetime", "sample_measurement",
                    "parameter_code", "site_name", "county_name",
                ],
                filters=[("pollutant_group", "=", group)],
            )
            if df.empty:
                log.warning(f"  no data for {group}; skipping")
                continue
            result = _compute_group(group, df, cfg)
            log.info(f"  {group}: {len(result)} design-value rows")
            frames.append(result)

    if not frames:
        log.error("No design values computed.")
        return False

    dv = pd.concat(frames, ignore_index=True)
    dv = dv.sort_values(["pollutant_group", "aqsid", "year", "metric"]).reset_index(drop=True)

    # Write parquet + flat CSV
    out_pq = ensure_dir(cfg.path("parquet_naaqs"))
    dv.to_parquet(out_pq / "design_values.parquet", index=False)
    csv_out = cfg.path("csv_exports") / "naaqs_design_values.csv"
    write_csv(dv, csv_out)

    log.info(
        f"Design values: {len(dv):,} rows  "
        f"({dv['aqsid'].nunique()} sites × "
        f"{dv['year'].nunique()} years × "
        f"{dv['metric'].nunique()} metrics)"
    )
    log.info(f"  parquet: {out_pq / 'design_values.parquet'}")
    log.info(f"  csv:     {csv_out}")
    return True


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
