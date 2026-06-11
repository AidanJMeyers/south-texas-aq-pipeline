# 03 — Data Schemas

> **v0.4.0 (2026-05-28):** Schemas updated for the TCEQ-only architecture.
> Canonical 14-column schema (was 15 — `data_source` dropped). Three new
> tables (`vocs_1hr`, `vocs_24hr`, `pollutant_daily_24hr`) and one new
> reference table (`parameter_reference`). See the
> [v0.4.0 migration guide](./v0_4_0_migration.md) for query rewrites.

Complete schemas for every output the pipeline produces. This is the
authoritative reference — if a column name or unit differs from what you
see here, the pipeline has drifted and this doc is wrong.

---

## Canonical 14-column schema

The same 14-column schema is used for `aq.pollutant_hourly`,
`aq.pollutant_daily_24hr`, `aq.vocs_1hr`, and `aq.vocs_24hr` at ingest.
The hourly stores add 5 derived columns (`datetime`, `year`, `month`,
`hour`, `season`) when written to parquet by step 01 / 01c.

| Column | Type | Unit | Description |
|---|---|---|---|
| `state_code` | int32 | — | FIPS state code (always 48 = Texas) |
| `county_code` | int32 | — | FIPS county code (3-digit) |
| `site_number` | int32 | — | AQS site number |
| `parameter_code` | int32 | — | AQS parameter code (see `aq.parameter_reference`) |
| `poc` | int32 | — | Parameter Occurrence Code (sub-instrument identifier) |
| `date_local` | string | — | ISO date `YYYY-MM-DD` (local time) |
| `time_local` | string | — | `HH:MM` (local time; `00:00` for daily readings) |
| `sample_measurement` | float64 | varies | **Normalized to EPA units** (see §Unit conventions) |
| `method_code` | int32 | — | AQS measurement method code |
| `county_name` | string | — | Title case (e.g. "Bexar", "Nueces") |
| `pollutant_name` | string | — | Specific pollutant name (e.g. "Ozone", "Benzene") |
| `aqsid` | string | — | 9-digit AQS site identifier (`state+county+site`, zero-padded) |
| `pollutant_group` | string | — | **Partition key.** One of: `Ozone`, `NOx_Family`, `CO`, `SO2`, `PM2.5`, `PM10`, `VOCs` |
| `site_name` | string | — | Canonical name with trailing AQSID suffix, e.g. `Camp Bullis_0052` |

> **v0.4.0 change:** The `data_source` column was dropped (15 → 14 cols)
> because every row is TCEQ-sourced now. If you have v0.3.7 code that
> selects `data_source`, remove it; if you filter `WHERE data_source='TCEQ'`,
> the predicate is now unconditional.

---

## Parquet Stores (local layer)

### `data/parquet/pollutants/` — Criteria hourly

**Partition keys:** `pollutant_group=…/year=…/*.parquet`
**Rows:** 4,710,663 (v0.4.0)
**Produced by:** `step_01_build_pollutant_store.py`
**Schema:** 14 canonical cols + 5 derived (`datetime`, `year`, `month`, `hour`, `season`)

