# 02 — Data Sources

Every dataset flowing through the pipeline, with provenance, retrieval method,
license, and quality notes.

## 1. EPA Air Quality System (AQS)

**Network:** federally-managed criteria pollutant monitoring
**Coverage in project:** 29 sites, 2015-01-01 → 2025-07
**Parameters:** O₃, CO, SO₂, NO/NO₂/NOx, PM₂.₅, PM₁₀
**Native units:** ppm (O₃, CO), ppb (SO₂, NO, NO₂, NOx), µg/m³ (PM)
**License:** Public domain (U.S. government work)
**Retrieval method:** EPA AQS Data Mart API via project script
`02_Scripts/Python/smart_download_NO_VOCs.py` and related downloaders.
**Landing location:** `!Final Raw Data/EPA AQS Downloads/`

### Raw layout

```
!Final Raw Data/EPA AQS Downloads/
├── AQS_SouthTexas_2015_2025_COMPLETE.csv     (master, 933 MB)
├── by_pollutant/                              (7 CSVs, one per pollutant)
│   ├── CO_2015_2025_AllCounties.csv
│   ├── NO2_2015_2025_AllCounties.csv
│   ├── NOx_2015_2025_AllCounties.csv
│   ├── Ozone_2015_2025_AllCounties.csv
│   ├── PM10_2015_2025_AllCounties.csv
│   ├── PM25_FRM_2015_2025_AllCounties.csv
│   └── SO2_2015_2025_AllCounties.csv
├── by_site/                                   (41 site CSVs)
├── individual_downloads/                      (273 annual-parameter CSVs)
└── monitoring_sites_table.csv                 (reference metadata)
```

### Columns retained (EPA → merged schema)

| EPA column | Mapped to | Notes |
|---|---|---|
| `state_code`, `county_code`, `site_number` | same | FIPS identifiers |
| `parameter_code`, `poc` | same | AQS parameter + occurrence code |
| `date_local`, `time_local` | same | Local time of observation |
| `sample_measurement` | same | **Normalized to EPA units** in step 01 |
| `method_code` | same | Measurement method |
| `units_of_measure` | dropped | Used only for validation |
| `latitude`, `longitude` | (extracted to reference table) | |

## 2. TCEQ (Texas Commission on Environmental Quality)

