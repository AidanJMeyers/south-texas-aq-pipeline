# 14 — Publication Protocol Summary

Prose suitable for the Methods section of a manuscript describing the
South Texas Air Quality data pipeline. See
[05_methodology.md](./05_methodology.md) for detailed formulas and
regulatory references.

---

## Data Sources and Assembly

Hourly ambient air quality measurements were assembled for 13 South Texas
counties over the period 1 January 2015 – 30 November 2025. Monitoring data
were drawn from two regulatory networks: (1) the U.S. Environmental
Protection Agency Air Quality System (EPA AQS, retrieved via the AQS Data
Mart API on 18 February 2026), covering 29 sites with criteria pollutant
observations (O₃, CO, SO₂, NO₂, NOx, PM₂.₅, PM₁₀); and (2) the Texas
Commission on Environmental Quality Air Monitoring Information System
(TCEQ TAMIS, manually retrieved in AQS Raw Data Transaction format on 6
April 2026), covering 14 additional CAMS sites where EPA coverage was
sparse, including volatile organic compound measurements at Corpus Christi
Hillcrest.

Meteorological and solar irradiance observations at hourly resolution were
obtained from the OpenWeather Historical Hourly Weather API (15 stations,
2015–2025), pre-processed into a unified 45-variable master file with
derived fields including wind u/v components, Rothfusz heat index, and
clear-sky/all-sky global horizontal irradiance (GHI).

Following retrieval, raw files were staged in an immutable archive
directory and were not modified by any subsequent processing.

## Data Pipeline Architecture

Raw CSV and TCEQ Raw Data transaction files were processed by a
config-driven Python pipeline (version 0.3.0, April 2026) consisting of
eight sequential steps orchestrated by `pipeline/run_pipeline.py`:

1. **Validation** (`step_00_validate_raw.py`) — Asserts 15-column schemas,
   per-file row counts within ±1% of specification, unique identifier
   counts, date-range containment, and absence of pipeline-blocking
   defects. Errors halt the pipeline; warnings (documented upstream data
   quirks) allow continuation.

2. **Pollutant parquet store** (`step_01_build_pollutant_store.py`) —
   Reads the seven merged By_Pollutant CSVs and writes a Hive-partitioned
   Apache Parquet dataset partitioned by pollutant group and year. Three
   operations are applied during write: (a) exact full-row deduplication
   of 973,294 rows introduced by the upstream merge step; (b) normalization
   of ozone measurements from TCEQ, which are reported in parts per billion
   (ppb), to parts per million (ppm) to match EPA convention, a conversion
   confirmed by direct inspection of the `units_of_measure` column in raw
   EPA files and the `Unit Cd` field in TCEQ Raw Data files (638,174 rows
   affected); and (c) normalization of county name capitalization.

3. **Weather parquet store** (`step_02_build_weather_store.py`) — Writes
   the weather master file as Hive-partitioned parquet (by station and
   year). Station coordinates and pre-derived fields (u/v wind, heat index,
   dew-point spread) are preserved from the upstream master.

4. **NAAQS design value computation** (`step_03_compute_naaqs.py`) —
   Per-site-year design values were computed following 40 CFR Part 50:
   - **Ozone 8-hour:** 4th-highest daily maximum 8-hour rolling mean,
     with 75% hourly completeness (≥6 of 8 hours per window);
   - **PM₂.₅ annual:** arithmetic mean of daily 24-hour means;
   - **PM₂.₅ 24-hour:** 98th percentile of daily 24-hour means;
   - **PM₁₀ 24-hour:** exceedance count against 150 µg/m³;
   - **CO 8-hour and 1-hour:** annual maxima;
   - **SO₂ 1-hour:** 99th percentile of daily maximum 1-hour values;
   - **NO₂ 1-hour and annual:** 98th percentile of daily max 1-hour, and
     annual arithmetic mean.
   Daily means and maxes required ≥18 of 24 hourly observations (75%
   completeness, 40 CFR §50 Appendix N). Design values exceeding current
   NAAQS thresholds were flagged; 3-year averaging was left to downstream
   analysis.

5. **Daily and monthly aggregates** (`step_04_compute_daily_aggregates.py`) —
   Per-site daily statistics (mean, min, max, standard deviation, hourly
   completeness percentage) were computed for each parameter. Days meeting
   the 75% completeness threshold were flagged as valid; invalid days
   were retained but excluded from monthly rollups.

