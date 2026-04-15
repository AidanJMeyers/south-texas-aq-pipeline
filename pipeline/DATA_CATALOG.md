# DATA_CATALOG — Pipeline Outputs

Authoritative manifest for everything the pipeline writes under `data/`.
If a file isn't listed here it isn't part of the supported surface.

Paths are relative to the project root (`AirQuality South TX/`).

---

## Parquet store

### `data/parquet/pollutants/`

Hive-partitioned: `pollutant_group=X/year=YYYY/*.parquet`.
Produced by: **step 01**.
Source: the 7 `01_Data/Processed/By_Pollutant/*.csv` files.
Expected rows: **~5,843,628** total.

| Column | Type | Description |
|---|---|---|
| `state_code` | int32 | FIPS state (always 48) |
| `county_code` | int32 | FIPS county (3-digit) |
| `site_number` | int32 | AQS site number |
| `parameter_code` | int32 | AQS parameter code |
| `poc` | int32 | Parameter Occurrence Code |
| `date_local` | string | `YYYY-MM-DD` |
| `time_local` | string | `HH:MM` |
| `sample_measurement` | float64 | Primary value — unit normalized to the EPA convention per pollutant (see unit note below) |
| `method_code` | int32 | Measurement method ID |
| `county_name` | string | Title case (normalized from ALL-CAPS originals) |
| `pollutant_name` | string | Specific pollutant |
| `aqsid` | string | 9-digit AQS ID |
| `data_source` | string | `"EPA"` or `"TCEQ"` |
| `pollutant_group` | string | **Partition key** |
| `site_name` | string | `Name_XXXX` format |
| `datetime` | timestamp[ns] | Derived from date_local+time_local |
| `year` | int16 | **Partition key** |
| `month` | int8 | |
| `hour` | int8 | |
| `season` | string | `DJF/MAM/JJA/SON` |

**Load example:**
```python
import pandas as pd
df = pd.read_parquet("data/parquet/pollutants",
    filters=[("pollutant_group","=","Ozone"),("year","=",2023)])
```

**Unit normalization (step 01):** The upstream By_Pollutant CSVs were built
from EPA (ppm for ozone) + TCEQ (ppb for ozone) without unit reconciliation.
Step 01 applies a single correction before writing parquet:

| Pollutant | EPA unit | TCEQ unit | Normalized to | Conversion |
|---|---|---|---|---|
| Ozone (44201) | ppm | ppb | **ppm** | TCEQ × 0.001 |
| CO (42101) | ppm | (not in TCEQ) | ppm | — |
| SO2 (42401) | ppb | ppb | ppb | — |
| NO/NO2/NOx (42601/02/03) | ppb | ppb | ppb | — |
| PM2.5 (88101/88502) | µg/m³ | µg/m³ | µg/m³ | — |
| PM10 (81102) | µg/m³ | (not in TCEQ) | µg/m³ | — |

Verified directly against `!Final Raw Data/EPA AQS Downloads/by_pollutant/`
(EPA) and `!Final Raw Data/TCEQ Data - Missing Sites/*.txt` (TCEQ AQS RD
format with explicit `Unit Cd`). Only ozone needed conversion.

---

### `data/parquet/weather/`

Hive-partitioned: `location=X/year=YYYY/*.parquet`.
Produced by: **step 02**.
Source: `Weather_Irradiance_Master_2015_2025.csv` (440 MB).
Expected rows: **~1,470,050** (15 stations × hourly, 2015–2025).

Derived columns added beyond the raw 45:

| Column | Unit | Notes |
|---|---|---|
| `temp_c` | °C | `temp - 273.15` (auto-detected from Kelvin) |
| `feels_like_c` | °C | |
| `dew_point_c` | °C | |
| `wind_u` | m/s | Meteorological u-component (`-speed·sin(deg)`) |
| `wind_v` | m/s | Meteorological v-component (`-speed·cos(deg)`) |
| `heat_index_c` | °C | Rothfusz regression when `temp_c>26` & `humidity>40` |

All original Kelvin temps, humidity, wind, GHI, etc. are preserved.

**Load example (R):**
```r
library(arrow)
wx <- open_dataset("data/parquet/weather/") |>
  filter(location == "Corpus Christi", year == 2023) |>
  collect()
```

---

### `data/parquet/naaqs/design_values.parquet`

One row per **(aqsid, year, metric)**.
Produced by: **step 03**.

| Column | Type | Description |
|---|---|---|
| `aqsid` | string | 9-digit AQS ID |
| `year` | int | Calendar year |
| `pollutant_group` | string | Ozone / PM2.5 / PM10 / CO / SO2 / NOx_Family |
| `metric` | string | `ozone_8hr_4th_max`, `pm25_annual_mean`, `pm25_24hr_p98`, `pm10_24hr_exceedances`, `co_8hr_max`, `co_1hr_max`, `so2_1hr_p99`, `no2_1hr_p98`, `no2_annual_mean` |
| `value` | float64 | Computed design value |
| `units` | string | `ppm` / `ppb` / `ug/m3` / `count` |
| `naaqs_level` | float64 | Standard level from `config.yaml` (null for exceedance counts) |
| `exceeds` | bool | `value > naaqs_level` |
| `site_name` | string | |
| `county_name` | string | |

