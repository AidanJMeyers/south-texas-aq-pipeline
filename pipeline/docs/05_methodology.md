# 05 — Methodology

Technical and regulatory foundations for every transformation the pipeline
applies. This document is written to be citable from the Methods section
of a manuscript.

## 1. Unit normalization

### Problem

The upstream reorganization scripts merged EPA AQS and TCEQ CAMS data into
single per-pollutant CSVs (`01_Data/Processed/By_Pollutant/*.csv`) without
reconciling native units. For ozone specifically:

| Source | Native unit | Example raw value |
|---|---|---|
| EPA AQS | ppm | 0.0459 |
| TCEQ CAMS | ppb | 45.9 |

Downstream NAAQS calculations against the 0.070 ppm standard produced
nonsense values (~75 "ppm" at San Antonio sites) because TCEQ rows were
treated as ppm when they were actually ppb.

### Verification

Units were confirmed directly from the raw files under `!Final Raw Data/`:

**EPA (CSV with `units_of_measure` column):**
```python
import pandas as pd
epa = pd.read_csv('!Final Raw Data/EPA AQS Downloads/by_pollutant/Ozone_2015_2025_AllCounties.csv')
epa['units_of_measure'].unique()  # → ['Parts per million']
```

**TCEQ (AQS RD Transaction format with `Unit Cd` field):**
```python
# From TCEQ_O3_2016-2025_MissingGuadelupe.txt
# RD|I|48|091|0503|44201|01|1|008|...
#                             ^^^
#                             Unit Cd = 008 = Parts per billion (ppb)
```

The AQS standard unit code table (EPA AQS Data Mart documentation) maps:
- 001 = ppm
- 007 = ppmC
- 008 = ppb ← TCEQ ozone uses this
- 009 = ppbC
- 105 = µg/m³ LC

### Conversion table

Verified for every `(parameter_code, data_source)` combination in the
project data:

| Parameter | EPA unit | TCEQ unit | Target | Conversion |
|---|---|---|---|---|
| 44201 (O₃) | ppm | ppb | **ppm** | TCEQ × 0.001 |
| 42101 (CO) | ppm | — | ppm | (TCEQ absent) |
| 42401 (SO₂) | ppb | ppb | ppb | (none) |
| 42601 (NO) | ppb | ppb | ppb | (none) |
| 42602 (NO₂) | ppb | ppb | ppb | (none) |
| 42603 (NOx) | ppb | ppb | ppb | (none) |
| 88101 (PM₂.₅ FRM) | µg/m³ | — | µg/m³ | — |
| 88502 (PM₂.₅ non-FRM) | — | µg/m³ | µg/m³ | — |
| 81102 (PM₁₀) | µg/m³ | — | µg/m³ | — |

**Only ozone required conversion.** All other parameters already use matching
units across the two networks.

### Implementation

`pipeline/step_01_build_pollutant_store.py` applies conversions via the
`UNIT_CONVERSIONS` dictionary before writing parquet:

```python
UNIT_CONVERSIONS: dict[tuple[int, str], tuple[float, str]] = {
    (44201, "TCEQ"): (0.001, "ozone ppb → ppm"),
}

def _normalize_units(df, log):
    for (param, src), (factor, desc) in UNIT_CONVERSIONS.items():
        mask = (df.parameter_code == param) & (df.data_source == src)
        if mask.sum():
            df.loc[mask, 'sample_measurement'] *= factor
            log.info(f"unit normalize: {desc}  ({mask.sum():,} rows × {factor})")
    return df
```

**Applied in practice:** 638,174 TCEQ ozone rows were converted in the
current pipeline run. Post-conversion, the Bexar 8-hr ozone 4th-max values
land at 0.063–0.077 ppm, consistent with the San Antonio MSA's ongoing
nonattainment status.

### Reproducibility

Running `python pipeline/run_pipeline.py --only 01` after updating
`UNIT_CONVERSIONS` will rebuild the parquet store with the new conversion
in place. The step is idempotent; there is no state to roll back.

