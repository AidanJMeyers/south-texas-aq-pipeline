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

### 8b. Calaveras Lake TCEQ data feed is a duplicate of the EPA feed

**Severity:** Medium (~478k rows would have been mis-counted without a fix)
**Status:** ✅ Filtered in v0.3.3 (step 01 `OUT_OF_SCOPE_FILTERS`)

The EPA-operated Calaveras Lake monitor (AQSID `480290059`) has a
**parallel TCEQ data feed** in the merged pollutant CSVs. This feed
carries rows with `(aqsid=480290059, data_source='TCEQ')` alongside the
genuine EPA feed with `data_source='EPA'`. Investigation during v0.3.3:

| Pollutant | Dedup-exact duplicates | Post-dedup TCEQ rows at 480290059 | Same-key value conflicts |
|---|---:|---:|---:|
| NOx_Family | 502,656 → 251,328 | **251,328** | Yes |
| Ozone | 0 → 0 | **85,025** | N/A (dedup drops none) |
| PM2.5 | 0 → 0 | **60,377** | N/A |
| SO2 | 0 → 0 | **82,116** | N/A |
| **Total** | **251,328** | **478,846** | |

**Diagnosis — what the TCEQ feed is:**
- The `TCEQ_CalaveresLake_PM2.5,SO2,NOx,O3_2016-2025.txt` raw file writes
  every measurement row under AQSID `480290059` (the EPA-assigned ID).
  This is TCEQ republishing EPA's monitor data through its TAMIS portal.
- Roughly half of the NOx rows are **byte-for-byte duplicates** of the
  EPA feed (same `sample_measurement`, same timestamp, same method).
  Those are dropped automatically by step 01's `drop_duplicates()`.
- The other half — and all rows in Ozone, PM2.5, SO2 — are **same-key
  same-site same-time but different `sample_measurement`**. Likely
  causes: rounding differences between EPA and TCEQ data loaders, timing
  differences in when each network processed the same raw voltage,
  or genuinely different post-processing QC rules.
- In every case, the TCEQ feed is **secondary** — EPA is the primary
  source for this site because EPA operates it.

**Decision (v0.3.3):** Drop all rows matching
`(aqsid='480290059', data_source='TCEQ')` in step 01 via the new
`OUT_OF_SCOPE_FILTERS` mechanism. The 478,846 post-dedup TCEQ rows are
removed before writing to parquet. The EPA feed (the authoritative
source) is the only data used for this site.

**Why not average the two feeds?** Averaging EPA + TCEQ values for the
same timestamp would bias the analysis toward sites that happen to be
double-reported (i.e., just Calaveras Lake) relative to sites that only
appear in one network. Dropping the TCEQ feed gives us a consistent
"one authoritative source per site" rule.

**Also verified:** The separate physical TCEQ station at Calaveras Lake
Park (AQSID `480291609`) measures only Total Suspended Particulate (TSP),
which is outside the project's pollutant scope. It is tracked in the
registry as `excluded`, with `data_status='excluded'` and a clarifying
note. See the overall reconciliation in issue #9.

**Precedent / extensibility:** `OUT_OF_SCOPE_FILTERS` in
`pipeline/step_01_build_pollutant_store.py` is a list of
`(description, match_dict)` rules. Each rule is an AND over column
matches. Add to it if future data audits uncover other parallel feeds.

---

### 9. Site count 42 vs 43 vs 47 (inventory reconciliation)

**Severity:** Informational (spec vs. reality mismatch)
**Status:** ✅ Documented in v0.3.2 (site_lookup + config)

The inventory HTML report (`06_HTML_Reports/10_Site_Inventory_Report.html`)
lists 47 sites. The original specification says 43 should be "active with
data". The pipeline currently carries 42 active sites.

Current reconciliation (47 total, as of v0.3.2):

| Count | data_status | Sites |
|---:|---|---|
| **42** | `active` | Sites with measurement rows in the processed CSVs |
| **3** | `reference` | CPS Energy fence-line monitors (Gardner Rd, Gate 9A, Gate 58) — registered but never collected data |
| **1** | `pending` | **Calaveras Lake Park (480291609)** — TCEQ-operated monitor; raw data not yet downloaded from TCEQ TAMIS. This is the 43rd "expected active" site and is the only site needed to match the original specification. |
| **1** | `disabled` | Williams Park (483551024) — confirmed disabled in inventory report |

**Calaveras Lake vs. Calaveras Lake Park** — `480290059` is **Calaveras
Lake**, an EPA-operated monitor with full measurement data in the pipeline.
`480291609` is **Calaveras Lake Park**, a separate TCEQ-operated monitor
at the nearby park. They are distinct physical stations and must never be
deduplicated. The raw `TCEQ_CalaveresLake_*.txt` file writes every row
under `480290059` (the EPA AQSID), so the TCEQ-operated Calaveras Lake
Park monitor has zero data in the project until someone downloads its
raw data from TCEQ TAMIS.

**Path to 43 active sites:** Download the raw TCEQ TAMIS data for AQSID
`480291609`, place it under `!Final Raw Data/TCEQ Data - Missing Sites/`,
and rerun the ingestion. No pipeline code changes required.

**Fix:** `site_registry.csv` lists all 47 with a `data_status` column plus
a `co_located_with` cross-reference column (currently only populated for
the Calaveras alias pointing at 480290059).

Config's `expected.active_sites` is set to 41. The earlier "target_sites:
43" is now revised — there is **no path** to 43 unless Williams Park
(currently disabled) is reactivated AND CC Palm VOCs data is downloaded.

### 10. Original `VOCsAutoGC_CCPalmNueces.txt` file was mislabeled AND mis-filled

**Severity:** Medium (data acquisition gap, not a pipeline bug)
**Status:** ✅ Resolved in v0.3.2

The original file under
`!Final Raw Data/TCEQ Data - Missing Sites/TCEQ_VOCsAutoGC_2016-2025_CCPalmNueces.txt`
was named to describe **Corpus Christi Palm (AQSID 483550083) AutoGC VOCs
data**, but its actual contents were **443,297 rows of CO, SO₂, NO, NO₂,
NOx, O₃, and PM₂.₅ data for 6 Bexar County sites**. Zero rows for AQSID
483550083, zero rows in Nueces County, zero VOC parameter codes.

The Bexar site data is already correctly represented in the pipeline via
the `NOx_Family`, `CO`, `SO2`, `Ozone`, and `PM2.5` By_Pollutant CSVs
(upstream reorg scripts had already routed it by parameter code, not by
filename).

**Resolution:** The real CC Palm AutoGC VOCs data (3,307,617 rows, 46 VOC
parameter codes, 2016–2025) was downloaded from TCEQ TAMIS on 2026-04-15
and ingested into `VOCs_AllCounties_2016_2025.csv` via a custom converter
that parses AQS RD transaction format. The original mislabeled file was
renamed to `TCEQ_BexarCriteria_2016-2025_MISLABELED.txt` for archival.

### 11. VOCs file coverage

**Severity:** Informational
**Status:** ✅ v0.3.2 — now 2 VOC sites

After the v0.3.2 CC Palm ingestion, `VOCs_AllCounties_2016_2025.csv`
contains **3,354,321 rows** across **2 sites**:

| AQSID | Site | Method | Rows | Parameters |
|---|---|---|---:|---:|
| 483550029 | Corpus Christi Hillcrest | Canister | 46,704 | 84 |
| 483550083 | Corpus Christi Palm | AutoGC | 3,307,617 | 46 |

The large row count difference reflects the difference in measurement
cadence: Canister samples are collected and analyzed periodically,
while Auto GC runs continuously at hourly resolution.

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