Completeness rules applied: ≥6/8 hours for 8-hr rolling, ≥18/24 hours for daily
means and daily maxes. See `pipeline/utils/naaqs.py` docstring for the exact
40 CFR Part 50 definitions used.

---

### `data/parquet/daily/pollutant_daily.parquet`

One row per **(aqsid, date_local, parameter_code)**.
Produced by: **step 04**.

| Column | Description |
|---|---|
| `aqsid`, `date_local`, `parameter_code`, `pollutant_name`, `pollutant_group` | Identifiers |
| `county_name`, `site_name` | Site metadata |
| `mean`, `min`, `max`, `std` | Daily summary stats of `sample_measurement` |
| `n_hours` | Hours reported that day |
| `completeness_pct` | `n_hours / 24` |
| `valid_day` | `completeness_pct ≥ 0.75` |

### `data/parquet/daily/pollutant_monthly.parquet`

Same idea aggregated to `year_month` (YYYY-MM) using only valid days.

### `data/parquet/combined/aq_weather_daily.parquet`

Per-site-day join of `pollutant_daily` with daily-aggregated weather at the
paired station. Produced by: **step 05**.

Weather columns present (all daily aggregates): `temp_c`, `temp_c_min`,
`temp_c_max`, `feels_like_c`, `dew_point_c`, `humidity`, `humidity_min`,
`humidity_max`, `pressure`, `wind_speed`, `wind_speed_max`, `wind_u`,
`wind_v`, `wind_gust_max`, `clouds_all`, `visibility`, `rain_1h_sum`,
`ghi_cloudy_sky_sum`, `ghi_clear_sky_sum`, `heat_index_c_max`.

---

## Flat CSV exports (`data/csv/`)

For R/Colab users without `arrow`. Regenerated every pipeline run.

| File | Description | Source step | Rows (approx) |
|---|---|---|---|
| `daily_pollutant_means.csv`      | Full dump of `pollutant_daily.parquet` | 04 | ~4.5M |
| `naaqs_design_values.csv`        | Full dump of `design_values.parquet`   | 03 | ~1.5k |
| `combined_aq_weather_daily.csv`  | Full dump of `combined/aq_weather_daily` | 05 | ~4M |
| `site_registry.csv`              | 43 active sites with metadata | 05 | 43 |

### `site_registry.csv` columns

`aqsid, state_code, county_code, site_number, site_name, county_name,
network (EPA/TCEQ/BOTH), pollutants (;-separated), n_pollutants,
first_date, last_date, n_records, dual_id_group, lat, lon`

`dual_id_group='calaveras_lake'` flags the EPA 480290059 / TCEQ 480291609
collision — deduplicate in spatial analyses.

Sites with missing `lat`/`lon` are TCEQ-only sites not present in the TCEQ
reference registry; geocoding them is follow-up work.

---

## R-native bundles (`data/rds/`)

Produced by: **step 06** (via `pipeline/utils/export_rds.R`).
Best-effort — skipped with a warning if `Rscript` is not on `PATH`.

| File | Contents |
|---|---|
| `master_pollutant.rds` | `pollutant_daily` as a `data.frame` |
| `master_weather.rds`   | Full weather parquet collapsed to a `data.frame` |
| `combined_daily.rds`   | `aq_weather_daily` as a `data.frame` |

---

## Postgres tables (optional, step 07)

Loaded into the `aq` schema of whatever database `AQ_POSTGRES_URL` points to.
Raw hourly data is **not** loaded — stays in parquet only.

| Table | Source | Indexes | Notes |
|---|---|---|---|
| `aq.site_registry` | `data/csv/site_registry.csv` | `aqsid` | 43 rows |
| `aq.naaqs_design_values` | `data/parquet/naaqs/design_values.parquet` | `aqsid, year, metric, pollutant_group` | ~1.5k rows |
| `aq.pollutant_daily` | `data/parquet/daily/pollutant_daily.parquet` | `aqsid, date_local, pollutant_group` | ~4M rows |
| `aq.pollutant_monthly` | `data/parquet/daily/pollutant_monthly.parquet` | `aqsid, year_month, pollutant_group` | ~130k rows |
| `aq.aq_weather_daily` | `data/parquet/combined/aq_weather_daily.parquet` | `aqsid, date_local` | ~4M rows, skip-on-quota |

Schemas mirror the parquet/CSV sources exactly. See each source's section
above for column definitions.

**Credentials:** Read only from the `AQ_POSTGRES_URL` environment variable.
Never stored in any pipeline file.

---

## Internal/debug outputs

| Path | Description |
|---|---|
| `data/_logs/{step_name}.log` | Per-step log, appended on every run |
| `data/_validation/validation_report.json` | Pass/fail per check from step 00 |

These are safe to delete; they will be recreated on the next run.

---

## Deletion policy

Everything under `data/` is **pipeline-managed**. Safe to
`rm -rf data/ && python pipeline/run_pipeline.py` to rebuild from scratch.

Nothing under `01_Data/`, `!Final Raw Data/`, `AM_R_Notebooks/`, or
`02_Scripts/` is ever touched.
