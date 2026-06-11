# 04 — Pipeline Architecture

> **v0.4.0 update (2026-05-28):** Architecture rewritten for TCEQ-only.
> New steps `01b` (raw TCEQ ingest), `01c` (VOC + daily_24hr parquet),
> `05b` (metadata CSVs); step `05` (combined AQ+weather) removed. See the
> [migration guide](./v0_4_0_migration.md) for the 19 architectural
> decisions that drove this rewrite.

## Overview (v0.4.0)

```
┌──────────────────────── INPUTS (read-only, immutable) ─────────────────────┐
│  !Final Raw Data/TCEQ Downloads 5-21-26/Confirmed - AQS Ascending/         │
│    51 .txt files in AQS RD v1.6 format (9.77M raw rows)                    │
│      ├── 41 per-site files (with A/B splits for 2 sites)                   │
│      └── 10 county-level VOC AutoGC files (1hr + 24hr cadences)            │
│  !Final Raw Data/Extra TCEQ Sites.xlsx          (site coordinates)         │
│  01_Data/Processed/Meteorological/                                         │
│    Weather_Irradiance_Master_2015_2025.csv      (440 MB)                   │
│  01_Data/Reference/enhanced_monitoring_sites.csv                           │
│  !Archive_v0_3_7/inventory/parameter_reference.csv (57 AQS codes)          │
└────────────────────────────────────────────────────────────────────────────┘
                                  │
                     python pipeline/run_pipeline.py   (~9 min total)
                                  │
   ┌──────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┐
   ▼      ▼      ▼      ▼      ▼      ▼      ▼      ▼      ▼      ▼
  00    01b     01    01c     02     03     04    05b    06     07
 valid │TCEQ  criteria  VOC + weather NAAQS  daily +  site_reg  CSV  Postgres
       │TXT → parquet  daily         design  monthly  + param   verify  COPY
       │CSV  (drop     parquet       values  aggs     reference        (Neon
       │     dups,     stores                                          aq schema)
       │     normalize
       │     units)
  00 → 01b → 01 → 01c → 02 → 03 → 04 → 05b → 06 → 07

┌──────────────────────── OUTPUTS (pipeline-managed) ────────────────────────┐
│  01_Data/Processed/By_Pollutant/*.csv          6 criteria CSVs (14 cols)   │
│  01_Data/Processed/By_VOC/vocs_{1hr,24hr}.csv  VOC long-format             │
│  01_Data/Processed/By_Pollutant_Daily/*.csv    Site 0060 PM10 24hr-only    │
│  data/parquet/pollutants/                      Hive part. by group, year   │
│  data/parquet/vocs_1hr/                        Hive part. by chemical, yr  │
│  data/parquet/vocs_24hr/                       Hive part. by chemical, yr  │
│  data/parquet/pollutant_daily_24hr/            Hive part. by group, yr     │
│  data/parquet/weather/                         Hive part. by location, yr  │
│  data/parquet/naaqs/                           Design values per (site,yr) │
│  data/parquet/daily/                           Daily + monthly aggregates  │
│  data/csv/site_registry.csv                    Built fresh by step 05b     │
│  data/csv/parameter_reference.csv              57 AQS codes                │
│  data/csv/{naaqs_design_values,daily_pollutant_means}.csv                  │
│  Postgres aq schema                            10 analysis-ready tables    │
│                                                 ~11.5M rows / ~2.4 GB      │
└────────────────────────────────────────────────────────────────────────────┘
```

