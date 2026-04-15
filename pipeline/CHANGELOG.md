# Changelog

All notable changes to the South Texas AQ data pipeline are documented here.

## [0.3.0] — 2026-04-14

### Added

- **Publication-grade documentation suite** under `pipeline/docs/`:
  - `README.md` with table of contents
  - `01_overview.md`, `02_data_sources.md`, `03_data_schemas.md`,
    `04_pipeline_architecture.md`, `05_methodology.md`, `06_data_quality.md`
  - `07_usage_python.md`, `08_usage_r.md`, `09_usage_colab.md`, `10_usage_sql.md`
  - `11_reproducibility.md`, `12_configuration_reference.md`
  - `13_decisions.md` (Architecture Decision Records)
  - `14_publication_protocol.md` (Methods-section-ready prose)
  - `CITATION.cff` (machine-readable citation metadata)
- Top-level `README.md` at the repository root with quick-start and TOC
- `LICENSE` (MIT)
- `.gitignore` configured to exclude raw data and pipeline outputs
- `site_lookup.py` now emits all **47 sites** in the inventory with a
  `data_status` column: `active` (41), `reference` (3 CPS fence-line),
  `pending` (2 VOC sites awaiting TCEQ TAMIS download), and
  `active+dual_id` (1 Calaveras Lake EPA side).

### Fixed

- **Coordinate lookup for 12 TCEQ-only sites.** Step 05 now merges
  `enhanced_monitoring_sites.csv` (29 sites) with the `Missing Sites` sheet
  of `Extra TCEQ Sites.xlsx` (18 sites), covering all previously unpaired
  active sites. Pairing rate is now **41/41 via Haversine nearest-neighbor**
  (up from 30/41). Combined AQ+weather table grew from 191,284 to 236,070
  rows.
- `site_reference` path added to `config.yaml` pointing at the reference CSV.
- `read_parquet_dataset` in `pipeline/utils/io.py` now explicitly globs
  `*.parquet` files so OneDrive-injected `desktop.ini` sidecars do not
  crash the dataset scan.
- Config `expected.active_sites` updated from 43 → 41 (reality) with
  `target_sites: 43` and `total_inventory: 47` documented alongside.

### Documented (not new behavior)

- The `TCEQ_VOCsAutoGC_CCPalmNueces.txt` file is misnamed — contents are
  actually 443k rows of CO/SO₂/NO/NOx/O₃/PM₂.₅ for 6 Bexar sites.
  Documented in `06_data_quality.md` issue 10.
- The `VOCs_AllCounties_*.csv` merged file contains only 1 of 2+ expected
  VOC sites. Raw files for Corpus Christi Palm (483550083) and Williams
  Park (483551024) have not been downloaded from TCEQ TAMIS.

## [0.2.1] — 2026-04-14

### Fixed

- **Ozone unit mismatch between EPA (ppm) and TCEQ (ppb).** The merged
  `By_Pollutant/Ozone_AllCounties_2015_2025.csv` carried raw values from
  both networks without reconciliation, so TCEQ ozone rows were ~1000×
  too large. Step 01 now applies a per-`(parameter_code, data_source)`
  normalization table (`UNIT_CONVERSIONS` in
  `pipeline/step_01_build_pollutant_store.py`) before writing parquet.
  Only ozone needed conversion; all other pollutants already use
  matching units across EPA and TCEQ. Verified by inspecting the
  `units_of_measure` column of `!Final Raw Data/EPA AQS Downloads/
  by_pollutant/*.csv` and the AQS `Unit Cd` column of the TCEQ RD files.
  Conversion table documented in `DATA_CATALOG.md`.
- **Validation check severity.** Duplicate-hour and site-count checks
  that previously halted the pipeline are now WARNING-severity and
  allow the run to continue. Exact-duplicate rows are deduped by
  step 01 before writing parquet.
- **Validation date-range check** relaxed from "exactly spans
  endpoints" to "falls inside the study window," which correctly
  tolerates PM10's 2015-01-06 start, PM2.5's 2025-12-31 end, and
  VOCs' 2016-onward coverage.
- **Step 02 weather schema.** Adapted to the actual weather master
  columns (`site_name`, `temp` already in Celsius, `wind_u/v` and
  `heat_index_c` already present) — removed the Kelvin→Celsius
  conversion and duplicate derived columns.
- **Step 05 site pairing.** The existing `AQ_Weather_SiteMapping.csv`
  is keyed by raw lat/lon tuples, not by AQ site ID. Step 05 now
  loads coordinates from `01_Data/Reference/enhanced_monitoring_sites.csv`
  and computes per-site nearest-weather pairing via Haversine distance.
- **Step 07 chunk size.** Clamped per-table to stay under the Postgres
  65535-parameter-per-statement limit when using pandas
  `to_sql(method='multi')`.

