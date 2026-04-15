"""NAAQS design value computations.

Each function takes a **hourly** ``pd.Series`` indexed by a ``DatetimeIndex``
(tz-naive, local time) for a single site-parameter and returns a per-year
``pd.Series`` keyed by ``year``. This keeps the functions pure and testable.

NAAQS definitions (40 CFR Part 50):
    * Ozone 8-hr:  4th-highest daily max 8-hr rolling avg per year, then
                   averaged over 3 years → compare to 0.070 ppm
    * PM2.5 annual: annual mean of daily means, 3-yr average → 9.0 µg/m³
    * PM2.5 24-hr:  98th percentile of daily means per year, 3-yr average → 35 µg/m³
    * PM10 24-hr:   daily mean not to exceed 150 µg/m³ more than once per year
    * CO 8-hr:      8-hr rolling max not to exceed 9 ppm more than 1x/yr
    * CO 1-hr:      hourly max not to exceed 35 ppm more than 1x/yr
    * SO2 1-hr:     99th percentile of daily max 1-hr, 3-yr average → 75 ppb
    * NO2 1-hr:     98th percentile of daily max 1-hr, 3-yr average → 100 ppb
    * NO2 annual:   annual mean → 53 ppb

Completeness rules (75% rule):
    * 8-hr O3 rolling avg needs ≥ 6 of 8 hours
    * Daily mean needs ≥ 18 of 24 hours
    * This module's functions accept ``min_hours_per_day`` / ``min_hours_per_8hr``
      parameters that default to these values.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------
def _require_datetime_index(s: pd.Series) -> pd.Series:
    if not isinstance(s.index, pd.DatetimeIndex):
        raise TypeError(
            f"NAAQS functions require a DatetimeIndex; got {type(s.index).__name__}"
        )
    return s.sort_index()


def _daily_mean(s: pd.Series, min_hours: int = 18) -> pd.Series:
    """Daily mean with 75% completeness rule."""
    s = _require_datetime_index(s)
    g = s.resample("D")
    means = g.mean()
    counts = g.count()
    means[counts < min_hours] = np.nan
    return means


def _daily_max(s: pd.Series, min_hours: int = 18) -> pd.Series:
    """Daily max with 75% completeness rule."""
    s = _require_datetime_index(s)
    g = s.resample("D")
    maxes = g.max()
    counts = g.count()
    maxes[counts < min_hours] = np.nan
    return maxes


def rolling_8hr_mean(s: pd.Series, min_hours: int = 6) -> pd.Series:
    """8-hour trailing rolling mean with 75% completeness rule.

    Ozone 8-hr averages are labeled by the **start** hour of the window in
    EPA guidance, but pandas rolling is right-labeled. We keep the
    right-labeled result for consistency with pandas conventions — the
    daily-max aggregation that follows is invariant to the label choice.
    """
    s = _require_datetime_index(s)
    return s.rolling(window=8, min_periods=min_hours).mean()


# ---------------------------------------------------------------------------
# Per-pollutant design values
# ---------------------------------------------------------------------------
def ozone_8hr_4th_max(hourly_ppm: pd.Series, min_hours_8hr: int = 6) -> pd.Series:
    """Ozone 8-hr NAAQS metric: 4th-highest daily max 8-hr avg per year (ppm).

    Returns a Series indexed by year.
    """
    r8 = rolling_8hr_mean(hourly_ppm, min_hours=min_hours_8hr)
    daily_max_8hr = r8.resample("D").max()
    years = daily_max_8hr.index.year
    out: dict[int, float] = {}
    for yr, grp in daily_max_8hr.groupby(years):
        vals = grp.dropna().sort_values(ascending=False)
        out[int(yr)] = float(vals.iloc[3]) if len(vals) >= 4 else float("nan")
    return pd.Series(out, name="ozone_8hr_4th_max")


def pm_annual_mean(hourly: pd.Series, min_hours_daily: int = 18) -> pd.Series:
    """Annual mean of daily means (PM2.5, NO2 annual, etc.)."""
    daily = _daily_mean(hourly, min_hours=min_hours_daily)
    return daily.groupby(daily.index.year).mean().rename("annual_mean")


def pm25_24hr_p98(hourly_ugm3: pd.Series, min_hours_daily: int = 18) -> pd.Series:
    """PM2.5 24-hr NAAQS: 98th percentile of daily means per year (µg/m³)."""
    daily = _daily_mean(hourly_ugm3, min_hours=min_hours_daily)
    return (
        daily.groupby(daily.index.year)
        .quantile(0.98)
        .rename("pm25_24hr_p98")
    )


def pm10_24hr_exceedances(
    hourly_ugm3: pd.Series,
    level: float = 150.0,
    min_hours_daily: int = 18,
) -> pd.Series:
    """PM10 24-hr NAAQS: count of daily means exceeding ``level`` per year."""
    daily = _daily_mean(hourly_ugm3, min_hours=min_hours_daily)
    exceedances = (daily > level).astype(int)
    return (
        exceedances.groupby(exceedances.index.year)
        .sum()
        .rename("pm10_24hr_exceedances")
    )


def co_8hr_max(hourly_ppm: pd.Series, min_hours_8hr: int = 6) -> pd.Series:
    """CO 8-hr NAAQS metric: annual max of 8-hr rolling means (ppm)."""
    r8 = rolling_8hr_mean(hourly_ppm, min_hours=min_hours_8hr)
    return r8.groupby(r8.index.year).max().rename("co_8hr_max")


def co_1hr_max(hourly_ppm: pd.Series) -> pd.Series:
    """CO 1-hr NAAQS metric: annual max hourly value (ppm)."""
    s = _require_datetime_index(hourly_ppm)
    return s.groupby(s.index.year).max().rename("co_1hr_max")


def so2_1hr_p99(hourly_ppb: pd.Series, min_hours_daily: int = 18) -> pd.Series:
    """SO2 1-hr NAAQS: 99th percentile of daily max 1-hr values per year (ppb)."""
    daily_max = _daily_max(hourly_ppb, min_hours=min_hours_daily)
    return (
        daily_max.groupby(daily_max.index.year)
        .quantile(0.99)
        .rename("so2_1hr_p99")
    )


def no2_1hr_p98(hourly_ppb: pd.Series, min_hours_daily: int = 18) -> pd.Series:
    """NO2 1-hr NAAQS: 98th percentile of daily max 1-hr values per year (ppb)."""
    daily_max = _daily_max(hourly_ppb, min_hours=min_hours_daily)
    return (
        daily_max.groupby(daily_max.index.year)
        .quantile(0.98)
        .rename("no2_1hr_p98")
    )


def no2_annual_mean(hourly_ppb: pd.Series, min_hours_daily: int = 18) -> pd.Series:
    """NO2 annual NAAQS: annual mean of hourly values (ppb)."""
    return pm_annual_mean(hourly_ppb, min_hours_daily=min_hours_daily).rename("no2_annual_mean")


# ---------------------------------------------------------------------------
# Dispatcher: map pollutant group → applicable metrics
# ---------------------------------------------------------------------------
METRIC_DISPATCH: dict[str, list[tuple[str, callable, str, float | None]]] = {
    # Each tuple: (metric_name, function, units, standard_level_or_None)
    "Ozone": [
        ("ozone_8hr_4th_max", ozone_8hr_4th_max, "ppm", 0.070),
    ],
    "PM2.5": [
        ("pm25_annual_mean",  pm_annual_mean,    "ug/m3", 9.0),
        ("pm25_24hr_p98",     pm25_24hr_p98,     "ug/m3", 35.0),
    ],
    "PM10": [
        ("pm10_24hr_exceedances", pm10_24hr_exceedances, "count", None),
    ],
    "CO": [
        ("co_8hr_max", co_8hr_max, "ppm", 9.0),
        ("co_1hr_max", co_1hr_max, "ppm", 35.0),
    ],
    "SO2": [
        ("so2_1hr_p99", so2_1hr_p99, "ppb", 75.0),
    ],
    "NOx_Family": [
        # NO2 metrics only — applied to rows where parameter_code == 42602 (NO2)
        ("no2_1hr_p98",      no2_1hr_p98,     "ppb", 100.0),
        ("no2_annual_mean",  no2_annual_mean, "ppb", 53.0),
    ],
}
