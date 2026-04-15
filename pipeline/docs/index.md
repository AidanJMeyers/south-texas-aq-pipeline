# South Texas Air Quality Data Pipeline

!!! info "At a glance"

    A reproducible, config-driven data pipeline assembling, validating,
    normalizing, and analyzing ambient air quality data for **13 South
    Texas counties** over **2015–2025**.

    **Lab:** Melaram Lab, Texas A&M University–Corpus Christi
    **Pipeline version:** 0.3.3 (April 2026)
    **License:** MIT

## What this pipeline does

```
┌──────── INPUTS (immutable) ────────┐
│  EPA AQS, TCEQ CAMS, OpenWeather   │
│  ~5.8M hourly pollutant rows       │
│  ~1.5M hourly weather rows         │
└────────────────────────────────────┘
                 │
                 ▼
  python pipeline/run_pipeline.py  (~20 min)
                 │
                 ▼
┌──────── OUTPUTS (reproducible) ────┐
│  Parquet store (fast analytics)    │
│  NAAQS design values (764 rows)    │
│  Daily & monthly aggregates        │
│  AQ + weather joined daily         │
│  Flat CSVs for R/Colab             │
│  PostgreSQL tables (Neon)          │
└────────────────────────────────────┘
```

## Get started in 30 seconds

=== "Python users"

    ```python
    import pandas as pd
    dv = pd.read_csv("data/csv/naaqs_design_values.csv")
    # Sites exceeding the 8-hr ozone NAAQS in 2023
    print(dv.query("metric == 'ozone_8hr_4th_max' and year == 2023 and exceeds"))
    ```

    Full guide → [Python usage](./07_usage_python.md)

=== "R / RStudio users"

    ```r
    library(data.table)
    dv <- fread("data/csv/naaqs_design_values.csv")
    dv[metric == "ozone_8hr_4th_max" & year == 2023 & exceeds == TRUE]
    ```

    Full guide → [R usage](./08_usage_r.md)

=== "SQL / BI users"

    ```sql
    SELECT county_name, site_name, value
    FROM aq.naaqs_design_values
    WHERE metric = 'ozone_8hr_4th_max' AND year = 2023 AND exceeds = TRUE
    ORDER BY value DESC;
    ```

    Full guide → [SQL usage](./10_usage_sql.md)

=== "Google Colab users"

    ```python
    from google.colab import drive
    drive.mount('/content/drive')
    import os, pandas as pd
    os.chdir('/content/drive/MyDrive/AirQuality South TX')
    dv = pd.read_csv('data/csv/naaqs_design_values.csv')
    ```

    Full guide → [Colab usage](./09_usage_colab.md)

## What's in the data

!!! success "After the v0.3.3 pipeline run"

    | Output layer | Rows | Purpose |
    |---|---:|---|
    | `data/parquet/pollutants/` | ~7.7M | Hourly, partitioned by group + year |
    | `data/parquet/weather/` | 1.47M | Hourly, partitioned by station + year |
    | `data/parquet/naaqs/` | 764 | Design values per (site, year, metric) |
    | `data/parquet/daily/` | ~400k | Daily aggregates with completeness flags |
    | `data/parquet/combined/` | ~236k | AQ + weather joined by nearest station |
    | `data/csv/site_registry.csv` | 47 | Canonical site inventory with status tags |
    | PostgreSQL (`aq` schema) | 5 tables | SQL + BI access via Neon |

!!! info "Site counts"

    **42 active monitoring sites** (with in-scope pollutant data) across
    13 counties and 2 networks (EPA + TCEQ). The total inventory of 47
    sites includes 3 CPS Energy fence-line reference monitors, 1
    excluded site (Calaveras Lake Park — TSP-only, outside scope), and
    1 disabled site (Williams Park).

## Navigate the docs

<div class="grid cards" markdown>

-   :material-map-marker-radius: **Project**

    ---

    [Overview](./01_overview.md) · [Data sources](./02_data_sources.md) · [Schemas](./03_data_schemas.md) · [Architecture](./04_pipeline_architecture.md)

-   :material-flask: **Methodology**

    ---

    [NAAQS formulas & completeness rules](./05_methodology.md) · [Known data quality issues](./06_data_quality.md)

-   :material-code-tags: **Usage guides**

    ---

    [Python](./07_usage_python.md) · [R / RStudio](./08_usage_r.md) · [Google Colab](./09_usage_colab.md) · [SQL / Postgres](./10_usage_sql.md)

-   :material-chef-hat: **Recipes**

    ---

    [15 — Recipes & worked examples](./15_recipes.md) — copy-paste queries for common research tasks

-   :material-cog: **Operations**

    ---

    [Reproducibility](./11_reproducibility.md) · [Config reference](./12_configuration_reference.md) · [Architecture decisions](./13_decisions.md)

-   :material-school: **Publication**

    ---

    [Methods-section protocol](./14_publication_protocol.md) · [CITATION.cff](./CITATION.cff)

</div>

## Quick reference

!!! question "Where's column X?"

    See [03_data_schemas.md](./03_data_schemas.md) — every column, type, and unit.

!!! question "How do I reproduce this?"

    See [11_reproducibility.md](./11_reproducibility.md) — dependency list, known-good sanity values, and step-by-step rebuild instructions.

!!! question "Can I cite this in a paper?"

    Yes. See [14_publication_protocol.md](./14_publication_protocol.md) for
    Methods-section prose and [CITATION.cff](./CITATION.cff) for
    machine-readable citation metadata.

!!! question "Are there any known data quirks?"

    Yes, 16 of them are catalogued. See [06_data_quality.md](./06_data_quality.md).

## Pipeline version history

| Version | Date | Summary |
|---|---|---|
| 0.3.3 | 2026-04-15 | Calaveras Lake TCEQ feed filter, Calaveras Lake Park excluded (TSP-only), inventory report reconciled |
| 0.3.2 | 2026-04-15 | CC Palm VOCs raw data ingested (1 → 2 active VOC sites) |
| 0.3.1 | 2026-04-15 | Site registry correction, data provenance fixes |
| 0.3.0 | 2026-04-14 | Initial publication-grade docs suite; 47-site registry with status tags |
| 0.2.1 | 2026-04-14 | Ozone unit mismatch fix (EPA ppm vs TCEQ ppb) |
| 0.2.0 | 2026-04-13 | PostgreSQL loader added (Neon free tier) |
| 0.1.0 | 2026-04-13 | Initial pipeline release (parquet store + NAAQS computation) |
