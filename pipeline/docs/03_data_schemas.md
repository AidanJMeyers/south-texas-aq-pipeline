# 03 — Data Schemas

Complete schemas for every output the pipeline produces. This is the
authoritative reference — if a column name or unit differs from what you
see here, the pipeline has drifted and this doc is wrong.

## Parquet Store

### `data/parquet/pollutants/` — Hive partitioned

**Partition keys:** `pollutant_group=…/year=…/*.parquet`
**Rows:** ~4,870,334 after deduplication (from 5,843,628 raw)
**Produced by:** `step_01_build_pollutant_store.py`

| Column | Type | Unit | Description |
|---|---|---|---|
| `state_code` | int32 | — | FIPS state code (always 48 = Texas) |
| `county_code` | int32 | — | FIPS county code (3-digit) |
| `site_number` | int32 | — | AQS site number |
| `parameter_code` | int32 | — | AQS parameter code (e.g. 44201 = O₃) |
| `poc` | int32 | — | Parameter Occurrence Code (sub-instrument identifier) |
| `date_local` | string | — | ISO date `YYYY-MM-DD` (local time) |
| `time_local` | string | — | `HH:MM` (local time) |
| `sample_measurement` | float64 | varies | **Normalized to EPA units** (see §Unit conventions) |
| `method_code` | int32 | — | Measurement method code |
| `county_name` | string | — | Title case (normalized from ALL-CAPS) |
| `pollutant_name` | string | — | Specific pollutant name |
| `aqsid` | string | — | 9-digit AQS site identifier (`state+county+site`) |
| `data_source` | string | — | `"EPA"` or `"TCEQ"` |
| `pollutant_group` | string | — | **Partition key.** One of: `Ozone`, `NOx_Family`, `CO`, `SO2`, `PM2.5`, `PM10`, `VOCs` |
| `site_name` | string | — | `Human Name_XXXX` |
| `datetime` | timestamp[ns] | — | Derived from `date_local + time_local` |
| `year` | int16 | — | **Partition key** |
| `month` | int8 | — | 1–12 |
| `hour` | int8 | — | 0–23 |
| `season` | string | — | `DJF` / `MAM` / `JJA` / `SON` |

#### Unit conventions (pollutant parquet)

| Pollutant group | Parameter codes | Unit | Note |
|---|---|---|---|
| Ozone | 44201 | **ppm** | TCEQ rows converted from ppb (×0.001) in step 01 |
| NOx_Family | 42601, 42602, 42603 | ppb | EPA and TCEQ both native ppb |
| CO | 42101 | ppm | EPA-only, native ppm |
| SO2 | 42401 | ppb | EPA and TCEQ both native ppb |
| PM2.5 | 88101, 88500, 88502 | µg/m³ | Local conditions |
| PM10 | 81102, 85101 | µg/m³ | Local conditions |
| VOCs | 43xxx, 45xxx | ppbC | Carbon-normalized |

### `data/parquet/weather/` — Hive partitioned

**Partition keys:** `location=…/year=…/*.parquet`
**Rows:** 1,470,049
**Produced by:** `step_02_build_weather_store.py`

Inherits all 45 columns from `Weather_Irradiance_Master_2015_2025.csv`. The
most-used subset:

| Column | Type | Unit | Description |
|---|---|---|---|
| `dt` | int64 | unix seconds | UTC timestamp |
| `datetime_local` | string | — | Local datetime |
| `datetime_utc` | string | — | UTC datetime |
| `year`, `month`, `hour` | int16/8/8 | — | Derived from `datetime_local` |
| `date_local` | string | — | Local date `YYYY-MM-DD` |
| `location` | string | — | **Partition key.** Weather station name (renamed from `site_name`) |
| `county_name` | string | — | County the station is in |
| `lat`, `lon` | float64 | degrees | Station coordinates |
| `temp` | float64 | **°C** | Air temperature (already Celsius in master) |
| `temp_c` | float64 | °C | Stable alias (identical to `temp`) |
| `temp_f` | float64 | °F | Pre-computed Fahrenheit |
| `feels_like` | float64 | °C | Apparent temperature |
| `dew_point` | float64 | °C | Dew point |
| `td_spread` | float64 | °C | Dew point spread (`temp - dew_point`) |
| `humidity` | float64 | % | Relative humidity |
| `pressure` | float64 | hPa | Station pressure |
| `sea_level`, `grnd_level` | float64 | hPa | Reduced pressures |
| `wind_speed` | float64 | m/s | Wind speed |
| `wind_deg` | float64 | degrees | Wind direction (meteorological convention) |
| `wind_gust` | float64 | m/s | Peak gust in hour |
| `wind_u` | float64 | m/s | U-component (`-speed · sin(deg)`) |
| `wind_v` | float64 | m/s | V-component (`-speed · cos(deg)`) |
| `clouds_all` | float64 | % | Cloud cover fraction |
| `cloud_fraction` | float64 | 0–1 | Decimal cloud cover |
| `visibility` | float64 | m | Horizontal visibility |
| `rain_1h` | float64 | mm | Rainfall last hour |
| `rain_3h` | float64 | mm | Rainfall last 3 hours |
| `snow_1h` | float64 | mm | Snowfall last hour |
| `is_raining` | bool | — | Flag |
| `weather_id`, `weather_main`, `weather_description` | — | — | OpenWeather condition |
| `heat_index_c` | float64 | °C | Rothfusz (null when `T<26°C` or `RH<40%`) |
| `ghi_cloudy_sky`, `ghi_clear_sky` | float64 | W/m² | Global horizontal irradiance |
| `dni_cloudy_sky`, `dni_clear_sky` | float64 | W/m² | Direct normal irradiance |
| `dhi_cloudy_sky`, `dhi_clear_sky` | float64 | W/m² | Diffuse horizontal irradiance |