Step 05 (`step_05_merge_aq_weather`) was retired in v0.4.0 — the combined
`aq_weather_daily` table is no longer generated (decision #13). Pollutant +
weather joins are now handled directly in user code via SQL against
`aq.pollutant_hourly` ⨝ `aq.weather_hourly` (or against the daily
aggregates).

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
**Reads:** All 6 criteria By_Pollutant CSVs (post-01b) + weather master
**Writes:** `data/_validation/validation_report.json`
**Runtime:** ~60 seconds

Runs integrity checks on the canonical-format CSVs produced by step 01b.
Exits nonzero on any error-severity failure so downstream steps can't
proceed.

**Checks performed (v0.4.0):**
- 14-column schema on every criteria pollutant CSV (NO `data_source`)
- Row count within ±2% of expected for each file (loosened during stabilization)
- Total rows across all 6 criteria pollutants computed dynamically from config
- Unique AQS IDs (expected 41 active; warning if <36)
- 13 unique counties
- 6 pollutant groups (VOCs live in their own tables now)
- No duplicate `(aqsid, date, time, parameter, poc)` tuples (warning)
- Per-pollutant date range falls within study window (2015-01-01 → 2025-12-31)
- Weather master row count (~1.47M)
- 15 unique weather stations

### Step 01b — Ingest Raw TCEQ TAMIS (NEW in v0.4.0)
**Script:** `pipeline/step_01b_ingest_tceq_raw.py`
**Reads:** 51 `.txt` files under `!Final Raw Data/TCEQ Downloads 5-21-26/Confirmed - AQS Ascending/`
**Writes:**
- `01_Data/Processed/By_Pollutant/{CO,SO2,NOx_Family,Ozone,PM10,PM2.5}_AllCounties_2015_2025.csv` (14-col)
- `01_Data/Processed/By_VOC/vocs_{1hr,24hr}_*.csv` (NEW)
- `01_Data/Processed/By_Pollutant_Daily/pollutant_daily_24hr_2015_2025.csv` (NEW)

**Runtime:** ~4.7 minutes (9.77M rows parsed from 51 TXT files)

What it does:

1. Parses each TXT file in AQS RD v1.6 transaction format (pipe-delimited,
   28 fields, 11-row header).
2. Detects file type: `site` (one AQSID per file) vs `voc` (county-level
   AutoGC bundle, multiple sites inside).
3. Concatenates A/B file splits for sites with multi-year data that exceeded
   TAMIS's per-download cap (Heritage MS 480290622, Brownsville 480610006).
4. Routes each row to its destination bucket via three rules in order:
   - **VOC parameter codes (43xxx / 45xxx) in a county VOC file** → `vocs_1hr` or
     `vocs_24hr` (cadence from filename)
   - **Sample Duration Code = 7 or X** → `pollutant_daily_24hr` (catches
     site 0060 + any future 24hr-only feed)
   - **Everything else (criteria pollutants, hourly cadence)** →
     `pollutant_<group>` CSV
5. Applies per-row transformations:
   - Ozone (44201): ppb → ppm × 0.001
   - aqsid built from zero-padded state+county+site
   - county_name from `COUNTY_NAMES` lookup
   - site_name from `SITE_NAMES_CANONICAL` lookup
   - pollutant_group from `PARAM_GROUP` lookup
   - `data_source` column **not written** (dropped in v0.4.0)
6. Defensive drops: 6 excluded AQSIDs (4 TSP sites, Von Ormy, Williams Park).
7. Dedupes on `(aqsid, date_local, time_local, parameter_code, poc)` within each bucket.

### Step 01 — Build Criteria Pollutant Parquet Store
**Script:** `pipeline/step_01_build_pollutant_store.py`
**Reads:** `01_Data/Processed/By_Pollutant/*.csv`
**Writes:** `data/parquet/pollutants/` (partitioned by `pollutant_group`, `year`)
**Runtime:** ~1 minute

Simplified in v0.4.0 — unit conversions and out-of-scope filtering are now
done upstream in 01b. This step just enriches with `datetime`/`year`/`month`/
`hour`/`season`/`county_name` (title-case) and writes the partitioned parquet.

### Step 01c — Build Auxiliary Parquet Stores (NEW in v0.4.0)
**Script:** `pipeline/step_01c_build_aux_stores.py`
**Reads:** `By_VOC/*.csv` + `By_Pollutant_Daily/*.csv`
**Writes:**
- `data/parquet/vocs_1hr/` (partitioned by `pollutant_name`, `year`)
- `data/parquet/vocs_24hr/` (partitioned by `pollutant_name`, `year`)
- `data/parquet/pollutant_daily_24hr/` (partitioned by `pollutant_group`, `year`)

**Runtime:** ~1 minute

VOC stores partition by `pollutant_name` (chemical species, e.g. "Benzene",
"Ethylene") rather than `pollutant_group` because every VOC row has
`pollutant_group="VOCs"` — that would be one giant partition. Splitting by
chemical keeps partitions small and lets downstream queries push down
`pollutant_name="Benzene"` filters cheaply.

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

### Step 05 — Merge AQ + Weather (RETIRED in v0.4.0)

This step is no longer in the pipeline. Decision #13 dropped the combined
`aq_weather_daily` table — pollutant ⨝ weather joins are handled by user
code in SQL/pandas/data.table directly against `aq.pollutant_hourly` or
`aq.pollutant_daily` and `aq.weather_hourly` (or their parquet
equivalents). Site coordinates are now merged into the site registry by
step 05b instead.

The v0.3.7 implementation lives in `pipeline/step_05_merge_aq_weather.py`
and remains in the repo for historical reference, but it's commented out
of `run_pipeline.py:STEPS` and is never executed.

### Step 05b — Build Metadata (NEW in v0.4.0)
**Script:** `pipeline/step_05b_build_metadata.py`
**Helper:** `pipeline/utils/site_lookup.py`
**Reads:** `data/parquet/{pollutants,vocs_1hr,vocs_24hr,pollutant_daily_24hr}/`, `enhanced_monitoring_sites.csv`, `Extra TCEQ Sites.xlsx`, `!Archive_v0_3_7/inventory/parameter_reference.csv`
**Writes:** `data/csv/site_registry.csv`, `data/csv/parameter_reference.csv`, `01_Data/Reference/parameter_reference.csv`
**Runtime:** ~30 seconds

1. **Build site registry** from the four parquet stores via
   `pipeline.utils.site_lookup.build_site_registry`:
   - Scan each store for unique AQSIDs and which pollutant_groups appear
   - Compute `pollutant_groups_hourly[]` (criteria pollutant groups in `pollutant_hourly`)
   - Compute `pollutant_groups_daily_24hr[]` (groups in `pollutant_daily_24hr`)
   - Compute `voc_cadence` (`'1hr'` / `'24hr'` / `'both'` / empty) from VOC stores
   - Add disabled sites (Williams Park 483551024) for completeness
2. **Merge lat/lon coordinates** from `enhanced_monitoring_sites.csv` +
   `Extra TCEQ Sites.xlsx`
3. **Copy the parameter reference seed** from the Phase 1 inventory
   artifact (57 AQS codes with HAP flags + chemical families) into both
   `data/csv/` and `01_Data/Reference/`

### Step 06 — Export Analysis-Ready Files
**Script:** `pipeline/step_06_export_analysis_ready.py`
**Reads:** `data/csv/*.csv`
**Writes:** Optionally `data/rds/*.rds`
**Runtime:** ~5 seconds

1. Verify all expected CSV files exist (`daily_pollutant_means.csv`,
   `naaqs_design_values.csv`, `site_registry.csv`, `parameter_reference.csv`)
2. If `Rscript` is on `PATH`, shell out to `export_rds.R` to save
   R-native bundles
3. If `Rscript` is missing, log a warning and skip — this is non-fatal

### Step 07 — Load Postgres via COPY (REWRITTEN in v0.4.0)
**Script:** `pipeline/step_07_load_postgres.py`
**Helper:** `pipeline/utils/db.py`
**Reads:** `data/csv/{site_registry,parameter_reference}.csv`, `data/parquet/{naaqs,daily,pollutants,vocs_1hr,vocs_24hr,pollutant_daily_24hr,weather}/`
**Writes:** 10 tables in the `aq` schema of whatever Postgres instance
`AQ_POSTGRES_URL` points at
**Runtime:** ~54 minutes via COPY (was ~5.5 hr with v0.3.7 `to_sql`)

For each table spec in `config.yaml:postgres.tables`:
1. Read the source (CSV, single parquet, or partitioned `parquet_dir`)
2. DROP TABLE IF EXISTS … CASCADE
3. CREATE TABLE via `df.head(0).to_sql` (schema inferred from pandas)
4. Bulk-load via `COPY … FROM STDIN WITH (FORMAT CSV)` in 100K-row chunks,
   one transaction per chunk, with 3-retry backoff on transient errors
5. CREATE INDEX for each configured index column
6. GRANT SELECT on the new table to `anonymous` + `authenticated`

After all tables load, ALTER DEFAULT PRIVILEGES sets future-table grants
so the read-only Data API roles continue to work even if new tables are
added.

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
