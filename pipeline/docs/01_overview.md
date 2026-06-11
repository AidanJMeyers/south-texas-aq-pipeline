# 01 — Project Overview

> **v0.4.0 (2026-05-28):** This page reflects the TCEQ-only architecture.
> Site counts and pollutant coverage updated. For the full rationale, see
> the [v0.4.0 migration guide](./v0_4_0_migration.md).

## Mission

Characterize ambient air quality in 13 South Texas counties from 2015 through
2025, identify weather-driven pollutant patterns, and build the data
foundation for spatial interpolation models that extend monitored estimates
into unmonitored areas.

## Study area

**13 counties**, **42 monitoring sites in the registry** (41 active with data
+ 1 disabled Williams Park retained for historical record), **15 weather
stations** (OpenWeather + Solcast).

| County | MSA / Region | Active AQ Sites | Weather Stations |
|---|---|---:|---:|
| Atascosa | San Antonio–New Braunfels, TX | 1 | — |
| Bexar | San Antonio–New Braunfels, TX | 14 | 5 |
| Cameron | Brownsville–Harlingen, TX | 3 | 1 |
| Comal | San Antonio–New Braunfels, TX | 3 | 1 |
| Guadalupe | San Antonio–New Braunfels, TX | 2 | 1 |
| Hidalgo | McAllen–Edinburg–Mission, TX | 2 | 1 |
| Karnes | (non-MSA) | 1 | — |
| Kleberg | (non-MSA) | 1 | 1 |
| Maverick | (non-MSA) | 1 | — |
| Nueces | Corpus Christi, TX | 7 | 3 |
| Victoria | Victoria, TX | 1 | 1 |
| Webb | Laredo, TX | 3 | 1 |
| Wilson | San Antonio–New Braunfels, TX | 1 | — |

Counts reflect the v0.4.0 state (2026-05-28). The Bexar count dropped from
v0.3.7 (19) to v0.4.0 (14) because the 4 TSP-only CPS fence-line sites
(480290623, 480290625, 480290626, 480291609) and Von Ormy 480291097 (not
in the 2026-05-21 TCEQ pull) are excluded.

## Pollutants measured

All data comes from a **single source: TCEQ TAMIS** (2026-05-21 pull).
EPA AQS API integration was retired in v0.4.0.

### Criteria pollutants (9 AQS codes, 6 pollutant groups)

| Group | Parameters | Native unit | Canonical unit | Storage |
|---|---|---|---|---|
| Ozone (O₃) | 44201 | ppb (TCEQ) | **ppm** (× 0.001 at ingest) | `aq.pollutant_hourly` |
| NOx family | 42601 (NO), 42602 (NO₂), 42603 (NOx) | ppb | ppb | `aq.pollutant_hourly` |
| CO | 42101 | ppm | ppm | `aq.pollutant_hourly` |
| SO₂ | 42401 | ppb | ppb | `aq.pollutant_hourly` |
| PM₂.₅ | 88101 (FRM/FEM), 88502 (any method) | µg/m³ | µg/m³ | `aq.pollutant_hourly` |
| PM₁₀ | 81102 | µg/m³ | µg/m³ | `aq.pollutant_hourly` or `aq.pollutant_daily_24hr` (site 0060) |

### Volatile organic compounds (47 AQS codes, 4 chemical families)

VOCs live in separate tables (`aq.vocs_1hr`, `aq.vocs_24hr`) — NOT in
`pollutant_hourly`. Of the 47 species, **10 are HAPs** (Hazardous Air
Pollutants under Clean Air Act §112(b)).

| Family | Count | Examples | HAPs |
|---|---:|---|---|
| Paraffins (alkanes, C₂–C₁₁) | 21 | Ethane (43202), n-Butane (43212), n-Hexane (43231) | n-Hexane, 2,2,4-Trimethylpentane |
| Cycloalkanes | 4 | Cyclopentane (43242), Cyclohexane (43248) | — |
| Olefins (alkenes/dienes/alkynes) | 12 | Ethylene (43203), Isoprene (43243), 1,3-Butadiene (43218) | 1,3-Butadiene |
| Aromatics (BTEX and beyond) | 11 | Benzene (45201), Toluene (45202), m/p-Xylene (45109) | Benzene, Toluene, Ethylbenzene, Xylenes, Isopropylbenzene, Styrene |

The full parameter reference (with `chemical_family`, `pollutant_group`,
`default_units`, `naaqs_regulated`, `is_hap` flags) lives at:

- `aq.parameter_reference` table on Neon
- [`parameter_reference.md`](https://github.com/AidanJMeyers/south-texas-aq-pipeline/blob/main/!Archive_v0_3_7/inventory/parameter_reference.md) on GitHub (local-only)

All values are normalized to the canonical EPA unit convention at ingestion
(step 01b). See [methodology §1](./05_methodology.md#1-unit-normalization).

## Weather and irradiance variables

Hourly observations from **15 weather stations** covering 2015–2025
(OpenWeather One Call API + Solcast irradiance):

- Air temperature, feels-like, dew point (°C — converted from Kelvin if needed)
- Relative humidity (%), station pressure (hPa)
- Wind speed, gust, direction (m/s, degrees)
- Wind u/v components (m/s) for kriging
- Cloud cover (%), visibility (m), precipitation (mm)
- GHI / DNI / DHI — clear-sky and cloudy-sky (W/m²)
- Heat index (°C, Rothfusz when applicable)

Weather data is **unchanged in v0.4.0** — the EPA→TCEQ migration only
touched the pollutant side.

## Deliverables

The pipeline produces five tiers of output (see [architecture](./04_pipeline_architecture.md)
and [Colab + Neon DB guide](./17_colab_database_guide.md)):

1. **Partitioned parquet stores** (7 stores, ~10.7M rows):
   `data/parquet/{pollutants,vocs_1hr,vocs_24hr,pollutant_daily_24hr,weather,naaqs,daily}/`
2. **NAAQS design values** — 759 rows × 9 metrics × 39 sites × 11 years
3. **Daily + monthly aggregates** — 201,290 + 6,804 rows with completeness flags
4. **Flat CSV exports** — `data/csv/` for R / Colab users without Arrow
5. **Postgres (Neon) — 10 analysis-ready tables in `aq` schema**, ~11.5M rows / ~2.4 GB

Historical v0.3.7 EPA-blended data is preserved indefinitely as
`aq_v0_3_7_epa.*` (7 tables, ~2.2 GB) for fallback queries and rollback.

## Intended users

1. **Lab researchers** — hourly-resolution analysis in R notebooks
2. **Students / collaborators** — SQL queries against Neon, daily-resolution
3. **Manuscript authors** — NAAQS design value tables, time series plots
4. **Spatial modelers** — Kriging inputs with `distance_km` weighting

## Not in scope (yet)

- Spatial interpolation / kriging surfaces (user-led, downstream of this pipeline)
- Predictive models for unmonitored areas (downstream)
- Refactored R notebooks loading from `data/parquet/` (follow-up work)