**Network:** state-managed, fills EPA coverage gaps especially for VOCs and
urban San Antonio / Corpus Christi.
**Coverage in project:** 14 sites, 2016-01-01 → 2025-11
**Parameters:** Same as EPA + VOCs (benzene, toluene, etc.) at Hillcrest
**Native units:** **ppb for O₃** (mismatch vs. EPA — see methodology §Unit normalization), ppb for SO₂/NO, µg/m³ for PM
**License:** Public records (Texas Public Information Act)
**Retrieval method:** Manual download from TCEQ TAMIS web portal
(https://www17.tceq.texas.gov/tamis/) in AQS RD (Raw Data) Transaction format.
**Landing location:** `!Final Raw Data/TCEQ Data - Missing Sites/`

### Raw layout

```
!Final Raw Data/TCEQ Data - Missing Sites/
├── TCEQ_CalaveresLake_PM2.5,SO2,NOx,O3_2016-2025.txt
├── TCEQ_NOX_2016-2025.txt
├── TCEQ_O3_2016-2015_Guadelupe.txt
├── TCEQ_O3_2016-2025_MissingGuadelupe.txt
├── TCEQ_PM10TEOM_NewBraunfelsOakPkwy.txt
├── TCEQ_PM2.5TEOM_2016-2025.txt
├── TCEQ_VOCsAutoGC_2016-2025_CCPalmNueces.txt   ← mis-named; actually 6 Bexar sites
└── TCEQ_VOCsCanister_2016-2025_HillcrestNueces.txt
```

**IMPORTANT NAMING NOTE:** The `TCEQ_VOCsAutoGC_*_CCPalmNueces.txt` filename is
misleading. Its contents are **443,297 rows of CO/SO₂/NO/NO₂/NOx/O₃/PM₂.₅ for
6 Bexar sites**, not VOCs and not Nueces. The reorg scripts correctly sorted
the rows into the EPA pollutant buckets despite the filename. Documented in
[06_data_quality.md](./06_data_quality.md).

### AQS RD Transaction Format (pipe-delimited)

```
Transaction Type|Action|State Cd|County Cd|Site ID|Parameter Cd|POC|Dur Cd|
Unit Cd|Meth Cd|Date|Time|Value|Null Data Cd|...
```

Critical field: `Unit Cd`. AQS standard codes:
- `001` = ppm (parts per million)
- `007` = ppmC
- `008` = ppb (parts per billion) ← **TCEQ ozone uses this, creates mismatch with EPA ppm**
- `009` = ppbC
- `105` = µg/m³ LC (local conditions)

## 3. Extra TCEQ Sites reference workbook

**File:** `!Final Raw Data/Extra TCEQ Sites.xlsx`
**Purpose:** Site metadata including lat/lon for 18 TCEQ CAMS sites not in
EPA AQS Data Mart.
**Sheets:** `Missing Sites` (18 rows), `Summary by County` (4 rows),
`Data Download Checklist` (18 rows).
**Use in pipeline:** Step 05 merges these coordinates with `enhanced_monitoring_sites.csv`
for Haversine-nearest-station pairing. Covers all 12 previously
unpaired sites in the pipeline.

## 4. OpenWeather historical hourly observations

**Source:** OpenWeather One Call API (historical endpoint)
**Coverage:** 15 stations, 2015-01-01 → 2025-11
**Retrieval:** Project bulk-download script with per-station coordinate list
in `01_Data/Reference/weather_bulk_*_sites.csv`
**License:** OpenWeather commercial data license (project has active subscription)
**Landing location:**

```
01_Data/OpenwWeatherData/
├── Historical Weather Data/    (15 station CSVs, hourly)
└── Irradiance Data/            (13 station CSVs, hourly)
```

### Pre-processed master

The raw station files are merged and enriched into
`01_Data/Processed/Meteorological/Weather_Irradiance_Master_2015_2025.csv`
(440 MB, 1.47M rows, 45 columns). The pipeline reads this file directly as
its weather input. Derivations already present in the master:

- `temp_f` alongside `temp` (Celsius in this master — not Kelvin as earlier
  stages used)
- `wind_u`, `wind_v` components
- `heat_index_c`
- `td_spread` (dew-point spread)
- `is_raining` flag
- `season` (DJF/MAM/JJA/SON)

Step 02 of the pipeline does **not** re-derive these fields; it only renames
`site_name` → `location` and ensures a stable `temp_c` alias.

## 5. AQ ↔ Weather station mapping (legacy)

**File:** `01_Data/Processed/Meteorological/AQ_Weather_SiteMapping.csv`
**Columns:** `aq_lat, aq_lon, wx_site, distance_km`
**Limitation:** Keyed by raw lat/lon tuples, not by AQS site ID. Step 05
**does not use this file** for joining; it recomputes nearest-neighbor
pairing from canonical site coordinates for reproducibility.

## 6. Reference registry (authoritative site list)

**File:** `01_Data/Reference/enhanced_monitoring_sites.csv`
**Rows:** 29 AQ sites with verified lat/lon, pollutant coverage, operating
schedules, and AQS network type.
**Derived from:** EPA AQS monitoring site table + manual TCEQ enrichment.
**Use in pipeline:** Primary coordinate source for step 05's Haversine pairing.

## Data freshness

| Source | Last refresh | Cadence | Next refresh |
|---|---|---|---|
| EPA AQS | 2026-02-18 | Ad-hoc annual | Early 2027 |
| TCEQ CAMS | 2026-04-06 | Ad-hoc annual | Early 2027 |
| OpenWeather | 2025-12 | Bulk end-of-year | Late 2026 |

## Re-running data acquisition

Data acquisition is **outside** the pipeline scope — raw files are treated
as immutable inputs. To add a new year or new site:

1. Download raw data from EPA AQS Data Mart or TCEQ TAMIS
2. Place under `!Final Raw Data/…`
3. Re-run upstream reorganization scripts in `02_Scripts/Python/` to refresh
   `01_Data/Processed/By_Pollutant/*.csv`
4. Re-run the pipeline: `python pipeline/run_pipeline.py`

Steps 1–3 are the responsibility of the project team and pre-date this
pipeline. Step 4 handles everything from raw CSV → Postgres in ~15 minutes.
