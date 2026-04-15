# South Texas Air Quality Data Pipeline — Documentation

> **Project:** Multi-year ambient air quality characterization of 13 South Texas counties
> **Lab:** Melaram Lab, Texas A&M University–Corpus Christi
> **Lead Researcher:** Aidan Wolf
> **Pipeline Version:** 0.3.0 (April 2026)
> **Study Period:** January 2015 – November 2025

This directory is the canonical reference for the South Texas AQ data pipeline.
It is designed to be **publication-ready** — every design decision, data
transformation, quality caveat, and access pattern is documented here so the
protocol can be cited and reproduced without reading source code.

## Table of Contents

| # | Document | Purpose |
|---|---|---|
| 01 | [Project Overview](./01_overview.md) | Study context, goals, study area, deliverables |
| 02 | [Data Sources](./02_data_sources.md) | EPA AQS, TCEQ CAMS, OpenWeather — provenance and retrieval |
| 03 | [Data Schemas](./03_data_schemas.md) | Every table, every column, every unit |
| 04 | [Pipeline Architecture](./04_pipeline_architecture.md) | Step-by-step breakdown of all 8 pipeline steps |
| 05 | [Methodology](./05_methodology.md) | NAAQS formulas, completeness rules, citations (40 CFR Part 50) |
| 06 | [Data Quality & Known Issues](./06_data_quality.md) | Validation checks, discovered issues, caveats |
| 07 | [Python Usage Guide](./07_usage_python.md) | Parquet + pandas access patterns |
| 08 | [R / RStudio Usage Guide](./08_usage_r.md) | arrow + data.table, legacy RDS exports |
| 09 | [Google Colab Quickstart](./09_usage_colab.md) | Mounting Drive and running against parquet |
| 10 | [SQL / Postgres Usage Guide](./10_usage_sql.md) | Neon connection + worked SQL examples |
| 11 | [Reproducibility Guide](./11_reproducibility.md) | Rebuilding the pipeline from scratch |
| 12 | [Configuration Reference](./12_configuration_reference.md) | Every key in `config.yaml` |
| 13 | [Architecture Decisions](./13_decisions.md) | Why parquet, why Neon, why Haversine — the record |
| 14 | [Publication Protocol Summary](./14_publication_protocol.md) | Methods-section-ready prose |

## Additional Files

- [`CITATION.cff`](./CITATION.cff) — Machine-readable citation metadata
- `figures/` — Architecture diagrams

## Top-level project docs

The repository root also contains:
- [`pipeline/README.md`](../README.md) — Short quick-start
- [`pipeline/DATA_CATALOG.md`](../DATA_CATALOG.md) — Output file manifest
- [`pipeline/CHANGELOG.md`](../CHANGELOG.md) — Version history with rationale
- [`PIPELINE_PROMPT.md`](../../PIPELINE_PROMPT.md) — The original specification

## Quick navigation by question

**"How do I run the pipeline from scratch?"** → [11_reproducibility.md](./11_reproducibility.md)
**"What does column X mean?"** → [03_data_schemas.md](./03_data_schemas.md)
**"How do I load data in R?"** → [08_usage_r.md](./08_usage_r.md)
**"Are the NAAQS values computed correctly?"** → [05_methodology.md](./05_methodology.md)
**"Why is there a site count discrepancy?"** → [06_data_quality.md](./06_data_quality.md)
**"Can I cite this in a paper?"** → [14_publication_protocol.md](./14_publication_protocol.md) + [CITATION.cff](./CITATION.cff)

---

*For questions not answered by the documentation, contact the Melaram Lab at TAMU-CC.*