## 2. Duplicate handling

### Problem

The upstream reorg scripts wrote ~973k exact full-row duplicates when merging
TCEQ data into EPA-dominated CSVs. Additionally, ~167k rows for ~84k groups
have identical `(aqsid, date, time, parameter, poc)` keys but **different**
`sample_measurement` values — these are not simple duplicates but likely
reflect concurrent reports from redundant sub-instruments.

### Resolution

1. **Exact full-row duplicates** are dropped in step 01 before writing
   parquet. These carry no information.
2. **Same-key-different-value rows** are **preserved in the raw parquet
   store** and handled downstream in the NAAQS computation (step 03), which
   averages across POCs at the same timestamp via:

```python
s = df.set_index('datetime')['sample_measurement'].sort_index()
if s.index.duplicated().any():
    s = s.groupby(level=0).mean()
```

This matches EPA AQS's standard practice of averaging across POCs when
computing design values.

### Per-group counts (pipeline v0.3.3, April 2026)

| Pollutant | Raw rows | Exact-dup drops | Out-of-scope filter drops | Rows in parquet | Notes |
|---|---:|---:|---:|---:|---|
| NOx_Family | 1,989,602 | 551,305 | 251,328 | 1,186,969 | Calaveras TCEQ feed drop |
| Ozone | 1,823,627 | 311,508 | 85,025 | 1,427,094 | Calaveras TCEQ feed drop |
| PM2.5 | 1,168,298 | 110,481 | 60,377 | 997,440 | Calaveras TCEQ feed drop |
| SO2 | 524,039 | 0 | 82,116 | 441,923 | Calaveras TCEQ feed drop |
| CO | 191,448 | 0 | 0 | 191,448 | |
| PM10 | 99,910 | 0 | 0 | 99,910 | |
| VOCs | 3,354,321 | 0 | 0 | 3,354,321 | CC Palm + Hillcrest |
| **Total** | **9,151,245** | **973,294** | **478,846** | **7,699,105** | |

## 2b. Out-of-scope row filtering

After deduplication and before unit normalization, step 01 applies
per-row filters defined in
`pipeline/step_01_build_pollutant_store.py::OUT_OF_SCOPE_FILTERS`.
Each filter is an AND over `{column: value}` matches; matching rows are
dropped from the parquet store and logged.

### Current filters (v0.3.3)

| Filter | Rule | Rationale |
|---|---|---|
| Calaveras Lake TCEQ feed | `aqsid='480290059' AND data_source='TCEQ'` | TCEQ republishes the EPA feed for this site through TAMIS. Rows partially match EPA's `sample_measurement` (exact dups get dropped during dedup) and partially carry value conflicts from rounding / QC differences. Using only the EPA feed gives a single authoritative source per site. See [06_data_quality.md issue #8b](./06_data_quality.md). |

### How to add a new filter

Edit `OUT_OF_SCOPE_FILTERS` in step 01:

```python
OUT_OF_SCOPE_FILTERS: list[tuple[str, dict]] = [
    ("description", {"col": "value", ...}),
    # Add new filters here
]
```

Rerun with `python pipeline/run_pipeline.py --only 01,03,04,05,07` to
propagate changes through every downstream layer. Document the new
filter in `06_data_quality.md` with a clear rationale.

## 3. NAAQS design value computation

All formulas follow **40 CFR Part 50** (U.S. National Ambient Air Quality
Standards). Each function lives as a pure, unit-testable routine in
`pipeline/utils/naaqs.py`.

### 3.1 Ozone 8-hour

**Regulation:** 40 CFR §50.19, primary and secondary standard 0.070 ppm
**Form:** 4th-highest daily maximum 8-hour rolling mean, averaged over
3 consecutive years. The pipeline emits the per-year 4th-max; 3-year
averaging is left to downstream analysis.
**Completeness:** At least 6 of 8 hours for each rolling window

