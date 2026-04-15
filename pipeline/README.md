# South Texas Air Quality — Data Pipeline

A reproducible, config-driven pipeline that turns the project's scattered
CSVs into a fast, queryable parquet store + NAAQS design values + an
analysis-ready daily dataset.

Before this pipeline: ~18 Python scripts, 3 R notebooks, hardcoded paths, no
NAAQS computation, no unified store, ~30 s to load the weather CSV.

After this pipeline: one command, ~10× faster loads, proper NAAQS design
values per site-year, one authoritative merged AQ+weather dataset.

---

## Quick start

```bash
cd "AirQuality South TX"
pip install -r requirements.txt
python pipeline/run_pipeline.py
```

Total runtime: **~10–15 minutes** end-to-end on a modern laptop with SSD.

All outputs land under `data/`. Nothing under `01_Data/Processed/` or
`!Final Raw Data/` is ever modified.

### Common invocations

```bash
# Dry run — resolve paths and print the plan without touching data
python pipeline/run_pipeline.py --dry-run

# Re-run just the NAAQS step after tweaking thresholds
python pipeline/run_pipeline.py --only 03

# Skip the R-native export (if you don't have R installed)
python pipeline/run_pipeline.py --skip 06

# Point at a different config file
python pipeline/run_pipeline.py --config my_config.yaml
```

---

## Architecture

```
┌────────────────────── INPUTS (read-only) ─────────────────────┐
│  !Final Raw Data/EPA AQS Downloads/                           │
│  !Final Raw Data/TCEQ Data - Missing Sites/                   │
│  01_Data/Processed/By_Pollutant/*.csv        (7 files, 565 MB)│
│  01_Data/Processed/Meteorological/                            │
│    Weather_Irradiance_Master_2015_2025.csv   (440 MB)         │
│    AQ_Weather_SiteMapping.csv                                 │
└───────────────────────────────────────────────────────────────┘
                               │
                  pipeline/run_pipeline.py
                               │
      ┌────────────┬───────────┼───────────┬────────────┐
      ▼            ▼           ▼           ▼            ▼
   step_00      step_01     step_02     step_03      step_04
   validate   pollutant→pq  weather→pq   NAAQS      daily aggs
      │            │           │           │            │
      └────────────┴─────┬─────┴───────────┘            │
                         ▼                               ▼
                     step_05  ◄────────────────── step_06
                  merge AQ+WX                   flat CSV + RDS
                         │
                         ▼
┌────────────────────── OUTPUTS ───────────────────────────────┐
│  data/parquet/pollutants/   Hive-partitioned by group, year  │
│  data/parquet/weather/      Hive-partitioned by location,yr  │
│  data/parquet/naaqs/        Design values per (site, year)   │
│  data/parquet/daily/        Daily + monthly aggregates       │
│  data/parquet/combined/     Merged AQ + weather daily        │
│  data/csv/                  Flat CSV exports for R/Colab     │
│  data/rds/                  R-native .rds bundles (optional) │
│  data/_logs/                Per-step logs                    │
│  data/_validation/          Validation report JSON            │
└───────────────────────────────────────────────────────────────┘
```

See `DATA_CATALOG.md` for the authoritative schema of every output file.

---

## Steps

| ID | Script | Purpose |
|----|--------|---------|
| 00 | `step_00_validate_raw.py`          | Assert row counts, schemas, date ranges |
| 01 | `step_01_build_pollutant_store.py` | CSV → partitioned parquet (pollutants) |
| 02 | `step_02_build_weather_store.py`   | CSV → partitioned parquet (weather), K→C, u/v wind |
| 03 | `step_03_compute_naaqs.py`         | Design values: O3 4th-max, PM p98, etc. |
| 04 | `step_04_compute_daily_aggregates.py` | Daily & monthly pollutant stats w/ 75% rule |
| 05 | `step_05_merge_aq_weather.py`      | Joined AQ+WX dataset + 43-site registry |
| 06 | `step_06_export_analysis_ready.py` | Verify CSVs + optional R .rds export |
| 07 | `step_07_load_postgres.py`         | Load analysis-ready tables into Postgres (optional) |

Each step is idempotent — running twice produces identical output. Each step
logs row counts in, row counts out, and wall-clock duration to
`data/_logs/{step_name}.log` AND stdout.

---

## Colab vs. local

The pipeline auto-detects where it is running. Resolution order:

1. `AQ_PIPELINE_ROOT` environment variable (explicit override)
2. Google Colab: `/content/drive/MyDrive/AirQuality South TX`
3. Local Windows OneDrive: `~/OneDrive/Desktop/AirQuality South TX`
4. Current working directory (if it contains `01_Data/Processed`)
5. Walk up from CWD looking for `PIPELINE_PROMPT.md`

### Colab setup

```python
from google.colab import drive
drive.mount('/content/drive')

import os, sys
os.chdir('/content/drive/MyDrive/AirQuality South TX')
!pip install -q pyarrow pyyaml

!python pipeline/run_pipeline.py
```

---

## Using the outputs

### Python (parquet, preferred)

```python
import pandas as pd

# All ozone for 2023 across all sites
df = pd.read_parquet(
    "data/parquet/pollutants",
    filters=[("pollutant_group", "=", "Ozone"), ("year", "=", 2023)],
)

# NAAQS design values
dv = pd.read_csv("data/csv/naaqs_design_values.csv")
bexar_o3 = dv.query("county_name == 'Bexar' and metric == 'ozone_8hr_4th_max'")

# Combined AQ + weather
combined = pd.read_csv("data/csv/combined_aq_weather_daily.csv")
```

