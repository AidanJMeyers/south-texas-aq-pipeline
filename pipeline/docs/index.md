---
hide:
  - toc
---

<img src="assets/melaram-lab-logo.png" alt="Melaram Lab" class="hero-logo" />

# South Texas Air Quality Data Pipeline

<span class="brand-badge">Melaram Lab</span>
<span class="brand-badge brand-badge-accent">v0.3.4</span>

!!! info "About this project"

    A reproducible, config-driven data pipeline assembling, validating,
    normalizing, and analyzing ambient air quality data for
    **13 South Texas counties** over **2015–2025**.

    **Lab:** Melaram Lab, Texas A&M University–Corpus Christi
    **Principal Investigator:** Dr. Rajesh Melaram, TAMU-CC
    **Lead Developers:** Aidan Meyers, Manassa Kuchavaram
    **Collaborators:** L. Jin, Donald E. Warden
    **Contact:** [aidan.meyers@tamucc.edu](mailto:aidan.meyers@tamucc.edu) · [www.melaramlab.com](https://www.melaramlab.com)
    **License:** MIT

## Pipeline schematic

```mermaid
%%{init: {'theme':'base','themeVariables':{
    'fontFamily':'Arial, sans-serif',
    'fontSize':'14px',
    'primaryColor':'#FFFFFF',
    'primaryTextColor':'#213c4e',
    'primaryBorderColor':'#213c4e',
    'lineColor':'#6b7a85',
    'clusterBkg':'#F5F7F9',
    'clusterBorder':'#213c4e'
}}}%%
flowchart TD
    classDef input  fill:#E8F1F5,stroke:#213c4e,stroke-width:2px,color:#213c4e,font-weight:600
    classDef step   fill:#FFFFFF,stroke:#213c4e,stroke-width:2.5px,color:#213c4e,font-weight:600
    classDef output fill:#FDEBD3,stroke:#c2410c,stroke-width:2.5px,color:#7c2d0b,font-weight:700
    classDef db     fill:#FDEBD3,stroke:#c2410c,stroke-width:2.5px,color:#7c2d0b,font-weight:700

    subgraph INPUTS["&nbsp;RAW INPUTS (read-only)&nbsp;"]
        direction LR
        A1["<b>EPA AQS Data Mart</b><br/>29 sites · 2015–2025"]
        A2["<b>TCEQ TAMIS</b><br/>14 sites · 2016–2025"]
        A3["<b>OpenWeather API</b><br/>15 stations · 2015–2025"]
        A4["<b>Extra TCEQ Sites.xlsx</b><br/>site coordinates"]
    end

    subgraph PIPELINE["&nbsp;pipeline/run_pipeline.py · ~20 min&nbsp;"]
        direction TB
        S0["<b>step_00</b> · validate raw"]
        S1["<b>step_01</b> · pollutant parquet<br/>dedup · unit normalize · filter"]
        S2["<b>step_02</b> · weather parquet"]
        S3["<b>step_03</b> · NAAQS design values<br/>40 CFR Part 50"]
        S4["<b>step_04</b> · daily + monthly<br/>75% completeness rule"]
        S5["<b>step_05</b> · Haversine AQ ↔ WX"]
        S6["<b>step_06</b> · CSV + RDS export"]
        S7["<b>step_07</b> · PostgreSQL load"]

        S0 --> S1 --> S2 --> S3 --> S4 --> S5 --> S6 --> S7
    end

    subgraph OUTPUTS["&nbsp;ANALYSIS-READY OUTPUTS&nbsp;"]
        direction LR
        O1["<b>data/parquet/</b><br/>fast local analytics<br/>~7.7M rows"]
        O2["<b>data/csv/</b><br/>flat exports<br/>R + Colab users"]
        O3["<b>PostgreSQL (Neon)</b><br/>aq schema · 5 tables<br/>SQL + BI access"]
    end

    A1 --> S0
    A2 --> S0
    A3 --> S2
    A4 --> S5

    S2 --> O1
    S5 --> O1
    S6 --> O2
    S7 --> O3

    class A1,A2,A3,A4 input
    class S0,S1,S2,S3,S4,S5,S6,S7 step
    class O1,O2 output
    class O3 db
```

!!! abstract "At-a-glance numbers"

    | Count | What |
    |---:|---|
    | **42** | Active monitoring sites with in-scope data |
    | **13** | South Texas counties covered |
    | **15** | OpenWeather stations used for meteorological pairing |
    | **7.7M** | Hourly pollutant rows in parquet (post-dedup + filters) |
    | **1.47M** | Hourly weather rows in parquet |
    | **764** | NAAQS design values computed (9 metrics × 40 sites × 11 years) |
    | **~20 min** | End-to-end pipeline runtime on a laptop SSD |

## :material-download: Download the pipeline inputs

!!! warning "You need ~2 GB of raw data before you can run the pipeline"

    The git repository ships with the **pipeline code** only. To actually
    run it, you need the raw EPA AQS, TCEQ TAMIS, and OpenWeather files
    that live under `!Final Raw Data/` and `01_Data/` in the project tree.
    These are too large to commit to git.

### OneDrive bundle (for Melaram Lab members)

<a href="https://melaramlab-my.sharepoint.com/:u:/p/coreteam/IQDdWC35UwcvQ52psdTLNknpAbxOhQ9RDX7GUhFESx4iYec?e=xWfs2E" class="download-cta">
  :material-microsoft-onedrive: Download pipeline inputs from OneDrive (177 MB)
</a>

The OneDrive share contains a single zip file `south-texas-aq-inputs.zip`
(**177 MB compressed** → ~1.8 GB uncompressed) with this exact layout:

```
south-texas-aq-inputs/
├── !Final Raw Data/
│   ├── EPA AQS Downloads/
│   │   ├── AQS_SouthTexas_2015_2025_COMPLETE.csv
│   │   ├── by_pollutant/
│   │   └── individual_downloads/
│   ├── TCEQ Data - Missing Sites/
│   └── Extra TCEQ Sites.xlsx
└── 01_Data/
    ├── Processed/
    │   ├── By_Pollutant/
    │   ├── By_County/
    │   └── Meteorological/
    └── Reference/
        └── enhanced_monitoring_sites.csv
```

**To install:**

```powershell
# 1. Clone the code repo
git clone https://github.com/AidanJMeyers/south-texas-aq-pipeline.git
cd south-texas-aq-pipeline

# 2. Download the OneDrive zip into the repo root and unzip it
#    (both "!Final Raw Data/" and "01_Data/" should land next to pipeline/)
Expand-Archive south-texas-aq-inputs.zip -DestinationPath .

# 3. Install dependencies and run
pip install -r requirements.txt
python pipeline/run_pipeline.py
```

!!! note "OneDrive access is currently restricted to Melaram Lab members."

    If you're an external collaborator and need access, email
    [aidan.meyers@tamucc.edu](mailto:aidan.meyers@tamucc.edu) with your
    affiliation and intended use.

---

## Get started in 30 seconds

Already have the data downloaded? Pick your tool:

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

---

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

    [Python](./07_usage_python.md) · [R / RStudio](./08_usage_r.md) · [Google Colab](./09_usage_colab.md) · [SQL / Postgres](./10_usage_sql.md) · [**Colab + Neon DB**](./17_colab_database_guide.md)

-   :material-chef-hat: **Recipes**

    ---

    [15 — Recipes & worked examples](./15_recipes.md) — copy-paste queries for common research tasks

-   :material-calendar-check: **Project timeline**

    ---

    [16 — Analysis deliverables & delegation](./16_project_timeline.md) — week-by-week tasks through August 1

-   :material-cog: **Operations**

    ---

    [Reproducibility](./11_reproducibility.md) · [Config reference](./12_configuration_reference.md) · [Architecture decisions](./13_decisions.md)

-   :material-school: **Publication**

    ---

    [Methods-section protocol](./14_publication_protocol.md)

</div>

---

## Pipeline version history

| Version | Date | Summary |
|---|---|---|
| 0.3.5 | 2026-04-22 | Hourly tables loaded to Neon (~2.3 GB total); Data API + Neon Auth enabled; analysis timeline restructured |
| 0.3.4 | 2026-04-15 | MkDocs site with GitHub Pages deployment + Melaram Lab branding |
| 0.3.3 | 2026-04-15 | Calaveras Lake TCEQ feed filter, Calaveras Lake Park officially retired (TSP-only) |
| 0.3.2 | 2026-04-15 | CC Palm VOCs raw data ingested (1 → 2 active VOC sites) |
| 0.3.1 | 2026-04-15 | Site registry correction, data provenance fixes |
| 0.3.0 | 2026-04-14 | Initial publication-grade docs suite; 47-site registry with status tags |
| 0.2.1 | 2026-04-14 | Ozone unit mismatch fix (EPA ppm vs TCEQ ppb) |
| 0.2.0 | 2026-04-13 | PostgreSQL loader added (Neon free tier) |
| 0.1.0 | 2026-04-13 | Initial pipeline release (parquet store + NAAQS computation) |

---

<div style="text-align: center; margin-top: 3em; color: #555555;">
  <strong>Melaram Lab</strong> · Texas A&amp;M University–Corpus Christi
  <br/>
  <a href="https://www.melaramlab.com">www.melaramlab.com</a>
  ·
  <a href="https://github.com/AidanJMeyers/south-texas-aq-pipeline">GitHub</a>
</div>
