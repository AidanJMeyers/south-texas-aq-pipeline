# 04 — Pipeline Architecture

## Overview

```
┌──────────────────────── INPUTS (read-only, immutable) ─────────────────────┐
│  !Final Raw Data/EPA AQS Downloads/*.csv                                    │
│  !Final Raw Data/TCEQ Data - Missing Sites/*.txt                            │
│  !Final Raw Data/Extra TCEQ Sites.xlsx                                      │
│  01_Data/Processed/By_Pollutant/*.csv        (7 merged files, 565 MB)       │
│  01_Data/Processed/Meteorological/                                          │
│    Weather_Irradiance_Master_2015_2025.csv   (440 MB)                       │
│    AQ_Weather_SiteMapping.csv                                               │
│  01_Data/Reference/enhanced_monitoring_sites.csv                            │
└────────────────────────────────────────────────────────────────────────────┘
                                  │
                     python pipeline/run_pipeline.py
                                  │
   ┌──────────────┬───────────────┼───────────────┬──────────────┬────────────┐
   ▼              ▼               ▼               ▼              ▼            ▼
  00          01                02              03             04           05
 validate   pollutant→parquet  weather→parquet   NAAQS        daily aggs    merge AQ+WX
   │          (dedupe + unit     (rename + ensure  (per-site      (75% rule  (Haversine
   │           normalization)    stable aliases)   design values) completeness) pairing)
   │              │                │                │              │          │
   └──────────────┴────────┬───────┴────────────────┴──────────────┴──────────┘
                           ▼
                         06 export
                         (CSV verify + optional R .rds)
                           │
                           ▼
                         07 Postgres
                         (Neon free tier, aq schema)

┌──────────────────────── OUTPUTS (pipeline-managed) ────────────────────────┐
│  data/parquet/pollutants/     Hive-partitioned by group, year              │
│  data/parquet/weather/        Hive-partitioned by location, year           │
│  data/parquet/naaqs/          Design values per (site, year)               │
│  data/parquet/daily/          Daily + monthly aggregates                   │
│  data/parquet/combined/       Merged AQ + daily weather                    │
│  data/csv/                    Flat CSV exports                             │
│  data/rds/                    R-native bundles (optional, step 06)         │
│  data/_logs/                  Per-step log files                           │
│  data/_validation/            Validation report JSON                       │
│  Postgres (aq schema)         5 analysis-ready tables in Neon              │
└────────────────────────────────────────────────────────────────────────────┘
```

## Design principles

1. **Config-driven.** No hardcoded paths. `config.yaml` is the single source
   of truth. ROOT auto-detects across Colab / OneDrive / CWD.
2. **Idempotent.** Every step overwrites cleanly. `rm -rf data/ && python
   pipeline/run_pipeline.py` always produces identical output.
3. **Halt-on-error by default.** The orchestrator stops at the first failure
   unless `--continue-on-error` is passed. Validation halts before any
   expensive work.
4. **Warnings vs errors.** Validation checks are classified as `error`
   (halt) or `warning` (log and continue). Known data quirks like exact-row
   duplicates are warnings because step 01 handles them automatically.
5. **Separation of concerns.** Each step reads from a previous layer and
   writes to a new layer. No step modifies `!Final Raw Data/` or
   `01_Data/Processed/`.
6. **Raw preservation + analysis-ready outputs.** Parquet store keeps hourly
   resolution; derived tables (NAAQS, daily, combined) are rebuilt from
   parquet on demand.
7. **Optional Postgres.** Flat files work without any database. Postgres is
   an add-on for SQL / BI access; step 07 skips cleanly if the env var is
   unset.

## Step-by-step

### Step 00 — Validate Raw Data
**Script:** `pipeline/step_00_validate_raw.py`
**Reads:** All 7 By_Pollutant CSVs + weather master + site mapping
**Writes:** `data/_validation/validation_report.json`
**Runtime:** ~60 seconds

Runs 34 integrity checks. Exits nonzero on any error-severity failure so
downstream steps can't proceed. Known data quirks (exact-row duplicates,
SO₂ intra-POC value conflicts, missing sites vs. spec) are warnings.

**Checks performed:**
- 15-column schema on every pollutant CSV
- Row count within ±1% of expected for each file
- Total rows across all 7 pollutants (~5.84M)
- Unique AQS IDs (expected 41 active; warning if <36)
- 13 unique counties
- 7 pollutant groups
- No duplicate `(aqsid, date, time, parameter, poc)` tuples (warning)
- Per-pollutant date range falls within study window
- Weather master row count (~1.47M)
- 15 unique weather stations
- Site mapping file has required columns

### Step 01 — Pollutant Parquet Store
**Script:** `pipeline/step_01_build_pollutant_store.py`
**Reads:** `01_Data/Processed/By_Pollutant/*.csv`
**Writes:** `data/parquet/pollutants/` (partitioned by `pollutant_group`, `year`)
**Runtime:** ~2–3 minutes

