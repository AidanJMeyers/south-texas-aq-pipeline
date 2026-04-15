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

### 9. Site count 41 vs 47 (inventory reconciliation)

**Severity:** Informational (spec vs. reality mismatch)
**Status:** ✅ Documented in v0.3.1 (site_lookup + config)

The inventory HTML report (`06_HTML_Reports/10_Site_Inventory_Report.html`)
lists 47 sites. The pipeline finds 41 with measurement data.

Current reconciliation (47 total):

| Count | data_status | Sites |
|---:|---|---|
| **41** | `active` | Sites with measurement rows in the processed CSVs |
| **3** | `reference` | CPS Energy fence-line monitors (Gardner Rd, Gate 9A, Gate 58) — registered but never collected data |
| **1** | `pending` | Corpus Christi Palm (483550083) — VOCs data needs fresh TCEQ TAMIS download |
| **1** | `disabled` | Williams Park (483551024) — confirmed disabled in inventory report |
| **1** | `tceq_alias` | Calaveras Lake TCEQ (480291609) — TCEQ internal alias; data is always written under EPA AQSID 480290059 |

**Fix:** `site_registry.csv` lists all 47 with a `data_status` column plus
a `co_located_with` cross-reference column (currently only populated for
the Calaveras alias pointing at 480290059).

Config's `expected.active_sites` is set to 41. The earlier "target_sites:
43" is now revised — there is **no path** to 43 unless Williams Park
(currently disabled) is reactivated AND CC Palm VOCs data is downloaded.

### 10. TCEQ file `VOCsAutoGC_CCPalmNueces.txt` is mislabeled AND mis-filled

**Severity:** Medium (data acquisition gap, not a pipeline bug)
**Status:** ⚠️ Documented; action required for full VOC coverage

The file `!Final Raw Data/TCEQ Data - Missing Sites/TCEQ_VOCsAutoGC_2016-2025_CCPalmNueces.txt`
is named to describe **Corpus Christi Palm (AQSID 483550083) AutoGC VOCs data**,
but its actual contents are **443,297 rows of CO, SO₂, NO, NO₂, NOx, O₃,
and PM₂.₅ data for 6 Bexar County sites** (CPS Pecan Valley, Elm Creek,
Fair Oaks Ranch, Heritage, San Antonio Red Hill, Government Canyon).
**Zero rows for AQSID 483550083**, zero rows in Nueces County, zero VOC
parameter codes (no 431xx, 432xx, or 452xx).

The Bexar site data is **already correctly represented** in the pipeline
via the `NOx_Family`, `CO`, `SO2`, `Ozone`, and `PM2.5` By_Pollutant CSVs
(upstream reorg scripts routed it by parameter code, not by filename).

**The CC Palm VOCs data is not in the project at all.** To add it:
1. Download AQSID 483550083 VOC data from TCEQ TAMIS as AQS RD transaction format
2. Drop the file under `!Final Raw Data/TCEQ Data - Missing Sites/`
3. Update upstream reorg scripts to ingest it into `VOCs_AllCounties_2016_2025.csv`
4. Rerun `python pipeline/run_pipeline.py`

### 11. VOCs file covers only 1 site (not 2)

**Severity:** Informational (feature gap, follow-up of issue 10)
**Status:** Documented

`VOCs_AllCounties_2016_2025.csv` contains 46,704 rows for exactly 1 site:
483550029 (Corpus Christi Hillcrest). The project's original plan called
for 2 VOC sites, with Corpus Christi Palm (483550083) being the second.

Per issue 10, the raw file meant to contain CC Palm's data actually
contains unrelated Bexar data. Until a fresh TCEQ TAMIS download supplies
the real CC Palm VOCs measurements, the pipeline has only one VOC site.

### 12. Calaveras Lake dual AQSID

**Severity:** Informational
**Status:** ✅ Documented in v0.3.1

Two AQS identifiers map to the Calaveras Lake area:

| AQSID | Name | Used as measurement ID? |
|---|---|:-:|
| 480290059 | Calaveras Lake (EPA) | ✅ Yes — all raw data uses this ID |
| 480291609 | Calaveras Lake (TCEQ) | ❌ No — TCEQ-internal alias only |

**The `TCEQ_CalaveresLake_*.txt` file**, despite the filename and the
"TCEQ" prefix, writes every row under AQSID 480290059 — the EPA-assigned
ID. The TCEQ-internal ID 480291609 **never appears** as an AQSID on any
measurement row, in any raw file, from either network.

**Handling:** The pipeline treats 480290059 as an active site (loaded from
data) and 480291609 as a `tceq_alias` entry in the registry with
`co_located_with=480290059`. Consumers should **not** attempt to deduplicate
the pair — there is nothing to deduplicate, because only one side carries
data. If you need to reference the TCEQ site identifier for compliance
reporting, use 480291609; for data queries, always use 480290059.

### 13. 2025 data is partial

**Severity:** Informational
**Status:** Documented

EPA data currently runs through **July 2025**; TCEQ through **November
2025**. Any full-year 2025 analysis will be incomplete. NAAQS design
values for 2025 should be treated as provisional.

### 14. OneDrive `desktop.ini` sidecar files

**Severity:** Low (crashed pyarrow dataset scans)
**Status:** ✅ Fixed in v0.2.1

OneDrive automatically drops `desktop.ini` files into synced folders,
including `data/parquet/pollutants/`. pyarrow's `ds.dataset(path)` default
scan tried to read these as parquet files and crashed.

**Fix:** `pipeline/utils/io.py::read_parquet_dataset` now explicitly
globs `*.parquet` files and passes a file list to `ds.dataset()`, bypassing
the recursive directory scan.

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
