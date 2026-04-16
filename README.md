# South Texas Air Quality Data Pipeline

> **Melaram Lab · Texas A&M University–Corpus Christi**

A reproducible, config-driven data pipeline assembling, validating,
normalizing, and analyzing ambient air quality data for 13 South Texas
counties over the period 2015–2025.

- **Lab:** [Melaram Lab](https://www.melaramlab.com), Texas A&M University–Corpus Christi
- **Principal Investigator:** Dr. Rajesh Melaram, TAMU-CC
- **Lead Developer:** Aidan Meyers
- **Collaborators:** Manassa Kuchavaram, L. Jin, Donald E. Warden
- **Version:** 0.3.4 (April 2026)
- **License:** [MIT](./LICENSE)
- **Docs site:** https://aidanjmeyers.github.io/south-texas-aq-pipeline/

## What this repository contains

```
pipeline/                ← The pipeline package (Python)
├── config.yaml          ← Single source of truth
├── run_pipeline.py      ← Orchestrator
├── step_00 … step_07    ← Eight pipeline steps
├── utils/               ← Shared helpers (IO, logging, NAAQS, validation, DB)
├── docs/                ← ← ← FULL DOCUMENTATION ← ← ←
│   ├── 01_overview.md
│   ├── 02_data_sources.md
│   ├── 03_data_schemas.md
│   ├── 04_pipeline_architecture.md
│   ├── 05_methodology.md
│   ├── 06_data_quality.md
│   ├── 07_usage_python.md
│   ├── 08_usage_r.md
│   ├── 09_usage_colab.md
│   ├── 10_usage_sql.md
│   ├── 11_reproducibility.md
│   ├── 12_configuration_reference.md
│   ├── 13_decisions.md
│   └── 14_publication_protocol.md
├── README.md            ← Short quick-start
├── DATA_CATALOG.md      ← Output file manifest
└── CHANGELOG.md         ← Version history with rationale
requirements.txt         ← Python dependencies
LICENSE                  ← MIT
.gitignore               ← Excludes raw data and pipeline outputs
```

## Quick start

> :warning: **You need the raw data first.** The git repository ships with
> pipeline code only — raw EPA/TCEQ/OpenWeather files (~2 GB total) live
> in a separate OneDrive share. See [PUBLISHING.md](./PUBLISHING.md) or the
> [downloads section on the docs site](https://aidanjmeyers.github.io/south-texas-aq-pipeline/#download-the-pipeline-inputs).

```powershell
# 1. Clone
git clone https://github.com/AidanJMeyers/south-texas-aq-pipeline.git
cd south-texas-aq-pipeline

# 2. Download + unzip the raw data bundle into the repo root
#    (link in the docs site — contact BREATHE-CC@tamucc.edu for access)
#    After extraction, !Final Raw Data/ and 01_Data/ should sit next to pipeline/

# 3. Install and run
pip install -r requirements.txt
python pipeline/run_pipeline.py
```

End-to-end runtime: **~20 minutes**. Outputs land under `data/` (parquet
+ CSV + optional Postgres load).

## Where to read next

| Question | Start here |
|---|---|
| **I want to run the pipeline** | [`pipeline/docs/11_reproducibility.md`](./pipeline/docs/11_reproducibility.md) |
| **I want to use the data in Python** | [`pipeline/docs/07_usage_python.md`](./pipeline/docs/07_usage_python.md) |
| **I want to use the data in R** | [`pipeline/docs/08_usage_r.md`](./pipeline/docs/08_usage_r.md) |
| **I want to use the data in Colab** | [`pipeline/docs/09_usage_colab.md`](./pipeline/docs/09_usage_colab.md) |
| **I want to query Postgres directly** | [`pipeline/docs/10_usage_sql.md`](./pipeline/docs/10_usage_sql.md) |
| **What does column X mean?** | [`pipeline/docs/03_data_schemas.md`](./pipeline/docs/03_data_schemas.md) |
| **How are NAAQS values computed?** | [`pipeline/docs/05_methodology.md`](./pipeline/docs/05_methodology.md) |
| **Are there known data quality issues?** | [`pipeline/docs/06_data_quality.md`](./pipeline/docs/06_data_quality.md) |
| **How is it documented for publication?** | [`pipeline/docs/14_publication_protocol.md`](./pipeline/docs/14_publication_protocol.md) |
| **Why did you make decision X?** | [`pipeline/docs/13_decisions.md`](./pipeline/docs/13_decisions.md) |

## Output summary

| Output layer | Location | Rows | Purpose |
|---|---|---:|---|
| Pollutant parquet store | `data/parquet/pollutants/` | 4,870,334 | Hourly, partitioned by group+year |
| Weather parquet store | `data/parquet/weather/` | 1,470,049 | Hourly, partitioned by station+year |
| NAAQS design values | `data/parquet/naaqs/` + `data/csv/naaqs_design_values.csv` | 764 | 9 metrics × 40 sites × 11 years |
| Daily aggregates | `data/parquet/daily/` + `data/csv/daily_pollutant_means.csv` | 236,070 | With 75% completeness flag |
| Combined AQ+weather | `data/parquet/combined/` + `data/csv/combined_aq_weather_daily.csv` | 236,070 | Haversine-paired |
| Site registry | `data/csv/site_registry.csv` | 47 | 42 active + 3 reference + 1 excluded + 1 disabled |
| Postgres tables | `aq` schema (Neon) | — | Analysis-ready only |

## Contact

Questions, bug reports, or collaborator requests: contact the
[Melaram Lab](https://www.melaramlab.com) at Texas A&M University–Corpus Christi.