```python
def ozone_8hr_4th_max(hourly_ppm, min_hours_8hr=6):
    rolling = hourly_ppm.rolling(8, min_periods=min_hours_8hr).mean()
    daily_max = rolling.resample('D').max()
    for year, grp in daily_max.groupby(daily_max.index.year):
        yield year, grp.dropna().sort_values(ascending=False).iloc[3]  # 4th-highest
```

### 3.2 PM₂.₅ annual

**Regulation:** 40 CFR §50.13, primary standard 9.0 µg/m³ (revised February
2024; previously 12.0 µg/m³). The pipeline uses the current 9.0 value.
**Form:** Annual mean of daily means, averaged over 3 years.
**Completeness:** At least 18 of 24 hours for a daily mean.

```python
def pm_annual_mean(hourly, min_hours_daily=18):
    daily = hourly.resample('D').mean()
    daily[hourly.resample('D').count() < min_hours_daily] = np.nan
    return daily.groupby(daily.index.year).mean()
```

### 3.3 PM₂.₅ 24-hour

**Regulation:** 40 CFR §50.13, primary and secondary standard 35 µg/m³
**Form:** 98th percentile of 24-hour mean concentrations per year, averaged
over 3 years.

```python
def pm25_24hr_p98(hourly, min_hours_daily=18):
    daily = hourly.resample('D').mean()  # with completeness filter
    return daily.groupby(daily.index.year).quantile(0.98)
```

### 3.4 PM₁₀ 24-hour

**Regulation:** 40 CFR §50.6, standard 150 µg/m³
**Form:** Count of days where the 24-hour mean exceeds 150 µg/m³; not to
exceed an average of 1 per year over 3 years.
**Output:** Exceedance count per year (value = integer, units = "count").

### 3.5 CO (1-hour and 8-hour)

**Regulation:** 40 CFR §50.8
- 1-hour: 35 ppm, not to exceed more than once per year
- 8-hour: 9 ppm, not to exceed more than once per year

Pipeline emits the **annual maximum** for both metrics; downstream analysis
can count exceedances.

### 3.6 SO₂ 1-hour

**Regulation:** 40 CFR §50.17, standard 75 ppb
**Form:** 99th percentile of daily maximum 1-hour concentrations per year,
averaged over 3 years.

```python
def so2_1hr_p99(hourly, min_hours_daily=18):
    daily_max = hourly.resample('D').max()  # with completeness filter
    return daily_max.groupby(daily_max.index.year).quantile(0.99)
```

### 3.7 NO₂ 1-hour and annual

**Regulation:** 40 CFR §50.11
- 1-hour: 100 ppb, 98th percentile of daily max 1-hr averaged over 3 years
- Annual: 53 ppb arithmetic mean

Only parameter code **42602** (NO₂) is used; NO (42601) and NOx (42603) are
stored in the parquet but excluded from NAAQS metrics.

## Completeness rules

Two completeness thresholds are enforced, consistent with EPA guidance:

| Window | Minimum hours | Rationale |
|---|---|---|
| 8-hour rolling average | **6 of 8** | 40 CFR §50 App. I |
| 24-hour daily mean | **18 of 24** | 40 CFR §50 App. N (PM₂.₅), §50 App. S (SO₂/NO₂) |

Both thresholds are configurable in `config.yaml`:

```yaml
data_quality:
  hourly_completeness_threshold: 0.75
  daily_completeness_threshold:  0.75
  ozone_8hr_min_hours:           6
  pm_daily_min_hours:           18
```

**Daily validity flag:** `pollutant_daily.valid_day` is true when
`completeness_pct ≥ 0.75`. Invalid days are retained in the output but
excluded from monthly rollups.

## 4. Haversine nearest-station pairing

### Problem

Pollutant sites and weather stations are not co-located. The project has 41
active AQ sites and 15 weather stations — a many-to-one relationship where
each AQ site needs to be paired to its nearest weather station for joint
analysis.

### Input coordinates

