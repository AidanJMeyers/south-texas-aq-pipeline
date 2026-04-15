# 01 — Project Overview

## Mission

Characterize ambient air quality in 13 South Texas counties from 2015 through
2025, identify weather-driven pollutant patterns, and build the data
foundation for spatial interpolation models that extend monitored estimates
into unmonitored areas.

## Study area

**13 counties**, 47 monitoring sites (41 active), 15 weather stations.

| County | MSA / Region | Active AQ Sites | Weather Stations |
|---|---|---:|---:|
| Atascosa | San Antonio–New Braunfels, TX | 1 | — |
| Bexar | San Antonio–New Braunfels, TX | 19 | 5 |
| Cameron | Brownsville–Harlingen, TX | 2 | 1 |
| Comal | San Antonio–New Braunfels, TX | 3 | 1 |
| Guadalupe | San Antonio–New Braunfels, TX | 2 | 1 |
| Hidalgo | McAllen–Edinburg–Mission, TX | 2 | 1 |
| Karnes | (non-MSA) | 1 | — |
| Kleberg | (non-MSA) | 1 | 1 |
| Maverick | (non-MSA) | 1 | — |
| Nueces | Corpus Christi, TX | 7 | 3 |
| Victoria | Victoria, TX | 1 | 1 |
| Webb | Laredo, TX | 2 | 1 |
| Wilson | San Antonio–New Braunfels, TX | 1 | — |

Counts reflect the post-pipeline state (April 2026). Some counties rely on
their nearest neighbor's weather station via Haversine pairing (see
[methodology](./05_methodology.md)).

## Pollutants measured

| Group | Parameters | Unit (normalized) | Source networks |
|---|---|---|---|
| Ozone (O₃) | 44201 | ppm | EPA + TCEQ |
| NOx family | 42601 (NO), 42602 (NO₂), 42603 (NOx) | ppb | EPA + TCEQ |
| CO | 42101 | ppm | EPA |
| SO₂ | 42401 | ppb | EPA + TCEQ |
| PM₂.₅ | 88101, 88500, 88502 | µg/m³ | EPA + TCEQ |
| PM₁₀ | 81102, 85101 | µg/m³ | EPA |
| VOCs | 43xxx, 45xxx (individual species) | ppbC | TCEQ (Hillcrest only) |

All pollutant values in the pipeline output are normalized to the **EPA unit
convention** — see [methodology §Unit normalization](./05_methodology.md#unit-normalization).

## Weather and irradiance variables

Hourly observations from **15 OpenWeather stations** covering 2015–2025:

- Air temperature, feels-like, dew point (°C — converted if source was Kelvin)
- Relative humidity (%)
- Station pressure (hPa)
- Wind speed, gust, direction (m/s, degrees)
- Wind u/v components (m/s) for kriging
- Cloud cover (%), visibility (m), precipitation (mm)
- GHI, DNI, DHI — clear-sky and all-sky (W/m²)
- Heat index (°C, Rothfusz when applicable)

## Deliverables

The pipeline produces four tiers of output (see [architecture](./04_pipeline_architecture.md)):

1. **Raw-preserved parquet store** — 4.87M pollutant hourly + 1.47M weather hourly rows
2. **NAAQS design values** — 764 rows × 9 metrics × 40 sites × 11 years
3. **Daily aggregates** — 236k site-day-parameter rows with completeness flags
4. **AQ + weather combined** — 236k rows joined to paired daily weather

All outputs exist as:
- **Parquet** — fast local analytics (primary)
- **Flat CSV** — for R/Colab users without Arrow
- **Postgres (Neon)** — for SQL + BI tool access (analysis-ready tables only)
- **R `.rds`** — optional, for R-native pipelines

## Intended users

1. **Lab researchers** — hourly-resolution analysis in R notebooks
2. **Students / collaborators** — SQL queries against Neon, daily-resolution
3. **Manuscript authors** — NAAQS design value tables, time series plots
4. **Spatial modelers** — Kriging inputs with `distance_km` weighting

## Not in scope (yet)

- Spatial interpolation / kriging surfaces (user-led, downstream of this pipeline)
- Predictive models for unmonitored areas (downstream)
- Refactored R notebooks loading from `data/parquet/` (follow-up work)
- Coordinates and data for 2 pending VOC sites (awaits TCEQ TAMIS download)
