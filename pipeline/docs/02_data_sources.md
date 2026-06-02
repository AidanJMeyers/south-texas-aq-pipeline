# 02 — Data Sources

> **v0.4.0 update (2026-05-28):** This page now describes the TCEQ-only
> data architecture introduced in v0.4.0. The v0.3.7 EPA-blended history is
> preserved at the bottom of this page for reference, and the v0.3.7 schema
> is still queryable at `aq_v0_3_7_epa.*`. See the
> [v0.4.0 migration guide](./v0_4_0_migration.md) for the full rationale.

Every dataset flowing through the pipeline, with provenance, retrieval
method, license, and quality notes.

---

## 1. TCEQ TAMIS (sole pollutant source as of v0.4.0)

**Network:** Texas Commission on Environmental Quality — TAMIS web portal,
the state's air monitoring data system. TCEQ also submits to EPA's AQS,
so every site here is the upstream of the EPA data we used in v0.3.7.

**Coverage in project:** **41 active sites** across 13 South Texas counties,
**2015-01-01 → 2025-12-31** (some sites have shorter windows where the
monitor came online mid-period).

**Parameters:** 9 criteria pollutants + 47 VOC chemicals (see
`aq.parameter_reference` table or `!Archive_v0_3_7/inventory/parameter_reference.md`):
- **Criteria:** CO (42101), SO₂ (42401), NO (42601), NO₂ (42602), NOx (42603),
  Ozone (44201), PM₁₀ (81102), PM₂.₅ FRM/FEM (88101), PM₂.₅ acceptable (88502)
- **VOC paraffins (21):** Ethane, Propane, n-Butane … n-Undecane, 2-Methylheptane
- **VOC cycloalkanes (4):** Cyclopentane, Cyclohexane, Methylcyclohexane, Methylcyclopentane
- **VOC olefins (12):** Ethylene, Propylene, 1,3-Butadiene, Isoprene, …
- **VOC aromatics (11):** Benzene, Toluene, Ethylbenzene, m/p-Xylene, o-Xylene, …
- **HAPs flagged:** 10 of the VOCs are Hazardous Air Pollutants (CAA §112(b))

**Native units:** ppb (Ozone, SO₂, NOx family), ppbC (VOCs), µg/m³ (PM).
Ozone is converted ppb → ppm × 0.001 at ingestion (step 01b) to match the
EPA/pipeline canonical convention used downstream in NAAQS calculations.

**License:** Public records (Texas Public Information Act).