| Source | Sites | Coverage |
|---|---|---|
| `01_Data/Reference/enhanced_monitoring_sites.csv` | 29 | EPA + 2 TCEQ with AQS-verified lat/lon |
| `!Final Raw Data/Extra TCEQ Sites.xlsx` | 18 | TCEQ CAMS-registered coordinates |

The two sources are merged by `aqsid`, with the CSV taking precedence on
overlap. After merge, all 41 active pollutant sites have coordinates.

Weather station coordinates are derived from the weather parquet itself —
the first `(lat, lon)` row per station. All 15 stations have coordinates.

### Haversine formula

Great-circle distance between two points on a sphere of radius R:

$$
d = 2R \arcsin\left(\sqrt{\sin^2\left(\frac{\phi_2 - \phi_1}{2}\right) + \cos(\phi_1)\cos(\phi_2)\sin^2\left(\frac{\lambda_2 - \lambda_1}{2}\right)}\right)
$$

where φ is latitude, λ is longitude (both in radians), R = 6371.0088 km.

Implementation in `pipeline/step_05_merge_aq_weather.py`:

```python
def _haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0088
    p1, p2 = np.deg2rad(lat1), np.deg2rad(lat2)
    dp = p2 - p1
    dl = np.deg2rad(lon2) - np.deg2rad(lon1)
    a = np.sin(dp/2)**2 + np.cos(p1)*np.cos(p2)*np.sin(dl/2)**2
    return 2*R*np.arcsin(np.sqrt(a))
```

For each AQ site, the nearest of the 15 weather stations is chosen and the
distance is stored in `aq_weather_daily.distance_km`. This allows
downstream consumers to **weight by distance** in spatial interpolation or
to **threshold** (e.g. drop pairings > 30 km when doing hyper-local analysis).

### Alternative pairings (out of scope for v0.3)

This nearest-neighbor approach is adequate for daily-resolution analysis but
has known limitations:
- Does not account for elevation differences
- Does not handle coastal/inland gradients (e.g. Corpus Christi coast vs. West)
- Does not leverage MERRA-2 or NLDAS reanalysis grids

The project plans to use spatial interpolation (kriging, IDW) for weather
fields downstream of this pipeline. The `distance_km` field exposed in
`aq_weather_daily` is the handoff point.

## 5. Season assignment

Months are mapped to meteorological seasons using the standard
3-month grouping:

| Season | Months | Abbreviation |
|---|---|---|
| Winter | Dec, Jan, Feb | DJF |
| Spring | Mar, Apr, May | MAM |
| Summer | Jun, Jul, Aug | JJA |
| Fall | Sep, Oct, Nov | SON |

Implemented in `step_01_build_pollutant_store.py::_SEASON_MAP`.

## 6. Regulatory references and source documents

The following documents define the NAAQS calculations, unit
conventions, and completeness rules used by the pipeline. These are the
authoritative sources — not self-citations of this project.

1. **40 CFR Part 50** — National Primary and Secondary Ambient Air Quality Standards.
   Code of Federal Regulations. https://www.ecfr.gov/current/title-40/chapter-I/subchapter-C/part-50

2. **U.S. EPA, Air Quality System (AQS)** — Data Mart. https://www.epa.gov/aqs

3. **EPA NAAQS Design Value Methodology** — U.S. EPA Office of Air Quality
   Planning and Standards, Technical Reports on NAAQS Compliance. 2024.

4. **TCEQ TAMIS** — Texas Commission on Environmental Quality, Texas Air
   Monitoring Information System. https://www17.tceq.texas.gov/tamis/

5. **OpenWeather** — Historical Hourly Weather API documentation.
   https://openweathermap.org/api/one-call-3

6. **Rothfusz, L.P. (1990)** — The Heat Index Equation. NWS Technical Attachment SR 90-23.

7. **Haversine formula** — derived from Sinnott, R.W. "Virtues of the Haversine."
   Sky and Telescope, 68(2):159, 1984.
