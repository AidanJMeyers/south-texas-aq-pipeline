# Changelog

All notable changes to the South Texas AQ data pipeline are documented here.

## [0.3.3] — 2026-04-15

### Changed

- **Calaveras Lake Park (480291609) reclassified from `pending` to
  `excluded`.** Confirmed by the project team that this TCEQ-operated
  monitor measures only Total Suspended Particulate (TSP), which is
  outside the project's pollutant scope (PM₂.₅, PM₁₀, O₃, CO, NOx, SO₂,
  VOCs). It is a **separate physical site** from Calaveras Lake (EPA,
  480290059), not an alias. No data will be ingested from it.
- **Calaveras Lake (480290059) is now EPA-only.** Previously the merged
  pollutant CSVs carried a parallel TCEQ data feed for this AQSID
  (~478,846 rows post-dedup across NOx_Family, Ozone, PM2.5, SO2) that
  partially mirrored the EPA feed with occasional value conflicts.
  The v0.3.3 pipeline drops all rows matching
  `(aqsid=480290059, data_source=TCEQ)` via a new `OUT_OF_SCOPE_FILTERS`
  mechanism in `step_01_build_pollutant_store.py`. The EPA feed alone
  is used for this site.
- **`06_HTML_Reports/10_Site_Inventory_Report.html` updated** to reflect:
  * 42 active sites (not 43)
  * Calaveras Lake vs. Calaveras Lake Park clearly distinguished as
    two separate physical stations
  * Calaveras Lake Park marked as excluded (TSP-only)
  * Summary: 42 Active + 5 Non-Scope = 47 Total

### Added

- `OUT_OF_SCOPE_FILTERS` constant + `_drop_out_of_scope()` function in
  `pipeline/step_01_build_pollutant_store.py`. Each filter is an AND over
  `{column: value}` matches; rows matching any filter are dropped after
  dedup and logged. Extensible for future filters.
- `EXCLUDED_SITES` dict and `excluded` data_status in
  `pipeline/utils/site_lookup.py`.
- `config.yaml:expected.parquet_expected` — post-filter row counts for
  downstream validators and sanity checks (not enforced by step 00, which
  reads raw CSV counts).

### Removed

- `PENDING_SITES` dict and `pending` data_status for Calaveras Lake Park
  (no longer needs to be downloaded — deliberately excluded).

### Pipeline outcome

After v0.3.3 pipeline run:

| Layer | Row count |
|---|---:|
| Raw CSVs (validated by step 00) | 9,151,245 |
| Parquet store (step 01 output) | ~7,699,105 |
| Daily aggregates | ~400,000 |
| Active sites | **42** |

## [0.3.2] — 2026-04-15

### Added

- **Corpus Christi Palm VOCs data ingested.** The real CC Palm AutoGC VOCs
  raw file (3,307,617 rows, 46 VOC parameter codes, single site 483550083,
  2016–2025 coverage) was downloaded from TCEQ TAMIS and ingested into
  `01_Data/Processed/By_Pollutant/VOCs_AllCounties_2016_2025.csv`. The
  merged VOCs CSV now contains **3,354,321 rows** across **2 sites**
  (Hillcrest + CC Palm), up from 46,704 rows for 1 site.
- Active site count is now **42** (up from 41).
- CC Palm (483550083) is automatically picked up as `active` in the site
  registry — no hardcoded entry needed, driven by data presence.

### Changed

- **Calaveras Lake Park reclassified as a distinct site**, not a TCEQ
  alias. The `tceq_alias` status is removed from `site_lookup.py`. AQSID
  `480291609` (Calaveras Lake Park, TCEQ-operated) is now listed as
  `pending` — a separate physical monitoring station from AQSID
  `480290059` (Calaveras Lake, EPA-operated). This is the **43rd
  expected active site** and can be activated by downloading its raw
  data from TCEQ TAMIS, the same way CC Palm was.
- Old mislabeled file at
  `!Final Raw Data/TCEQ Data - Missing Sites/TCEQ_VOCsAutoGC_2016-2025_CCPalmNueces.txt`
  renamed to `TCEQ_BexarCriteria_2016-2025_MISLABELED.txt` (preserved
  for archival — it contains 443k rows of Bexar criteria pollutant data
  that are already correctly ingested via other CSVs).
- Real CC Palm VOCs data saved under the proper filename
  `TCEQ_VOCsAutoGC_2016-2025_CCPalmNueces.txt`.
- Config `expected.total_pollutant_rows` updated 5,843,628 → 9,151,245.
- Config `expected.pollutant_rows.VOCs` updated 46,704 → 3,354,321.
- Config `expected.active_sites` updated 41 → 42.

### Removed

- `TCEQ_INTERNAL_ALIASES` dict and `tceq_alias` data_status from
  `pipeline/utils/site_lookup.py`. Superseded by the distinct-site
  treatment of Calaveras Lake Park.

## [0.3.1] — 2026-04-15

### Fixed

- **Williams Park site status.** Reclassified `483551024` from `pending`
  to `disabled` per the inventory report
  (`06_HTML_Reports/10_Site_Inventory_Report.html`). It is not a pending
  download — the station is permanently disabled.
- **Calaveras Lake dual-ID framing corrected.** Previously the registry
  labeled `480290059` (EPA) as `active+dual_id` and `480291609` (TCEQ)
  as `pending`, implying a physical duplication to deduplicate. Verified
  from the raw files that **480291609 never appears as a measurement
  AQSID in any file** — including the `TCEQ_CalaveresLake_*.txt` file,
  which writes every row under 480290059. The two identifiers are now
  tracked as distinct registry entries: `480290059` as `active`, and
  `480291609` as `tceq_alias` with `co_located_with=480290059`. No
  deduplication is performed because there is nothing to deduplicate.
- **`TCEQ_VOCsAutoGC_CCPalmNueces.txt` mislabel documented.** Confirmed
  via direct inspection (all 443,297 rows, all 7 parameters, all 6 sites)
  that the file contains **zero VOC rows and zero Nueces County rows** —
  it is filled with CO/SO₂/NO/NO₂/NOx/O₃/PM₂.₅ data for 6 Bexar sites.
  Corpus Christi Palm (`483550083`) VOCs data is therefore **not in the
  project**; registry row updated with a clear note.

### Added

- `data_status` values expanded from 4 to 5:
  `active`, `reference`, `pending`, `disabled`, `tceq_alias`
- `co_located_with` column in `site_registry.csv` for cross-referencing
  TCEQ aliases to their measurement-carrying AQSIDs
- `notes` column in `site_registry.csv` with free-text explanation of each
  non-active row's status
- `TCEQ_INTERNAL_ALIASES` and `DISABLED_SITES` dicts in
  `pipeline/utils/site_lookup.py`

### Removed

- `target_sites: 43` from `config.yaml:expected` — the previous "path to
  43" rested on Williams Park being reachable, which it is not. Maximum
  achievable active count is 42 (adding CC Palm VOCs).
- `dual_id_group` column from `site_registry.csv` — superseded by
  `co_located_with` + `data_status == 'tceq_alias'`.

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