**Retrieval method:** Manual download from the
[TCEQ TAMIS web portal](https://www17.tceq.texas.gov/tamis/), one site or
county-VOC-bundle at a time, in **AQS RD (Raw Data) Transaction v1.6**
format (pipe-delimited, 28 fields, 11-row header).

**Landing location:**
`!Final Raw Data/TCEQ Downloads 5-21-26/Confirmed - AQS Ascending/`
(may also be referenced from `~/OneDrive/Downloads/TCEQ Downloads 5-21-26/...`
via the `raw_tceq_fallback` config path).

### Raw layout (2026-05-21 pull, 51 files, 9.77M rows total)

```
TCEQ Downloads 5-21-26/Confirmed - AQS Ascending/
├── !TCEQ Parameter Codes.pdf                       (TCEQ SWQM reference,
│                                                    NOT AQS — see note below)
├── 480131090.txt                  Pleasanton (Atascosa)
├── 480290032.txt                  San Antonio Northwest
├── 480290052.txt                  Camp Bullis
├── 480290053.txt                  Live Oak
├── 480290055.txt                  CPS Pecan Valley
├── 480290059.txt                  Calaveras Lake
├── 480290060_OnlyEPAReportingStandard.txt    Palo Alto — 24hr-only
├── 480290501.txt … 480290677.txt  Bexar CAMS sites
├── 480290622_A.txt                Heritage Middle School (split A)
├── 480290622_B.txt                Heritage Middle School (split B)
├── 480291069 … 480291610.txt      remainder of Bexar
├── 480610006_A.txt                Brownsville (Cameron, split A)
├── 480610006_B.txt                Brownsville (Cameron, split B)
├── 480611023 … 484931038.txt      remaining 23 site files
└── Bexar_VOCs1hrAutoGC.txt        county-level VOC bundles
    Bexar_VOCs24hrAutoGC.txt       (10 files: Bexar, Cameron, Comal,
    Cameron_VOCs24hrAutoGC.txt      Hidalgo, Karnes, Nueces × {1hr, 24hr},
    Comal_VOCs1hrAutoGC.txt         Webb, Wilson)
    Hidalgo_VOCs24hrAutoGC.txt
    Karnes_VOCS1hrAutoGC.txt
    Nueces_VOCS1hrAutoGC.txt
    Nueces_VOCS24hrAutoGC.txt
    WEBB_Vocs24hrAutoGC.txt
    Wilson_VOCS1hrAutoGC.txt
```

### AQS RD v1.6 transaction format (the 28 fields)

```
Transaction Type | Action | State Cd | County Cd | Site ID | Parameter Cd |
POC | Dur Cd | Unit Cd | Meth Cd | Date | Time | Value | Null Data Cd |
Col Freq | Mon Protocol ID | Qual Cd 1..10 | Alternate MDL | Uncertainty
```

The fields that drive pipeline routing:
- **Dur Cd** — Sample Duration Code. `1` = 1hr (criteria hourly); `7` or `X`
  = 24hr block (routes to `pollutant_daily_24hr` table — see decision #6 / #19
  in the [migration guide](./v0_4_0_migration.md)).
- **Parameter Cd** — drives `pollutant_group` mapping and the
  criteria-vs-VOC routing.
- **Unit Cd** — used for unit-conversion sanity checks at ingestion. AQS
  unit codes used here:
  - `001` = ppm · `007` = ppm (Ozone EPA standard) · `008` = ppb (Ozone TCEQ raw)
  - `017` = ppbC (VOCs) · `040` = ppb · `105` = µg/m³ (LC)

### Routing decisions applied at ingestion (step 01b)

```
parameter_code → pollutant_group → table

  CO (42101)                  → CO          → aq.pollutant_hourly
  SO2 (42401)                 → SO2         → aq.pollutant_hourly
  NO/NO2/NOx (42601/2/3)      → NOx_Family  → aq.pollutant_hourly
  Ozone (44201)               → Ozone       → aq.pollutant_hourly  (× 0.001 ppb→ppm)
  PM10 (81102)                → PM10        → aq.pollutant_hourly  (or daily_24hr if dur=7/X)
  PM2.5 (88101 / 88502)       → PM2.5       → aq.pollutant_hourly  (or daily_24hr if dur=7/X)
  VOC paraffins (43xxx)       → VOCs        → aq.vocs_1hr OR aq.vocs_24hr
  VOC cycloalkanes (43xxx)    → VOCs        → aq.vocs_1hr OR aq.vocs_24hr
  VOC olefins (43xxx)         → VOCs        → aq.vocs_1hr OR aq.vocs_24hr
  VOC aromatics (45xxx)       → VOCs        → aq.vocs_1hr OR aq.vocs_24hr
```

VOC cadence (1hr vs 24hr) is determined by the source filename
(`*_VOCs1hrAutoGC.txt` vs `*_VOCs24hrAutoGC.txt`), NOT by `dur` on each
row (TCEQ doesn't always set `dur` consistently on AutoGC files).

### Sites in this pull but EXCLUDED from v0.4.0

Defensive drops in step 01b — these AQSIDs are never loaded:

| AQSID | Name | Reason |
|---|---|---|
| 480290623 | Gardner Rd. Gas SubStation | CPS Energy fence-line monitor; no data, removed in v0.4.0 |
| 480290625 | Gate 9A CPS | same |
| 480290626 | Gate 58 CPS | same |
| 480291609 | Calaveras Lake Park | TSP only — outside project scope (decision #8) |
| 480291097 | Von Ormy | Not in this TCEQ pull (decision #18) |
| 483551024 | Williams Park | Disabled per 06_HTML_Reports/10_Site_Inventory_Report.html; retained in `site_registry` with `data_status='disabled'` for historical record only |

### Note on the included PDF

The `!TCEQ Parameter Codes.pdf` (447 KB) shipped with this download is the
**TCEQ SWQM Chapter 6** — Surface Water Quality Monitoring parameter codes
(water/sediment/fish/biological), **not** AQS air codes. None of those
codes appear in our pollutant data. Our authoritative parameter reference
is built from the [EPA AQS code tables](https://aqs.epa.gov/aqsweb/documents/codetables/parameters.html)
and lives at `aq.parameter_reference` + `!Archive_v0_3_7/inventory/parameter_reference.md`.

---

## 2. Extra TCEQ Sites reference workbook

**File:** `!Final Raw Data/Extra TCEQ Sites.xlsx`
**Purpose:** Site metadata including lat/lon for 18 TCEQ CAMS sites not in
EPA AQS Data Mart.
**Sheets:** `Missing Sites` (18 rows), `Summary by County` (4 rows),
`Data Download Checklist` (18 rows).
**Use in pipeline:** Merged with `enhanced_monitoring_sites.csv` for the
`lat` / `lon` columns on `aq.site_registry`.

---

## 3. OpenWeather + Solcast historical hourly observations

**Source:** OpenWeather One Call API (historical endpoint) + Solcast
irradiance.
**Coverage:** 15 stations across the 13-county footprint, 2015-01-01 → 2025-12.
**Retrieval:** Project bulk-download script with per-station coordinate list
in `01_Data/Reference/weather_bulk_*_sites.csv`.
**License:** OpenWeather commercial data license (project has active
subscription); Solcast academic license.
**Landing location:**

```
01_Data/OpenwWeatherData/
├── Historical Weather Data/    (15 station CSVs, hourly)
└── Irradiance Data/            (13 station CSVs, hourly)
```

### Pre-processed master

The raw station files are merged into
`01_Data/Processed/Meteorological/Weather_Irradiance_Master_2015_2025.csv`
(440 MB, 1.47M rows, 45 columns). Step 02 of the pipeline reads this
directly and writes partitioned parquet to `data/parquet/weather/`, which
is then loaded into `aq.weather_hourly` by step 07.

**Weather data is UNCHANGED in v0.4.0** — the EPA→TCEQ migration only
touched the pollutant side of the pipeline.

---

## 4. Reference / authoritative site list

**File:** `01_Data/Reference/enhanced_monitoring_sites.csv`
**Rows:** 29 sites with verified lat/lon.
**Use in v0.4.0:** Provides the `lat` / `lon` columns merged into
`aq.site_registry` during step 05b.

---

## 5. Parameter reference

**Source:** [EPA AQS Code Tables](https://aqs.epa.gov/aqsweb/documents/codetables/parameters.html)
(authoritative — TCEQ submits using these codes).
**File:** `data/csv/parameter_reference.csv` →
loaded into `aq.parameter_reference`.
**Rows:** 57 codes (9 criteria + 47 VOCs + 1 sparse PM10 variant).
**Columns:**

| Column | Type | Description |
|---|---|---|
| `parameter_code` | int | AQS parameter code (primary key) |
| `parameter_name` | text | Human-readable name |
| `chemical_family` | text | `Criteria \| VOC-Paraffin \| VOC-Cycloalkane \| VOC-Olefin \| VOC-Aromatic` |
| `pollutant_group` | text | Pipeline routing group |
| `default_units` | text | Canonical units (ppm / ppb / ppbC / µg/m³ LC) |
| `naaqs_regulated` | bool | Is there a current EPA NAAQS for this parameter |
| `is_hap` | bool | Listed in Clean Air Act §112(b) as a Hazardous Air Pollutant |
| `notes` | text | Any unit-conversion or sparseness notes |

---

## Data freshness

| Source | Last refresh | Cadence | Next refresh |
|---|---|---|---|
| TCEQ TAMIS | 2026-05-21 (v0.4.0 baseline) | Annual or on-demand | Early 2027 (full 2026 data) |
| OpenWeather + Solcast | 2025-12 | Bulk end-of-year | Late 2026 |

---

## Re-running data acquisition

Data acquisition is **outside** the pipeline scope — raw files are
immutable inputs. To add a new year or new site:

1. **Pull from TCEQ TAMIS** in AQS RD v1.6 format (one site at a time).
   For the 5 sites with multi-year data exceeding TAMIS's per-download cap,
   split into `_A.txt` + `_B.txt` files and step 01b will concatenate them
   on date.
2. Drop the new `.txt` file(s) into
   `!Final Raw Data/TCEQ Downloads 5-21-26/Confirmed - AQS Ascending/`
   (or update `raw_tceq` in `pipeline/config.yaml` to point to a new
   download bundle).
3. Add any new AQSIDs to the `SITE_NAMES_CANONICAL` dict in
   `pipeline/step_01b_ingest_tceq_raw.py` (so site_name resolves cleanly).
4. Re-run the pipeline: `python pipeline/run_pipeline.py` (~9 min) then
   `python pipeline/run_pipeline.py --only 07` (~54 min for Neon reload).

---

## v0.3.7 history (preserved here for reference)

Before v0.4.0, the pipeline blended **two** upstream sources:

- **EPA AQS Data Mart** — 29 sites pulled via the AQS API; pre-aggregated
  NAAQS-formatted hourly data. Mixed cadence (some sites at 24hr only),
  mixed units across parameters, opaque EPA-side QA.
- **TCEQ TAMIS** — 14 sites (and a few VOC bundles) pulled manually to
  fill gaps the EPA API did not cover.

Both sources fed the same `aq.pollutant_hourly` table with a `data_source`
column (`'EPA'` or `'TCEQ'`). The v0.3.6 split-name bug — where 24 sites
ended up with duplicate `site_name` strings because EPA and TCEQ wrote
them differently — was a direct symptom of this dual-source fragility.

v0.4.0 eliminates the EPA path entirely. Every site that previously came
from EPA is now pulled from TCEQ instead (TCEQ is the upstream source EPA
itself receives data from for these monitors). The v0.3.7 EPA-blended
schema is preserved in Neon as `aq_v0_3_7_epa.*` and can be queried as a
fallback. The local v0.3.7 build artifacts (821 MB of CSVs + 233 MB of
parquet) are snapshotted under `!Archive_v0_3_7/`.

For the full rationale, the 19 architectural decisions, and the rollback
procedure, see the [v0.4.0 migration guide](./v0_4_0_migration.md).
