# 12 — Configuration Reference

Every key in `pipeline/config.yaml`, what it controls, and when to change it.

## File location

`pipeline/config.yaml` — loaded by `pipeline.utils.io.load_config()`.
The project root is resolved at runtime (see [11_reproducibility.md](./11_reproducibility.md)).

## Full annotated config

### `project:` — metadata only

```yaml
project:
  name: "South Texas Air Quality Analysis"
  lab: "Melaram Lab, TAMU-CC"
  principal_investigator: "Dr. Rajesh Melaram, TAMU-CC"
  lead_developers:
    - "Aidan Meyers, TAMU-CC"
    - "Manassa Kuchavaram, TAMU-CC"
  collaborators:
    - "L. Jin"
    - "Donald E. Warden"
  contact_email: "aidan.meyers@tamucc.edu"
  study_period: [2015, 2025]
  counties: [Atascosa, Bexar, Cameron, Comal, ...]
```

Used for logging/documentation only. Changing these does not affect
pipeline behavior.

### `paths:` — all file/directory locations (relative to ROOT)

#### Inputs (read-only)

| Key | Default | Notes |
|---|---|---|
| `raw_epa` | `!Final Raw Data/EPA AQS Downloads` | EPA source tree |
| `raw_tceq` | `!Final Raw Data/TCEQ Data - Missing Sites` | TCEQ RD files |
| `tceq_registry` | `!Final Raw Data/Extra TCEQ Sites.xlsx` | Site metadata workbook |
| `processed_pollutant` | `01_Data/Processed/By_Pollutant` | Merged 15-col CSVs |
| `processed_county` | `01_Data/Processed/By_County` | Same data, county-sliced |
| `processed_weather` | `01_Data/Processed/Meteorological` | Weather + mapping dir |
| `weather_master` | `01_Data/Processed/Meteorological/Weather_Irradiance_Master_2015_2025.csv` | Main weather CSV |
| `site_mapping` | `01_Data/Processed/Meteorological/AQ_Weather_SiteMapping.csv` | Legacy pairing (not used) |
| `site_reference` | `01_Data/Reference/enhanced_monitoring_sites.csv` | Primary coord source |

#### Outputs (pipeline-managed)

| Key | Default | Notes |
|---|---|---|
| `pipeline_output` | `data` | Top-level output dir |
| `parquet_pollutants` | `data/parquet/pollutants` | Step 01 |
| `parquet_weather` | `data/parquet/weather` | Step 02 |
| `parquet_naaqs` | `data/parquet/naaqs` | Step 03 |
| `parquet_daily` | `data/parquet/daily` | Step 04 |
| `parquet_combined` | `data/parquet/combined` | Step 05 |
| `parquet_rolling` | `data/parquet/rolling` | (reserved for future use) |
| `csv_exports` | `data/csv` | All flat CSVs |
| `rds_exports` | `data/rds` | R-native bundles (step 06) |
| `logs` | `data/_logs` | Per-step log files |
| `validation` | `data/_validation` | JSON validation reports |

Change these if you want outputs to land somewhere other than `data/`.

### `data_quality:` — completeness thresholds

```yaml
data_quality:
  hourly_completeness_threshold: 0.75   # fraction of valid hours for a day to be 'valid'
  daily_completeness_threshold:  0.75   # fraction of valid days in a window
  ozone_8hr_min_hours:           6      # minimum hours for an 8-hr rolling mean
  pm_daily_min_hours:           18      # minimum hours for a daily mean
  max_measurement_gap_hours:    48      # reserved; not currently used
  temperature_unit:         "kelvin"    # reserved; current data is Celsius
```

**Changing these re-scopes what counts as a valid observation.** Tightening
`hourly_completeness_threshold` to 0.9 would drop more days from monthly
rollups. EPA official guidance uses 0.75, which is the default.

### `naaqs:` — regulatory thresholds

```yaml
naaqs:
  ozone_8hr_ppm:    0.070
  pm25_annual_ugm3: 9.0
  pm25_24hr_ugm3:   35.0
  pm10_24hr_ugm3:   150.0
  co_8hr_ppm:       9.0
  co_1hr_ppm:       35.0
  so2_1hr_ppb:      75.0
  no2_1hr_ppb:      100.0
  no2_annual_ppb:   53.0
```

These define the `naaqs_level` column and `exceeds` boolean in
`design_values`. Update if EPA revises a standard (the PM₂.₅ annual was
revised from 12 to 9 in February 2024 — already reflected here).

### `expected:` — validation targets

```yaml
expected:
  total_pollutant_rows:     5843628
  pollutant_rows:
    CO:          191448
    NOx_Family: 1989602
    Ozone:      1823627
    PM10:        99910
    PM2.5:      1168298
    SO2:         524039
    VOCs:        46704
  active_sites:     41     # currently in data
  target_sites:     43     # 41 + 2 pending VOC downloads
  total_inventory:  47     # all known sites
  counties:         13
  pollutant_groups:  7
  weather_rows:     1470050
  weather_stations: 15
  row_count_tolerance_pct: 1.0
  date_min: "2015-01-01"
  date_max: "2025-11-30"
```

These drive the validation step. Update `total_pollutant_rows` and the
per-file counts whenever you add new data years; the tolerance (1%) allows
modest drift without breaking CI.

### `postgres:` — loader configuration

```yaml
postgres:
  enabled:      true
  schema:       "aq"
  chunksize:    50000
  if_exists:    "replace"
  tables:
    - name:   "site_registry"
      source: "csv"
      path:   "data/csv/site_registry.csv"
      indexes: ["aqsid"]
    - name:   "naaqs_design_values"
      source: "parquet"
      path:   "data/parquet/naaqs/design_values.parquet"
      indexes: ["aqsid", "year", "metric", "pollutant_group"]
    # ... etc
```

| Key | Description |
|---|---|
| `enabled` | Set to `false` to skip step 07 without deleting the config |
| `schema` | Target Postgres schema (created if missing) |
| `chunksize` | Max rows per INSERT batch (clamped per-table to stay under 65535 params) |
| `if_exists` | `replace` = drop+recreate (idempotent), `append` = incremental |
| `tables[].name` | Output table name in `<schema>.<name>` |
| `tables[].source` | `csv` or `parquet` |
| `tables[].path` | Relative path from ROOT |
| `tables[].indexes` | B-tree indexes to create (one per column) |
| `tables[].skip_on_quota_error` | If true, skip gracefully on free-tier storage errors |

**The connection URL is NOT in this file.** It's read exclusively from the
`AQ_POSTGRES_URL` environment variable — never from the filesystem. See
[10_usage_sql.md](./10_usage_sql.md#connection).

## Overriding the config at runtime

Pass `--config` to the orchestrator:

```bash
python pipeline/run_pipeline.py --config my_custom_config.yaml
```

Useful for running against a different Postgres instance or with
non-default completeness thresholds without editing the tracked config.

## Environment variable overrides

| Variable | Effect |
|---|---|
| `AQ_PIPELINE_ROOT` | Override ROOT auto-detection |
| `AQ_POSTGRES_URL` | Postgres connection URL (required for step 07) |

No other env vars are consumed by the pipeline.

## Adding new knobs

To introduce a new config key:

1. Add it to `config.yaml` under the appropriate section with a comment
2. Read it in the relevant step via `cfg.get("section", "key", default=...)`
3. Document the key here
4. Add an entry to `CHANGELOG.md` under the next version

Example:
```python
# In a pipeline step
min_rows = int(cfg.get("data_quality", "min_hourly_rows_per_day", default=1))
```