### `data/parquet/naaqs/design_values.parquet`

**Rows:** 764
**Produced by:** `step_03_compute_naaqs.py`

| Column | Type | Description |
|---|---|---|
| `aqsid` | string | Site |
| `year` | int | Calendar year |
| `pollutant_group` | string | `Ozone`, `PM2.5`, `PM10`, `CO`, `SO2`, `NOx_Family` |
| `metric` | string | See §NAAQS metric catalog |
| `value` | float64 | Computed design value |
| `units` | string | `ppm`, `ppb`, `ug/m3`, or `count` |
| `naaqs_level` | float64 | NAAQS threshold from `config.yaml` (null for exceedance counts) |
| `exceeds` | bool | `value > naaqs_level` |
| `site_name`, `county_name` | string | |

#### NAAQS metric catalog

| `metric` | Pollutant | Formula | NAAQS level | Applies when |
|---|---|---|---|---|
| `ozone_8hr_4th_max` | O₃ | 4th-highest daily max 8-hr rolling avg per year | 0.070 ppm | All sites with O₃ data |
| `pm25_annual_mean` | PM₂.₅ | Annual mean of daily means (≥18 hrs) | 9.0 µg/m³ | PM₂.₅ sites |
| `pm25_24hr_p98` | PM₂.₅ | 98th percentile of daily means per year | 35 µg/m³ | PM₂.₅ sites |
| `pm10_24hr_exceedances` | PM₁₀ | Count of daily means > 150 µg/m³ per year | — | PM₁₀ sites |
| `co_8hr_max` | CO | Annual max of 8-hr rolling means | 9 ppm | CO sites |
| `co_1hr_max` | CO | Annual max hourly | 35 ppm | CO sites |
| `so2_1hr_p99` | SO₂ | 99th percentile of daily max 1-hr per year | 75 ppb | SO₂ sites |
| `no2_1hr_p98` | NO₂ | 98th percentile of daily max 1-hr per year | 100 ppb | NO₂ only (param 42602) |
| `no2_annual_mean` | NO₂ | Annual mean | 53 ppb | NO₂ only (param 42602) |