### Added

- `site_reference` path in `config.yaml` pointing at
  `enhanced_monitoring_sites.csv`.
- `CheckResult.severity` field (`error`/`warning`) — warnings don't halt
  the pipeline.

## [0.2.0] — 2026-04-13

### Added

- `pipeline/utils/db.py` — SQLAlchemy + psycopg (v3) connection helper.
  Reads `AQ_POSTGRES_URL` from the environment, normalizes the URL,
  enforces `sslmode=require`, uses `pool_pre_ping=True` for Neon's
  auto-pause. Includes `ensure_schema`, `create_indexes`, and an
  `is_quota_error` heuristic.
- `pipeline/step_07_load_postgres.py` — loads the 5 analysis-ready tables
  (`site_registry`, `naaqs_design_values`, `pollutant_daily`,
  `pollutant_monthly`, `aq_weather_daily`) into the `aq` schema. Skipped
  cleanly (non-fatal) when the env var is unset. Tables with
  `skip_on_quota_error: true` are skipped gracefully if the free tier
  storage fills up.
- `postgres:` section in `config.yaml` — schema, chunk size, if_exists
  mode, and per-table specs with indexes. Credentials deliberately
  excluded.
- README + DATA_CATALOG sections on Postgres setup, Neon free-tier
  quirks, and example SQL.
- `sqlalchemy>=2.0` and `psycopg[binary]>=3.1` in `requirements.txt`.
- Step 07 added to the orchestrator (`run_pipeline.py`).

### Notes

- Raw hourly pollutant + weather data is deliberately **not** loaded to
  Postgres — too large for free-tier storage and rarely queried in SQL
  form. Use the parquet store for hourly work.

## [0.1.0] — 2026-04-13

Initial pipeline build. First reproducible end-to-end data pipeline for the
project.

### Added

- `pipeline/config.yaml` — single source of truth for paths, NAAQS levels,
  completeness thresholds, and expected row counts.
- `pipeline/utils/io.py` — config loading, ROOT auto-detection
  (Colab/OneDrive/CWD), canonical 15-column pollutant schema, parquet
  read/write helpers.
- `pipeline/utils/logging.py` — standardized per-step logger with
  stdout + file handlers and a `step_timer` context manager.
- `pipeline/utils/validation.py` — `CheckResult` / `CheckReport` and
  schema/row-count/unique-count/date-range/no-duplicate-hours checks.
- `pipeline/utils/naaqs.py` — pure NAAQS design value functions:
  ozone 8-hr 4th max, PM2.5 annual + 24-hr p98, PM10 exceedances, CO 8-hr,
  CO 1-hr, SO2 1-hr p99, NO2 1-hr p98, NO2 annual.
- `pipeline/utils/site_lookup.py` — builds the 43-site registry from the
  By_Pollutant CSVs + TCEQ Excel reference; flags Calaveras Lake dual-ID
  collision.
- `pipeline/utils/export_rds.R` — R helper for optional `.rds` export.
- `pipeline/step_00_validate_raw.py` — raw integrity checks, halts on
  failure.
- `pipeline/step_01_build_pollutant_store.py` — 7 CSVs → partitioned
  parquet by `pollutant_group` + `year`, normalizes county casing, derives
  datetime/season.
- `pipeline/step_02_build_weather_store.py` — weather master → partitioned
  parquet by `location` + `year`, Kelvin→Celsius, u/v wind, heat index.
- `pipeline/step_03_compute_naaqs.py` — per-site-year design values for
  every applicable NAAQS metric.
- `pipeline/step_04_compute_daily_aggregates.py` — daily + monthly
  per-site stats with 75% completeness flag.
- `pipeline/step_05_merge_aq_weather.py` — joins daily pollutant to
  daily-aggregated paired weather; emits `site_registry.csv`.
- `pipeline/step_06_export_analysis_ready.py` — verifies flat CSVs and
  runs optional R export.
- `pipeline/run_pipeline.py` — orchestrator with `--only`/`--skip`/
  `--dry-run`/`--continue-on-error`/`--config` CLI flags; idempotent;
  halts on first failure by default.
- `pipeline/README.md` — quick-start, architecture diagram, Colab/local
  notes, troubleshooting.
- `pipeline/DATA_CATALOG.md` — authoritative manifest of every output
  file with schemas and load examples.
- `requirements.txt` at repo root.

### Notes

- The pipeline never modifies `01_Data/`, `!Final Raw Data/`,
  `AM_R_Notebooks/`, or `02_Scripts/`.
- All outputs land under `data/`; safe to `rm -rf data/` and rebuild.
- NB1/NB2/NB3 R notebooks still read their original inputs — refactoring
  them to load from `data/parquet/` is deliberately out of scope for
  v0.1.0.