### R (parquet, preferred)

```r
library(arrow)
library(dplyr)

p <- open_dataset("data/parquet/pollutants/")
bexar_o3 <- p |>
  filter(pollutant_group == "Ozone", county_name == "Bexar", year == 2023) |>
  collect()

# Or flat CSVs if arrow isn't installed
library(data.table)
dv <- fread("data/csv/naaqs_design_values.csv")
daily <- fread("data/csv/daily_pollutant_means.csv")
```

---

## Configuration

Everything lives in `pipeline/config.yaml`:

* `paths:` — input and output locations (relative to ROOT)
* `data_quality:` — completeness thresholds (75% rule)
* `naaqs:` — NAAQS standard levels (ppm/ppb/µg/m³)
* `expected:` — row-count assertions for validation

To change a threshold, edit `config.yaml` and rerun only the affected step:
`python pipeline/run_pipeline.py --only 03`.

---

## Postgres (step 07, optional)

The pipeline can load the analysis-ready tables into a Postgres database so
collaborators and BI tools can query them with plain SQL. The raw hourly data
stays in parquet — Postgres is for the small/medium aggregates only.

### One-time setup

1. Create a free Neon project at https://neon.tech (0.5 GB free, no card).
2. Copy the connection string from the Neon dashboard.
3. Set it as a **user** environment variable (PowerShell):

   ```powershell
   [Environment]::SetEnvironmentVariable(
     "AQ_POSTGRES_URL",
     "postgresql://user:pass@ep-xxx.us-east-2.aws.neon.tech/neondb?sslmode=require",
     "User"
   )
   ```

   Close and reopen PowerShell. Verify with `echo $env:AQ_POSTGRES_URL`.

4. Install the Postgres driver:

   ```powershell
   pip install "psycopg[binary]>=3.1" "sqlalchemy>=2.0"
   ```

### Usage

```powershell
# Run just the Postgres loader after everything else is built
python pipeline/run_pipeline.py --only 07

# Skip the loader on a run
python pipeline/run_pipeline.py --skip 07
```

If `AQ_POSTGRES_URL` is unset, step 07 logs a warning and exits cleanly —
it is never a hard failure.

### Tables loaded (all in the `aq` schema)

| Table | Rows (approx) | Source |
|---|---|---|
| `aq.site_registry` | 43 | `data/csv/site_registry.csv` |
| `aq.naaqs_design_values` | ~1.5k | `data/parquet/naaqs/` |
| `aq.pollutant_daily` | ~4M | `data/parquet/daily/` |
| `aq.pollutant_monthly` | ~130k | `data/parquet/daily/` |
| `aq.aq_weather_daily` | ~4M | `data/parquet/combined/` (skipped gracefully on free-tier quota error) |

### Example SQL

```sql
-- Sites that exceeded the 8-hr ozone NAAQS in 2023
SELECT aqsid, site_name, county_name, value
FROM aq.naaqs_design_values
WHERE metric = 'ozone_8hr_4th_max' AND year = 2023 AND exceeds = true
ORDER BY value DESC;

-- Monthly mean PM2.5 for Bexar County 2020–2024
SELECT year_month, AVG(monthly_mean) AS mean_pm25
FROM aq.pollutant_monthly
WHERE county_name = 'Bexar' AND pollutant_group = 'PM2.5'
  AND year_month BETWEEN '2020-01' AND '2024-12'
GROUP BY year_month
ORDER BY year_month;
```

### Configuration

Table list, schema name, chunk size, and `replace`/`append` behavior live
under `postgres:` in `config.yaml`. The connection URL does **not** — that
is read only from the environment.

### Free-tier notes (Neon)

* **0.5 GB storage limit.** The four small tables (site_registry, NAAQS,
  daily, monthly) total ~400 MB and fit. The large `aq_weather_daily`
  (~400 MB) may push past the limit — if so, step 07 skips it with a
  warning and the load still completes.
* **Auto-pause after 5 min idle.** First query after a pause takes ~500 ms;
  the pipeline uses `pool_pre_ping=True` to handle this transparently.
* **To upgrade past 0.5 GB:** Neon Launch plan is $19/mo for 10 GB.
  Alternatively, edit `config.yaml:postgres.tables` to load only a subset.

---

## Troubleshooting

**`FileNotFoundError: Could not resolve AQ pipeline ROOT`**
Set the env var: `AQ_PIPELINE_ROOT="/path/to/AirQuality South TX"`.

**`Rscript not on PATH`**
Harmless — step 06 will skip RDS export and the flat CSVs are sufficient.

**Validation fails with a row-count mismatch**
Check `data/_validation/validation_report.json`. Increase the
`expected.row_count_tolerance_pct` in `config.yaml` if you have legitimately
updated the raw data.

**OneDrive file-locking errors**
Pause OneDrive sync before running, or run from a local copy.

---

## Out of scope (not in this pipeline)

* Refactoring `AM_R_Notebooks/NB1/NB2/NB3` to load from `data/parquet/` —
  follow-up work; the notebooks still work against their original inputs.
* Spatial kriging and predictive models — those belong in downstream
  analysis scripts, not the data pipeline.
* Deleting any existing scripts in `02_Scripts/Python/`.

---

*Last updated: April 2026 — v0.1.0*