Completeness rules are documented in [05_methodology.md](./05_methodology.md#completeness-rules).

### `data/parquet/daily/pollutant_daily.parquet`

**Rows:** 236,070
**Produced by:** `step_04_compute_daily_aggregates.py`

One row per `(aqsid, date_local, parameter_code)`.

| Column | Type | Description |
|---|---|---|
| `aqsid`, `date_local`, `parameter_code`, `pollutant_name`, `pollutant_group` | — | Identifiers |
| `county_name`, `site_name` | string | Metadata |
| `mean` | float64 | Daily mean of `sample_measurement` |
| `min` | float64 | Daily min |
| `max` | float64 | Daily max |
| `std` | float64 | Daily std dev (ddof=1) |
| `n_hours` | int64 | Hours reported that day |
| `completeness_pct` | float64 | `n_hours / 24` |
| `valid_day` | bool | `completeness_pct >= 0.75` |

### `data/parquet/daily/pollutant_monthly.parquet`

**Rows:** 6,070
**Produced by:** `step_04_compute_daily_aggregates.py`

One row per `(aqsid, year_month, parameter_code)`. Uses only valid days.

| Column | Type | Description |
|---|---|---|
| `aqsid`, `year_month`, `parameter_code`, `pollutant_name`, `pollutant_group` | — | Identifiers |
| `county_name`, `site_name` | string | |
| `monthly_mean` | float64 | Mean of daily means |
| `monthly_min`, `monthly_max`, `monthly_std` | float64 | |
| `n_valid_days` | int64 | Number of days meeting 75% threshold |

### `data/parquet/combined/aq_weather_daily.parquet`

**Rows:** 236,070
**Produced by:** `step_05_merge_aq_weather.py`

Daily pollutant joined with daily-aggregated weather at the **nearest** weather
station. Each row carries all of `pollutant_daily`'s columns PLUS:

| Column | Type | Description |
|---|---|---|
| `weather_station` | string | Paired station (same-county Haversine nearest) |
| `distance_km` | float64 | Great-circle distance from pollutant site to weather station |
| `temp_c`, `temp_c_min`, `temp_c_max` | float64 | Daily temperature stats (°C) |
| `feels_like_c`, `dew_point_c` | float64 | |
| `humidity`, `humidity_min`, `humidity_max` | float64 | % |
| `pressure` | float64 | hPa |
| `wind_speed`, `wind_speed_max` | float64 | m/s |
| `wind_u`, `wind_v` | float64 | m/s (for kriging) |
| `wind_gust_max` | float64 | m/s |
| `clouds_all` | float64 | % |
| `visibility` | float64 | m |
| `rain_1h_sum` | float64 | Daily precipitation |
| `ghi_cloudy_sky_sum`, `ghi_clear_sky_sum` | float64 | Daily integrated GHI |
| `heat_index_c_max` | float64 | Daily peak heat index |

## Flat CSV exports (`data/csv/`)

One-to-one dumps of the parquet tables above. Same schemas. Regenerated on
every pipeline run.

| File | Source | Rows (approx) |
|---|---|---:|
| `daily_pollutant_means.csv` | `pollutant_daily.parquet` | 236k |
| `naaqs_design_values.csv` | `design_values.parquet` | 764 |
| `combined_aq_weather_daily.csv` | `aq_weather_daily.parquet` | 236k |
| `site_registry.csv` | Built in step 05 from 4 sources | 47 |

### `site_registry.csv` (47 rows — full inventory)

| Column | Description |
|---|---|
| `aqsid` | 9-digit AQS site identifier |
| `state_code`, `county_code`, `site_number` | FIPS + site |
| `site_name` | Human-readable name |
| `county_name` | Title case |
| `network` | `EPA`, `TCEQ`, `BOTH`, or empty (reference/alias rows) |
| `pollutants` | `;`-separated list of pollutant groups measured |
| `n_pollutants` | Count of pollutant groups |
| `first_date`, `last_date` | Data coverage period (null for non-active rows) |
| `n_records` | Total raw observations across all pollutants |
| `data_status` | See breakdown below |
| `co_located_with` | Cross-reference AQSID for aliases (empty for most rows) |
| `notes` | Free-text explanation of the row's status |
| `lat`, `lon` | Decimal degrees (WGS84) |

**Status breakdown (47 total, as of v0.3.3):**

| Count | Status | Meaning |
|---:|---|---|
| **42** | `active` | Has measurement data in the pipeline |
| **3** | `reference` | CPS Energy fence-line monitors (Gardner Rd, Gate 9A, Gate 58) |
| **1** | `excluded` | Calaveras Lake Park (480291609) — TCEQ monitor, TSP-only (outside project scope) |
| **1** | `disabled` | Williams Park (483551024) — confirmed disabled in inventory |

**Note on Calaveras:** `480290059` (Calaveras Lake, EPA-operated, active)
and `480291609` (Calaveras Lake Park, TCEQ-operated, excluded) are
**separate physical monitoring stations**. Calaveras Lake Park measures
only Total Suspended Particulate (TSP), which is outside the project's
scope (PM₂.₅, PM₁₀, O₃, CO, NOx, SO₂, VOCs). Do not deduplicate.

**Important:** Always filter to `data_status == 'active'` for analytical
queries. The other four statuses describe registry entries that do **not**
have associated measurement rows.

## Postgres tables (`aq` schema)

Analysis-ready tables mirror the parquet/CSV schemas exactly. See
[10_usage_sql.md](./10_usage_sql.md) for connection and query details.

| Table | Row count | Index |
|---|---:|---|
| `aq.site_registry` | 47 | `aqsid` |
| `aq.naaqs_design_values` | 764 | `aqsid`, `year`, `metric`, `pollutant_group` |
| `aq.pollutant_daily` | 236,070 | `aqsid`, `date_local`, `pollutant_group` |
| `aq.pollutant_monthly` | 6,070 | `aqsid`, `year_month`, `pollutant_group` |
| `aq.aq_weather_daily` | 236,070 | `aqsid`, `date_local` |