6. **Air quality / weather joining** (`step_05_merge_aq_weather.py`) —
   Each air quality site was paired with its nearest weather station via
   Haversine great-circle distance, using site coordinates from the merged
   union of `enhanced_monitoring_sites.csv` (AQS-verified) and the TCEQ
   `Extra TCEQ Sites.xlsx` workbook. All 41 active sites were
   successfully paired; the pairing distance is retained in the combined
   output (`distance_km`) to support distance-weighted downstream analysis
   or threshold filtering.

7. **Analysis-ready exports** (`step_06_export_analysis_ready.py`) —
   Flat CSV exports (`daily_pollutant_means.csv`, `naaqs_design_values.csv`,
   `combined_aq_weather_daily.csv`, `site_registry.csv`) and optional R
   `.rds` bundles were emitted to support downstream analysis in R,
   RStudio, and Google Colab.

8. **Database load** (`step_07_load_postgres.py`) — Analysis-ready tables
   were loaded into a hosted PostgreSQL 16 instance (Neon, `aq` schema)
   for SQL-based querying by collaborators and BI tools. Connection
   credentials were supplied exclusively via an environment variable; no
   secrets were persisted to disk.

## Site Inventory

The pipeline produced a site registry containing 47 total monitoring sites,
stratified by data status: 41 with active measurement data, 3 Bexar County
CPS Energy fence-line monitors registered but without data, 2 Corpus
Christi volatile organic compound sites pending data retrieval from TCEQ
TAMIS, and 1 dual–AQS-ID physical site (Calaveras Lake, shared between EPA
ID 480290059 and TCEQ ID 480291609). The 41 active sites spanned 13
counties, with the greatest density in Bexar County (19 sites) and one
site each in Atascosa, Karnes, Kleberg, Maverick, Victoria, and Wilson
counties.

## Software and Reproducibility

The pipeline was implemented in Python 3.13 using `pandas` (2.x), `pyarrow`
(≥14), `pyyaml`, `numpy`, `sqlalchemy` (2.x), and `psycopg` (3.x). All
code, configuration, and documentation live in the `pipeline/` directory
of the project repository. The full pipeline can be rebuilt from raw
inputs in approximately 15 minutes via `python pipeline/run_pipeline.py`.
Deterministic outputs are guaranteed by idempotent writes and configurable
row-count validation. Complete reproduction instructions, dependency pins,
and expected output values are documented in
`pipeline/docs/11_reproducibility.md`.

## Data Availability

Processed outputs are distributed in three formats:

1. **Apache Parquet** (partitioned by pollutant group/year and by weather
   station/year) for high-performance Python and R analytical workflows;
2. **Flat CSV** for universal compatibility (R without Arrow, Google
   Colab, Excel);
3. **PostgreSQL** (hosted on Neon, `aq` schema) for interactive SQL and
   BI-tool access. Read-only credentials for collaborators are available
   on request.

Raw input files and full documentation are available within the project
repository. Upon publication, a Zenodo snapshot of the pipeline code and
an anonymized extract of the processed tables will be deposited under a
persistent DOI.

## Known Limitations

Several documented data artifacts affect the pipeline's outputs and should
be considered in analysis. First, the 2025 data tranche is incomplete
(EPA through July 2025; TCEQ through November 2025); any full-year 2025
metric should be treated as provisional. Second, ozone values in the
parquet store preceding pipeline version 0.2.1 were affected by an
EPA/TCEQ unit mismatch and must be discarded. Third, single-nearest-neighbor
weather pairings for sites more than approximately 20 km from their paired
station are of limited representativeness and will be superseded by spatial
interpolation in downstream work. A complete issue catalog appears in
`pipeline/docs/06_data_quality.md`.

## Project team and authorship

- **Principal Investigator:** Dr. Rajesh Melaram, Melaram Lab,
  Texas A&M University–Corpus Christi
- **Lead Developers:** Aidan Meyers (TAMU-CC), Manassa Kuchavaram (TAMU-CC)
- **Collaborators:** L. Jin, Donald E. Warden
- **Contact:** [aidan.meyers@tamucc.edu](mailto:aidan.meyers@tamucc.edu)

Source code repository:
https://github.com/AidanJMeyers/south-texas-aq-pipeline

## How to reference this pipeline

When referring to this pipeline in publications or presentations, use:

> Meyers, A., Kuchavaram, M., Jin, L., Warden, D. E., & Melaram, R. (2026).
> *South Texas Air Quality Data Pipeline*, version 0.3.4. Melaram Lab,
> Texas A&M University–Corpus Christi.
> https://github.com/AidanJMeyers/south-texas-aq-pipeline

---

**For technical details of every formula, completeness rule, and
conversion**, see [05_methodology.md](./05_methodology.md).
**For the complete list of known data issues**, see [06_data_quality.md](./06_data_quality.md).
