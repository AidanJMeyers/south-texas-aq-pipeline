"""South Texas Air Quality data pipeline.

A reproducible, config-driven pipeline that converts the project's raw CSVs
into a partitioned Parquet store, computes NAAQS design values, builds daily
aggregates, merges AQ + weather, and exports flat CSVs for R/Colab.

Entry point: ``python pipeline/run_pipeline.py``

See pipeline/README.md for usage and pipeline/DATA_CATALOG.md for the output
manifest.
"""

__version__ = "0.1.0"
