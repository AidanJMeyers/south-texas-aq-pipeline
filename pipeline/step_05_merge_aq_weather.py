"""Step 05 — Merge AQ with paired weather.

Produces the single daily-resolution combined dataset used by downstream
analysis (correlation, regression, ML).

The existing ``AQ_Weather_SiteMapping.csv`` is keyed by raw lat/lon tuples,
not by AQ site ID, so it can't be joined directly. Instead this step:

1. Loads authoritative site coordinates from
   ``01_Data/Reference/enhanced_monitoring_sites.csv``
   (29 sites with verified lat/lon).
2. Derives weather station coordinates by taking the first lat/lon row per
   station from the weather parquet store.
3. Computes a per-aqsid nearest-weather pairing by Haversine distance.
4. For any AQ site *without* confirmed coordinates, falls back to a
   county-name match against weather station names.
5. Joins the daily pollutant table to its paired station's daily weather.

Inputs:
    data/parquet/daily/pollutant_daily.parquet
    data/parquet/weather/
    01_Data/Reference/enhanced_monitoring_sites.csv

Outputs:
    data/parquet/combined/aq_weather_daily.parquet
    data/csv/combined_aq_weather_daily.csv
    data/csv/site_registry.csv
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from pipeline.utils.io import (
    PipelineConfig,
    ensure_dir,
    load_config,
    read_parquet_dataset,
    write_csv,
)
from pipeline.utils.logging import get_logger, step_timer
from pipeline.utils.site_lookup import build_site_registry


DAILY_WEATHER_AGGS = {
    "temp_c":        ["mean", "min", "max"],
    "feels_like_c":  ["mean"],
    "dew_point_c":   ["mean"],
    "humidity":      ["mean", "min", "max"],
    "pressure":      ["mean"],
    "wind_speed":    ["mean", "max"],
    "wind_u":        ["mean"],
    "wind_v":        ["mean"],
    "wind_gust":     ["max"],
    "clouds_all":    ["mean"],
    "visibility":    ["mean"],
    "rain_1h":       ["sum"],
    "ghi_cloudy_sky": ["sum"],
    "ghi_clear_sky":  ["sum"],
    "heat_index_c":  ["max"],
}


# ---------------------------------------------------------------------------
# Geospatial + pairing helpers
# ---------------------------------------------------------------------------
def _haversine_km(lat1, lon1, lat2, lon2) -> np.ndarray:
    """Broadcast-able Haversine distance in km."""
    R = 6371.0088
    p1, p2 = np.deg2rad(lat1), np.deg2rad(lat2)
    dp = p2 - p1
    dl = np.deg2rad(lon2) - np.deg2rad(lon1)
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * R * np.arcsin(np.sqrt(a))


def _weather_station_coords(wx: pd.DataFrame) -> pd.DataFrame:
    """One (location, lat, lon) row per weather station."""
    cols = [c for c in ("location", "lat", "lon") if c in wx.columns]
    if "lat" not in cols or "lon" not in cols:
        raise KeyError("Weather parquet missing lat/lon columns")
    return (
        wx[cols]
        .dropna(subset=["lat", "lon"])
        .drop_duplicates("location")
        .reset_index(drop=True)
    )


def _nearest_station(
    sites: pd.DataFrame,  # aqsid, lat, lon, county_name
    stations: pd.DataFrame,  # location, lat, lon
) -> pd.DataFrame:
    """For each site row, add the nearest weather station + distance_km."""
    slat = sites["lat"].to_numpy()[:, None]
    slon = sites["lon"].to_numpy()[:, None]
    wlat = stations["lat"].to_numpy()[None, :]
    wlon = stations["lon"].to_numpy()[None, :]
    dists = _haversine_km(slat, slon, wlat, wlon)
    idx = np.argmin(dists, axis=1)
    sites = sites.copy()
    sites["weather_station"] = stations["location"].iloc[idx].to_numpy()
    sites["distance_km"] = dists[np.arange(len(sites)), idx]
    return sites


def _county_fallback(unmatched_counties: list[str], stations: pd.DataFrame) -> dict:
    """Pick a default weather station per county by substring match."""
    out: dict[str, str] = {}
    for c in unmatched_counties:
        needle = c.lower()
        hits = [s for s in stations["location"] if needle in s.lower()]
        if hits:
            out[c] = hits[0]
    return out


def _daily_weather(wx: pd.DataFrame) -> pd.DataFrame:
    """Collapse hourly weather to daily per station."""
    wx = wx.copy()
    if "date_local" not in wx.columns:
        if "datetime_local" in wx.columns:
            wx["date_local"] = pd.to_datetime(wx["datetime_local"]).dt.strftime("%Y-%m-%d")
        elif "dt" in wx.columns:
            wx["date_local"] = pd.to_datetime(wx["dt"], unit="s").dt.strftime("%Y-%m-%d")
        else:
            raise KeyError("Weather parquet missing datetime columns")
    else:
        wx["date_local"] = wx["date_local"].astype(str).str.slice(0, 10)

    present = {c: aggs for c, aggs in DAILY_WEATHER_AGGS.items() if c in wx.columns}
    grouped = wx.groupby(["location", "date_local"]).agg(present)
    grouped.columns = [f"{c}_{a}" if a != "mean" else c for c, a in grouped.columns]
    return grouped.reset_index().rename(columns={"location": "weather_station"})


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(cfg: PipelineConfig | None = None) -> bool:
    cfg = cfg or load_config()
    log = get_logger("05_merge_aq_weather", log_dir=cfg.path("logs"))

    daily_path = cfg.path("parquet_daily") / "pollutant_daily.parquet"
    if not daily_path.exists():
        log.error(f"Missing daily pollutant file: {daily_path}  (run step 04 first)")
        return False

    wx_pq = cfg.path("parquet_weather")
    if not wx_pq.exists():
        log.error(f"Missing weather parquet store: {wx_pq}  (run step 02 first)")
        return False

    ref_path = cfg.path("site_reference")
    if not ref_path.exists():
        log.error(f"Missing site reference: {ref_path}")
        return False

    tceq_xlsx = cfg.path("tceq_registry")

    with step_timer(log, "load inputs"):
        daily = pd.read_parquet(daily_path)
        wx = read_parquet_dataset(wx_pq)
        ref = pd.read_csv(ref_path, dtype={"aqsid": str})
    log.info(f"  daily rows:    {len(daily):,}")
    log.info(f"  weather rows:  {len(wx):,}")
    log.info(f"  reference CSV: {len(ref)} sites with coords")

    # Union the reference CSV with the Extra TCEQ Sites workbook so we have
    # coordinates for the TCEQ-only sites that aren't in the enhanced CSV.
    ref_keep_csv = ref[["aqsid", "latitude", "longitude"]].rename(
        columns={"latitude": "lat", "longitude": "lon"}
    )
    tceq_coords: pd.DataFrame | None = None
    if tceq_xlsx.exists():
        try:
            tceq_df = pd.read_excel(tceq_xlsx, sheet_name="Missing Sites")
            tceq_df["aqsid"] = tceq_df["AQS Site ID"].astype(str)
            tceq_coords = tceq_df[["aqsid", "Latitude", "Longitude"]].rename(
                columns={"Latitude": "lat", "Longitude": "lon"}
            )
            log.info(f"  TCEQ workbook: {len(tceq_coords)} sites with coords")
        except Exception as e:
            log.warning(f"  could not read TCEQ workbook: {e}")

    if tceq_coords is not None:
        # CSV wins when both sources have a site (CSV is the AQS-verified one)
        combined_ref = (
            pd.concat([ref_keep_csv, tceq_coords], ignore_index=True)
            .drop_duplicates(subset=["aqsid"], keep="first")
        )
    else:
        combined_ref = ref_keep_csv
    ref_keep = combined_ref
    log.info(f"  merged coord lookup: {len(ref_keep)} unique aqsids")

    # Build site→station mapping
    with step_timer(log, "build site↔weather pairing"):
        stations = _weather_station_coords(wx)
        log.info(f"  weather stations with coords: {len(stations)}")

        # Unique site list from the daily table
        site_list = (
            daily.groupby("aqsid", dropna=False)
            .agg(site_name=("site_name", "first"), county_name=("county_name", "first"))
            .reset_index()
        )

        # Attach coordinates from the merged lookup (CSV + xlsx)
        site_list = site_list.merge(ref_keep, on="aqsid", how="left")

        with_coords = site_list.dropna(subset=["lat", "lon"]).copy()
        without = site_list[site_list["lat"].isna()].copy()

        paired_coords = _nearest_station(with_coords, stations)

        # County-name fallback for uncoordinated sites
        fallback = _county_fallback(
            sorted(without["county_name"].dropna().unique().tolist()),
            stations,
        )
        without["weather_station"] = without["county_name"].map(fallback)
        without["distance_km"] = np.nan

        site_pairing = pd.concat(
            [paired_coords, without],
            ignore_index=True,
        )[["aqsid", "site_name", "county_name", "weather_station", "distance_km"]]

        n_paired = site_pairing["weather_station"].notna().sum()
        log.info(
            f"  sites paired: {n_paired}/{len(site_pairing)} "
            f"(coord-match={len(with_coords)}, county-fallback={without['weather_station'].notna().sum()})"
        )

    with step_timer(log, "collapse weather to daily"):
        wx_daily = _daily_weather(wx)
    log.info(f"  weather daily rows: {len(wx_daily):,}")

    with step_timer(log, "join AQ + weather"):
        daily_keyed = daily.merge(
            site_pairing[["aqsid", "weather_station", "distance_km"]],
            on="aqsid",
            how="left",
        )
        missing = daily_keyed["weather_station"].isna().sum()
        if missing:
            log.warning(f"  {missing:,} daily rows have no weather pairing (dropped)")
        combined = daily_keyed.dropna(subset=["weather_station"]).merge(
            wx_daily, on=["weather_station", "date_local"], how="left"
        )
    log.info(f"  combined rows: {len(combined):,}")

    # Outputs
    out_pq = ensure_dir(cfg.path("parquet_combined"))
    combined.to_parquet(out_pq / "aq_weather_daily.parquet", index=False)
    write_csv(combined, cfg.path("csv_exports") / "combined_aq_weather_daily.csv")

    with step_timer(log, "build site registry"):
        registry = build_site_registry(cfg)
    write_csv(registry, cfg.path("csv_exports") / "site_registry.csv")
    log.info(f"  site registry: {len(registry)} sites written")

    log.info("Merge complete.")
    return True


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
