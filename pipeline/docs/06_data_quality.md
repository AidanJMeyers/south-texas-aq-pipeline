# 06 — Data Quality & Known Issues

A full catalog of every data quality issue discovered during pipeline
development, with explanation, resolution, and impact on analysis.

This document is updated whenever new issues surface. If you find something
not listed here, add it with a reproduction and fix.

## Issue catalog

### 1. Ozone unit mismatch between EPA and TCEQ ⚠️ CRITICAL

**Severity:** Critical (affected NAAQS numerical values by ~1000×)
**Status:** ✅ Fixed in v0.2.1 (step 01)

EPA reports ozone in parts per million (ppm); TCEQ reports it in parts per
billion (ppb). The upstream `By_Pollutant/Ozone_AllCounties_2015_2025.csv`
merged both networks without converting, producing a column where the
numeric value meant different things depending on the `data_source` column.

**Detection:** The first NAAQS run produced values like 76.9 "ppm" at
Bexar sites — an impossible number against the 0.070 ppm standard.

**Fix:** `pipeline/step_01_build_pollutant_store.py::_normalize_units` now
multiplies TCEQ ozone rows by 0.001 before writing to parquet. 638,174
rows affected. See [methodology §Unit normalization](./05_methodology.md#unit-normalization).

**Verification:** Post-fix, Bexar 8-hr ozone 4th-max values are 0.063–0.077
ppm — consistent with the San Antonio MSA's documented nonattainment.

### 2. Exact-row duplicates from upstream merge

**Severity:** Medium (inflates row counts, wastes storage, risks biasing
means if not deduplicated)
**Status:** ✅ Fixed in v0.2.1 (step 01)

The upstream reorg scripts wrote 973,294 exact full-row duplicates when
stitching EPA + TCEQ into the merged pollutant CSVs. All identical on every
column including `sample_measurement`.

| Pollutant | Duplicate rows |
|---|---:|
| NOx_Family | 551,305 |
| Ozone | 311,508 |
| PM2.5 | 110,481 |
| SO2, CO, PM10, VOCs | 0 |

**Fix:** `step_01::_enrich` calls `df.drop_duplicates()` before writing
parquet. Validation step 00 reports the dup count as a warning so future
regressions are visible.

### 3. SO₂ intra-key value conflicts

**Severity:** Low (ambiguous but uncommon; averaged downstream)
**Status:** ✅ Handled in step 03 (NAAQS computation)

SO₂ has 80,755 rows where `(aqsid, date, time, parameter, poc)` is identical
but `sample_measurement` values differ. These are **not** exact duplicates
and are not dropped. Most likely cause: duplicate downloads from EPA AQS at
different Data Mart refresh dates.

**Handling:** Step 03's `_site_timeseries` helper averages across duplicate
timestamps before applying NAAQS formulas — matching standard practice for
POC-averaged design values.

### 4. County name capitalization

**Severity:** Low (cosmetic but breaks string joins)
**Status:** ✅ Fixed in v0.2.1 (step 01)

Some files use ALL CAPS for `county_name` (COMAL, GUADALUPE, NUECES) and
others use title case. The merged CSV inherited both.

**Fix:** `step_01::_enrich` normalizes to title case with `str.title()`.

### 5. Weather temperature unit detection

**Severity:** Low (potential Kelvin→Celsius bug)
**Status:** ✅ Handled in step 02

The project went through multiple weather-data pipelines over time. Earlier
generations stored temperatures in Kelvin; the current
`Weather_Irradiance_Master_2015_2025.csv` is in Celsius (verified by the
presence of a `temp_f` column where `temp_f ≈ temp·9/5+32`).

**Handling:** `step_02::_ensure_temp_c` detects the unit by checking if
`mean(temp) > 60`. If so, it subtracts 273.15; otherwise it copies `temp`
to `temp_c` unchanged. Currently the copy branch is taken.

### 6. Weather file column names ≠ spec

**Severity:** Low (broke early step 02 drafts)
**Status:** ✅ Fixed in v0.2.1 (step 02)

`PIPELINE_PROMPT.md §4c` claims the weather master uses a `location`
column for station name. In reality it uses `site_name`. The spec also
lists fewer derived columns than the actual file.

**Fix:** Step 02's `_pick_station_col` accepts a small set of alternatives
(`location`, `site_name`, `station`, `station_name`) and renames to `location`.
The file also already contains `wind_u`, `wind_v`, `heat_index_c`,
`td_spread`, and `is_raining` — step 02 preserves these rather than
re-deriving.

### 7. AQ↔Weather site mapping file is keyed by raw coordinates

**Severity:** Medium (original pairing strategy unusable)
**Status:** ✅ Worked around in v0.2.1 (step 05)

`01_Data/Processed/Meteorological/AQ_Weather_SiteMapping.csv` has columns
`aq_lat, aq_lon, wx_site, distance_km` — no AQS site ID. This makes the
file impossible to join to the pollutant data without first linking
coordinates back to sites.

**Fix:** Step 05 abandons the existing mapping file and **recomputes
pairings from scratch** using the union of
`enhanced_monitoring_sites.csv` + `Extra TCEQ Sites.xlsx` as the coordinate
source for AQ sites. Results match the original mapping where comparable,
but are reproducible and self-consistent.

### 8. Missing coordinates for 12 TCEQ-only sites

**Severity:** Medium (blocked weather pairing for 11 sites initially)
**Status:** ✅ Fixed in v0.3.0 (step 05 + site_lookup)

12 active pollutant sites had no entry in `enhanced_monitoring_sites.csv`,
leaving them unpaired to any weather station.

**Fix:** Step 05 now also reads `Extra TCEQ Sites.xlsx` "Missing Sites"
sheet, which covers all 12. The union of the two sources maps 41/41
active sites to coordinates. No county-name fallback needed.

### 9. Site count 41 vs 43 vs 47

**Severity:** Informational (spec vs. reality mismatch)
**Status:** ✅ Documented in v0.3.0 (site_lookup + config)

The project specification (`PIPELINE_PROMPT.md §5`) claims 43 sites with
active data. The inventory HTML report lists 47. The pipeline finds 41.
Reconciliation:

| Count | Breakdown |
|---|---|
| **41** | Sites with measurement rows in the processed CSVs (actual pipeline state) |
| **43** | Target = 41 + 2 pending VOC downloads (Corpus Christi Palm 483550083, Williams Park 483551024) |
| **47** | Full inventory = 43 + 3 CPS fence-line reference-only sites + 1 dual-ID physical site (Calaveras Lake 480291609) |

**Fix:** `site_registry.csv` now lists all 47 with a `data_status` column:
- `active` (41)
- `reference` (3) — CPS fence-line, no data yet
- `pending` (2) — VOC sites awaiting TCEQ TAMIS download
- `active+dual_id` (1) — Calaveras Lake EPA side

Config's `expected.active_sites` is set to 41 with `target_sites: 43` and
`total_inventory: 47` documented alongside. Validation warns (not errors)
if the active count drops below 36, allowing reasonable site turnover.

### 10. TCEQ file misnamed

**Severity:** Informational
**Status:** Documented (no fix needed)

The file `!Final Raw Data/TCEQ Data - Missing Sites/TCEQ_VOCsAutoGC_2016-2025_CCPalmNueces.txt`
is **not** VOCs and **not** Corpus Christi Palm. Its actual contents:
443,297 rows of CO, SO₂, NO, NO₂, NOx, O₃, and PM₂.₅ for **6 Bexar sites**
(CPS Pecan Valley, Elm Creek, Fair Oaks Ranch, Heritage, San Antonio Red
Hill, Government Canyon).

**No fix needed:** The upstream reorg scripts already route the rows into
the correct pollutant buckets by `parameter_code`, so the misleading
filename has no downstream impact. Documented here so future maintainers
don't chase it.

### 11. VOCs file covers only 1 of 2 expected sites

**Severity:** Informational (feature gap, not a bug)
**Status:** Documented as pending

`VOCs_AllCounties_2016_2025.csv` contains 46,704 rows for exactly 1 site:
483550029 (Corpus Christi Hillcrest). The project spec mentions 2 VOC
sites. The second (and a third per inventory) require fresh downloads
from TCEQ TAMIS:
- 483550083 — Corpus Christi Palm
- 483551024 — Williams Park

**Path forward:** Download those sites from
https://www17.tceq.texas.gov/tamis/, drop the RD transaction files under
`!Final Raw Data/TCEQ Data - Missing Sites/`, update the upstream reorg
scripts to ingest them, then rerun the pipeline. Site count will become
43 active.

### 12. 2025 data is partial

**Severity:** Informational
**Status:** Documented

EPA data currently runs through **July 2025**; TCEQ through **November
2025**. Any full-year 2025 analysis will be incomplete. NAAQS design
values for 2025 should be treated as provisional.

### 13. OneDrive `desktop.ini` sidecar files

**Severity:** Low (crashed pyarrow dataset scans)
**Status:** ✅ Fixed in v0.2.1

OneDrive automatically drops `desktop.ini` files into synced folders,
including `data/parquet/pollutants/`. pyarrow's `ds.dataset(path)` default
scan tried to read these as parquet files and crashed.

**Fix:** `pipeline/utils/io.py::read_parquet_dataset` now explicitly
globs `*.parquet` files and passes a file list to `ds.dataset()`, bypassing
the recursive directory scan.

### 14. Calaveras Lake dual AQS ID

**Severity:** Informational
**Status:** Documented

One physical site is registered under two AQS IDs:
- **480290059** (EPA side)
- **480291609** (TCEQ side)

Both IDs map to the same coordinates, same instrument data. Spatial
analyses **must deduplicate** to avoid double-counting.

**Handling:** `site_registry.csv` flags both rows with
`dual_id_group='calaveras_lake'`. Downstream analysis should group by
`dual_id_group` when present and pick one canonical ID.

### 15. Postgres 65k parameter limit

**Severity:** Low (caused step 07 failure on first run)
**Status:** ✅ Fixed in v0.2.1

Postgres caps INSERT statements at 65,535 parameters. pandas
`to_sql(method='multi')` with a 50k chunk size × 14 columns = 700k
parameters, which explodes.

**Fix:** `step_07_load_postgres.py` clamps chunk size per-table:
`chunksize = min(configured, 65000 / n_cols)`. Logged to stdout.

## Validation check reference

Current validation check results (see `data/_validation/validation_report.json`
after any run):

| Check | Severity | Expected | Notes |
|---|---|---|---|
| `schema:<pollutant>` | error | 15-col canonical schema | Halts on mismatch |
| `row_count:<pollutant>` | error | From `config.expected.pollutant_rows` ±1% | |
| `row_count:all_pollutants` | error | 5,843,628 ±1% | |
| `nunique:aqsid` | **warning** | 41 (min 36) | Drops below min still warns |
| `nunique:county_name` | error | 13 | |
| `nunique:pollutant_group` | error | 7 | |
| `no_duplicate_hours:<pollutant>` | **warning** | 0 | Exact dups deduped in step 01 |
| `date_range:<pollutant>` | error | Within [2015-01-01, 2026-12-31] | Loose upper bound |
| `row_count:weather_master` | error | 1,470,050 ±1% | |
| `nunique:weather_station_location` | error | 15 | |
| `site_mapping:has_required_columns` | warning | distance+aq+weather cols | Legacy file is loose |

## Data caveats for downstream users

When citing or publishing from this pipeline, note these limitations:

1. **Ozone values pre-v0.2.1 were wrong.** Any analysis run against the
   parquet store built before April 14, 2026 needs re-running. Rebuild
   from scratch with: `rm -rf data/ && python pipeline/run_pipeline.py`.

2. **Site coverage is unbalanced.** 19 of 41 sites are in Bexar County; 1 site
   each in Atascosa, Karnes, Kleberg, Maverick, Victoria, Wilson. Regional
   averages should be area-weighted or population-weighted, not simple
   means across sites.

3. **NAAQS values are per-year, not per-3-year.** The pipeline emits the
   per-year statistic (e.g. 4th-highest 8-hr O₃ max). The formal NAAQS
   compliance metric is the 3-year average of those per-year values.
   Compute the 3-year mean downstream if comparing to standards.

4. **Weather pairings are single-nearest-neighbor.** A site with
   `distance_km > 20` has a weather record that's only loosely
   representative. Consider dropping or re-weighting at hyperlocal scales.

5. **Weather master is derived from OpenWeather, not ASOS/METAR.** Accuracy
   is generally good but station-specific biases may exist, particularly
   for irradiance fields which are modeled, not measured.

6. **2025 data is incomplete.** See issue 12.
