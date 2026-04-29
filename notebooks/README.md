# Notebooks

Reproducible Colab/Jupyter notebooks for the South Texas Air Quality
project. Each notebook is **self-contained** — open it in Colab, set up
the `AQ_POSTGRES_URL` Colab secret once, then run end-to-end.

## Index

| File | Author | Purpose | Open |
|---|---|---|---|
| `API_Test_AM.ipynb` | Aidan Meyers | API + Neon DB smoke test + Phase 1 descriptives + 3 starter figures | [![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/AidanJMeyers/south-texas-aq-pipeline/blob/main/notebooks/API_Test_AM.ipynb) |
| `EPA_Refresh_2025_AM.py` | Aidan Meyers | Targeted EPA AQS refresh — pulls only the 38 (county × parameter) gaps identified on 2026-04-22, skips dead sensors, outputs delta CSV in canonical pipeline schema, optional Neon upsert | [view](https://github.com/AidanJMeyers/south-texas-aq-pipeline/blob/main/notebooks/EPA_Refresh_2025_AM.py) |
| `TCEQ_Append_2025_AM.py` | Aidan Meyers | Convert manually-pulled TCEQ TAMIS RD files to canonical 15-col schema and append to By_Pollutant CSVs. Applies ozone ppb→ppm normalization. Uses canonical site_name lookup (no split-name dupes) | [view](https://github.com/AidanJMeyers/south-texas-aq-pipeline/blob/main/notebooks/TCEQ_Append_2025_AM.py) |
| `finish_hourly_tables_AM.py` | Aidan Meyers | Recovery script — reload `aq.pollutant_hourly` + `aq.weather_hourly` from local parquet via Postgres COPY (10–100× faster than pandas `to_sql`, resilient to network blips). Use this after rebuilding parquet via the pipeline. | [view](https://github.com/AidanJMeyers/south-texas-aq-pipeline/blob/main/notebooks/finish_hourly_tables_AM.py) |

## Naming convention

`<purpose>_<initials>.ipynb`

Examples:
- `API_Test_AM.ipynb` — Aidan's API smoke test
- `Imputation_Eval_MK.ipynb` — Manassa's imputation evaluation
- `Kriging_AM.ipynb` — Aidan's spatial interpolation work

Where multiple notebooks belong to a single weekly task, prefix with
the week number:

- `wk03_imputation_apply_AM.ipynb`
- `wk09_rf_baseline_MK.ipynb`

## How to add a new notebook

1. Create the `.ipynb` locally (or in Colab → File → Download as .ipynb)
2. Drop it in this `notebooks/` directory
3. Add a row to the index table above
4. `git add`, `git commit`, `git push` — it appears on GitHub automatically
5. The "Open in Colab" badge URL pattern is:

   ```
   https://colab.research.google.com/github/AidanJMeyers/south-texas-aq-pipeline/blob/main/notebooks/<filename>.ipynb
   ```

## Required Colab secrets

Set these once per Colab account (🔑 icon → Add new secret):

| Secret name | Value | Used by |
|---|---|---|
| `AQ_POSTGRES_URL` | `postgresql://neondb_owner:npg_...` (from Neon console) | Direct SQL via SQLAlchemy |
| `AQ_NEON_JWT` | A session JWT from the Neon Auth login page (~24 h validity) | Authenticated Data API path (optional) |

## Documentation

Full guide: [docs site → 17 — Colab + Neon database](https://aidanjmeyers.github.io/south-texas-aq-pipeline/17_colab_database_guide/)