VOCs are **not** in this store anymore — they live under `vocs_1hr` / `vocs_24hr`
(decision #10). Site 480290060 PM10 is **not** here either — it routes to
`pollutant_daily_24hr` (decision #5/#6).

### `data/parquet/vocs_1hr/` and `data/parquet/vocs_24hr/` — VOC AutoGC (NEW)

**Partition keys:** `pollutant_name=…/year=…/*.parquet`
**Rows:**
- `vocs_1hr`: 4,964,065 (5 sites × 46 chemicals)
- `vocs_24hr`: 97,244 (8 sites × 48 chemicals)

**Produced by:** `step_01c_build_aux_stores.py`
**Schema:** Same 14-col canonical (all rows have `pollutant_group="VOCs"`) + 5 derived

We partition by `pollutant_name` (chemical species) rather than
`pollutant_group` because every VOC row has the same group value —
partitioning by group would mean one giant partition. Splitting by chemical
keeps partitions small and lets downstream queries push down
`pollutant_name="Benzene"` filters cheaply.

### `data/parquet/pollutant_daily_24hr/` — 24hr-only criteria (NEW)

**Partition keys:** `pollutant_group=…/year=…/*.parquet`
**Rows:** 636 (v0.4.0 — Site 480290060 PM10 only, will grow as new
24hr-only feeds are added)
**Produced by:** `step_01c_build_aux_stores.py`
**Schema:** Same 14-col canonical + 5 derived. `time_local` is `00:00`
for daily readings.

Routing rule: any row whose AQS RD `Dur Cd` field is `7` (24hr block) or
`X` (24hr average from midnight) lands here, not in `pollutant_hourly`.

### `data/parquet/weather/` — Weather hourly (UNCHANGED in v0.4.0)

**Partition keys:** `location=…/year=…/*.parquet`
**Rows:** 1,470,049
**Produced by:** `step_02_build_weather_store.py`

Inherits all 45 columns from `Weather_Irradiance_Master_2015_2025.csv`.
Most-used subset:

| Column | Type | Unit | Description |
|---|---|---|---|
| `dt` | int64 | unix seconds | UTC timestamp |
| `datetime_local` | string | — | Local datetime |
| `datetime_utc` | string | — | UTC datetime |
| `year`, `month`, `hour` | int16/8/8 | — | Derived from `datetime_local` |
| `date_local` | string | — | Local date `YYYY-MM-DD` |
| `location` | string | — | **Partition key.** Weather station name |
| `county_name` | string | — | County the station is in |
| `lat`, `lon` | float64 | degrees | Station coordinates |
| `temp` | float64 | **°C** | Air temperature (Celsius in master) |
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
| `rain_1h`, `rain_3h` | float64 | mm | Rainfall last 1/3 hours |
| `snow_1h` | float64 | mm | Snowfall last hour |
| `is_raining` | bool | — | Flag |
| `weather_id`, `weather_main`, `weather_description` | — | — | OpenWeather condition |
| `heat_index_c` | float64 | °C | Rothfusz (null when `T<26°C` or `RH<40%`) |
| `ghi_cloudy_sky`, `ghi_clear_sky` | float64 | W/m² | Global horizontal irradiance |
| `dni_cloudy_sky`, `dni_clear_sky` | float64 | W/m² | Direct normal irradiance |
| `dhi_cloudy_sky`, `dhi_clear_sky` | float64 | W/m² | Diffuse horizontal irradiance |

### `data/parquet/naaqs/design_values.parquet`

**Rows:** 759 (v0.4.0)
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
| `pm25_annual_mean` | PM₂.₅ | Annual mean of daily means (≥18 hrs) | **9.0 µg/m³** (Feb 2024 standard) | PM₂.₅ sites |
| `pm25_24hr_p98` | PM₂.₅ | 98th percentile of daily means per year | 35 µg/m³ | PM₂.₅ sites |
| `pm10_24hr_exceedances` | PM₁₀ | Count of daily means > 150 µg/m³ per year | — | PM₁₀ sites incl. site 0060 24hr |
| `co_1hr_max` | CO | Daily max 1-hr | 35 ppm | CO sites |
| `co_8hr_max` | CO | Daily max 8-hr rolling avg | 9 ppm | CO sites |
| `so2_1hr_99p_3yr` | SO₂ | 99th percentile of daily max 1-hr, 3-yr avg | 75 ppb | SO₂ sites |
| `no2_1hr_98p_3yr` | NO₂ | 98th percentile of daily max 1-hr, 3-yr avg | 100 ppb | NOx_Family sites (parameter_code = 42602) |
| `no2_annual_mean` | NO₂ | Annual mean of hourly | 53 ppb | NOx_Family sites (parameter_code = 42602) |

### `data/parquet/daily/`

**Files:** `pollutant_daily.parquet` (201,290 rows) +
`pollutant_monthly.parquet` (6,804 rows)
**Produced by:** `step_04_compute_daily_aggregates.py`

Daily schema: `aqsid, date_local, parameter_code, pollutant_name,
pollutant_group, county_name, site_name, mean, min, max, std, n_hours,
completeness_pct, valid_day` (14 cols).

Monthly schema: `aqsid, year_month, parameter_code, pollutant_name,
pollutant_group, county_name, site_name, monthly_mean, monthly_min,
monthly_max, monthly_std, n_valid_days` (12 cols).

---

## Reference / metadata CSVs

### `data/csv/site_registry.csv` — Site inventory (v0.4.0 schema)

**Rows:** 42 (41 active + 1 disabled)
**Produced by:** `step_05b_build_metadata.py`

| Column | Type | Description |
|---|---|---|
| `aqsid` | string | 9-digit AQS site ID (primary key) |
| `state_code`, `county_code`, `site_number` | int | FIPS components |
| `site_name`, `county_name` | string | Canonical names |
| `pollutant_groups_hourly` | string | Semicolon-joined list, e.g. `Ozone;NOx_Family;PM2.5` — what's in `pollutant_hourly` |
| `pollutant_groups_daily_24hr` | string | Semicolon-joined list — what's in `pollutant_daily_24hr` |
| `voc_cadence` | string | `'1hr'`, `'24hr'`, `'both'`, or empty string |
| `n_pollutant_groups` | int | Total distinct pollutant groups measured |
| `first_date`, `last_date` | string | Date range of data |
| `n_records` | int | Total rows across all pollutant stores |
| `data_status` | string | `'active'` or `'disabled'` |
| `notes` | string | Free text |
| `lat`, `lon` | float | Coordinates (from `enhanced_monitoring_sites.csv` + `Extra TCEQ Sites.xlsx`) |

> **v0.4.0 change:** The v0.3.7 `data_source` / `pollutants` / `n_pollutants` /
> `co_located_with` / `network` columns are gone. The new
> `pollutant_groups_hourly` / `pollutant_groups_daily_24hr` / `voc_cadence`
> trio captures everything you need to route queries to the right table.

### `data/csv/parameter_reference.csv` — AQS code → name + HAP (NEW in v0.4.0)

**Rows:** 57 (9 criteria + 47 VOCs + 1 sparse PM10 variant)
**Source:** [EPA AQS code tables](https://aqs.epa.gov/aqsweb/documents/codetables/parameters.html)
**Produced by:** `step_05b_build_metadata.py` (copies from
`!Archive_v0_3_7/inventory/parameter_reference.csv`)

| Column | Type | Description |
|---|---|---|
| `parameter_code` | int | AQS parameter code (primary key) |
| `parameter_name` | string | Human-readable name |
| `chemical_family` | string | `Criteria` / `VOC-Paraffin` / `VOC-Cycloalkane` / `VOC-Olefin` / `VOC-Aromatic` |
| `pollutant_group` | string | Pipeline routing group |
| `default_units` | string | Canonical units (ppm / ppb / ppbC / µg/m³ LC) |
| `naaqs_regulated` | bool | Is there a current EPA NAAQS for this parameter |
| `is_hap` | bool | Listed in Clean Air Act §112(b) as a Hazardous Air Pollutant |
| `notes` | string | Unit-conversion or sparseness notes |

---

## Postgres tables (`aq.*` schema on Neon)

After step 07 runs, the `aq` schema contains 10 tables. Schemas mirror the
parquet/CSV sources above:

| Table | Source | Rows | Size |
|---|---|---:|---:|
| `aq.site_registry` | csv | 42 | 32 kB |
| `aq.parameter_reference` | csv (NEW) | 57 | 48 kB |
| `aq.naaqs_design_values` | parquet | 759 | 288 kB |
| `aq.pollutant_daily` | parquet | 201,290 | 35 MB |
| `aq.pollutant_daily_24hr` | parquet_dir (NEW) | 636 | 264 kB |
| `aq.pollutant_monthly` | parquet | 6,804 | 1.2 MB |
| `aq.pollutant_hourly` | parquet_dir | 4,710,663 | 841 MB |
| `aq.vocs_1hr` | parquet_dir (NEW) | 4,964,065 | 877 MB |
| `aq.vocs_24hr` | parquet_dir (NEW) | 97,244 | 17 MB |
| `aq.weather_hourly` | parquet_dir | 1,470,049 | 630 MB |

The legacy v0.3.7 EPA-blended schema is preserved at `aq_v0_3_7_epa.*`
(7 tables, ~2.2 GB) — same column names as the old `aq.*` schema.

---

## Unit conventions (post-ingest)

| Pollutant group | Parameter codes | Stored unit | Note |
|---|---|---|---|
| Ozone | 44201 | **ppm** | TCEQ ppb → ppm × 0.001 applied at step 01b |
| NOx_Family | 42601, 42602, 42603 | ppb | Native ppb |
| CO | 42101 | ppm | Native ppm |
| SO2 | 42401 | ppb | Native ppb |
| PM2.5 | 88101, 88502 | µg/m³ | Local conditions |
| PM10 | 81102 | µg/m³ | Local conditions |
| VOCs (paraffins / cycloalkanes / olefins) | 43xxx | ppbC | Carbon-normalized |
| VOCs (aromatics) | 45xxx | ppbC | Carbon-normalized |

The ozone conversion is the **only** unit transformation in the v0.4.0
pipeline. Other parameters are TCEQ-native, which equals the EPA canonical
convention. See [methodology §1](./05_methodology.md#1-unit-normalization).