For each of 7 pollutant CSVs:
1. Read with canonical 15-column dtype schema (`site_name` forced to string)
2. **Drop exact full-row duplicates** (~973k rows total, mostly TCEQ rows
   duplicated by the upstream reorg step)
3. **Normalize units** (see [methodology §Unit normalization](./05_methodology.md#1-unit-normalization)):
   TCEQ ozone rows are multiplied by 0.001 (ppb → ppm) to match EPA
4. Derive `datetime`, `year`, `month`, `hour`, `season`
5. Normalize `county_name` to title case (fixes COMAL/GUADALUPE/NUECES)
6. Write to Hive-partitioned parquet using pyarrow

### Step 02 — Weather Parquet Store
**Script:** `pipeline/step_02_build_weather_store.py`
**Reads:** `Weather_Irradiance_Master_2015_2025.csv`
**Writes:** `data/parquet/weather/` (partitioned by `location`, `year`)
**Runtime:** ~20 seconds

1. Read the full 440 MB CSV
2. Rename `site_name` → `location` (partition key, matches spec convention)
3. Add stable `temp_c` alias (source is already Celsius; master has `temp_f`
   alongside, confirming units)
4. Ensure `year`, `month`, `hour` columns exist (source uses `hour_local`)
5. Sanitize `location` values for filesystem-safe partition paths
6. Write to Hive-partitioned parquet

**Note:** The weather master already contains `wind_u`, `wind_v`,
`heat_index_c`, `td_spread`, and `is_raining` — step 02 does NOT
recompute these. Earlier drafts did; removed after confirming the upstream
file was already enriched.

### Step 03 — NAAQS Design Value Computation
**Script:** `pipeline/step_03_compute_naaqs.py`
**Helper:** `pipeline/utils/naaqs.py` (pure functions, unit-testable)
**Reads:** `data/parquet/pollutants/`
**Writes:** `data/parquet/naaqs/design_values.parquet`, `data/csv/naaqs_design_values.csv`
**Runtime:** ~10 seconds

For each `(pollutant_group, aqsid)`:
1. Pivot to a tz-naive `DatetimeIndex`'d hourly `pd.Series`
2. Average across POCs at the same timestamp (deduplicates simultaneous
   sub-instruments)
3. Apply each applicable NAAQS metric from the dispatch table
4. Emit one row per `(aqsid, year, metric)` with value, units, standard, exceeds flag

**Dispatch table** (`pipeline/utils/naaqs.py:METRIC_DISPATCH`):
```python
{
    "Ozone":      [("ozone_8hr_4th_max",   ...)],
    "PM2.5":      [("pm25_annual_mean",    ...),
                   ("pm25_24hr_p98",       ...)],
    "PM10":       [("pm10_24hr_exceedances", ...)],
    "CO":         [("co_8hr_max", ...), ("co_1hr_max", ...)],
    "SO2":        [("so2_1hr_p99", ...)],
    "NOx_Family": [("no2_1hr_p98",      ...),
                   ("no2_annual_mean",  ...)],  # applies to param 42602 only
}
```

All NAAQS formulas follow 40 CFR Part 50. Completeness rules: ≥6 of 8 hours
for 8-hr rolling averages, ≥18 of 24 hours for daily means/maxes. See
[methodology](./05_methodology.md#completeness-rules).

### Step 04 — Daily & Monthly Aggregates
**Script:** `pipeline/step_04_compute_daily_aggregates.py`
**Reads:** `data/parquet/pollutants/`
**Writes:** `data/parquet/daily/pollutant_daily.parquet`, `data/parquet/daily/pollutant_monthly.parquet`, `data/csv/daily_pollutant_means.csv`
**Runtime:** ~15 seconds

1. Load pollutant parquet
2. Group by `(aqsid, date_local, parameter_code, pollutant_name, pollutant_group, county_name, site_name)` and compute `mean, min, max, std, n_hours`
3. Compute `completeness_pct = n_hours / 24`
4. Flag `valid_day = completeness_pct >= 0.75`
5. Roll up to monthly using only valid days

**Both invalid and valid days are preserved** in the output so downstream
consumers can audit completeness themselves.

### Step 05 — Merge AQ + Weather
**Script:** `pipeline/step_05_merge_aq_weather.py`
**Helper:** `pipeline/utils/site_lookup.py`
**Reads:** `data/parquet/daily/pollutant_daily.parquet`, `data/parquet/weather/`, `enhanced_monitoring_sites.csv`, `Extra TCEQ Sites.xlsx`
**Writes:** `data/parquet/combined/aq_weather_daily.parquet`, `data/csv/combined_aq_weather_daily.csv`, `data/csv/site_registry.csv`
**Runtime:** ~90 seconds

1. **Build coordinate union** from two sources:
   - `enhanced_monitoring_sites.csv` (29 AQS-verified sites)
   - `Extra TCEQ Sites.xlsx` "Missing Sites" sheet (18 TCEQ CAMS sites)
   - Deduplicate on `aqsid` (CSV wins for overlapping rows)
2. **Derive weather station coordinates** from the first lat/lon row per
   station in the weather parquet (15 stations)
3. **Compute nearest station per pollutant site** via Haversine distance
4. **Fallback to county-name matching** for any site without coordinates
   (currently unused — all 41 active sites have coordinates after step 1)
5. **Collapse weather to daily** per station using the aggregation spec in
   `DAILY_WEATHER_AGGS`
6. **Join** daily pollutant → paired station → daily weather
7. **Build site registry** via `pipeline.utils.site_lookup.build_site_registry`
   (47 rows with `data_status` tags)

### Step 06 — Export Analysis-Ready Files
**Script:** `pipeline/step_06_export_analysis_ready.py`
**Helper:** `pipeline/utils/export_rds.R`
**Reads:** `data/csv/*.csv`
**Writes:** Optionally `data/rds/*.rds`
**Runtime:** ~5 seconds

1. Verify all expected CSV files exist
2. If `Rscript` is on `PATH`, shell out to `export_rds.R` to save
   `master_pollutant.rds`, `master_weather.rds`, `combined_daily.rds`
3. If `Rscript` is missing, log a warning and skip — this is non-fatal

### Step 07 — Load Postgres
**Script:** `pipeline/step_07_load_postgres.py`
**Helper:** `pipeline/utils/db.py`
**Reads:** `data/csv/site_registry.csv`, `data/parquet/naaqs/`, `data/parquet/daily/`, `data/parquet/combined/`
**Writes:** 5 tables in the `aq` schema of whatever Postgres instance
`AQ_POSTGRES_URL` points at
**Runtime:** ~5–9 minutes (dominated by network round-trips to Neon)

For each table spec in `config.yaml:postgres.tables`:
1. Read the parquet/CSV source
2. Clamp chunk size to stay under the Postgres 65535-parameter limit with
   `method="multi"` (chunksize ≤ 65000 / n_cols)
3. `df.to_sql(if_exists='replace', ...)` — full table replace for idempotency
4. Create per-column B-tree indexes listed in the config

On a free-tier quota error (e.g. Neon 0.5 GB limit), tables with
`skip_on_quota_error: true` are skipped with a warning and the remaining
tables continue. Currently only `aq_weather_daily` has that flag.

**Credentials are read ONLY from `AQ_POSTGRES_URL`** — never from config or
the filesystem. If the variable is unset, step 07 is skipped cleanly.

## Orchestrator

`pipeline/run_pipeline.py` is the entry point. CLI:

```
python pipeline/run_pipeline.py [options]

--config PATH              Use a different config.yaml
--only 01,03               Run only these step IDs
--skip 06,07               Skip these step IDs
--dry-run                  Print plan without executing
--continue-on-error        Don't halt on first failure
```

The orchestrator:
1. Loads `config.yaml` and resolves `ROOT`
2. Imports each step module and calls its `main(cfg)` function
3. Times each step and prints a summary table at the end
4. Halts on first failure unless overridden

## File layout

```
AirQuality South TX/
├── pipeline/
│   ├── __init__.py
│   ├── config.yaml                  ← Single source of truth
│   ├── run_pipeline.py              ← Orchestrator entry point
│   ├── step_00_validate_raw.py
│   ├── step_01_build_pollutant_store.py
│   ├── step_02_build_weather_store.py
│   ├── step_03_compute_naaqs.py
│   ├── step_04_compute_daily_aggregates.py
│   ├── step_05_merge_aq_weather.py
│   ├── step_06_export_analysis_ready.py
│   ├── step_07_load_postgres.py
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── io.py                    ← Config, paths, parquet readers/writers
│   │   ├── logging.py               ← get_logger + step_timer
│   │   ├── validation.py            ← CheckResult / CheckReport
│   │   ├── naaqs.py                 ← Pure NAAQS formulas
│   │   ├── site_lookup.py           ← 47-site registry builder
│   │   ├── db.py                    ← Postgres connection helper
│   │   └── export_rds.R             ← R helper for step 06
│   ├── README.md                    ← Short quick-start
│   ├── DATA_CATALOG.md              ← Output file manifest
│   ├── CHANGELOG.md                 ← Version history
│   └── docs/                        ← ← ← You are here
│       └── *.md
├── data/                            ← All pipeline outputs (git-ignored)
├── requirements.txt                 ← Python dependencies
└── PIPELINE_PROMPT.md               ← Original project specification
```
