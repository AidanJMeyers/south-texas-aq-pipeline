"""I/O helpers — config loading, path resolution, parquet/CSV readers & writers.

All pipeline steps go through these helpers so paths and dtypes are consistent.
Nothing here does any analytical work; it is the plumbing layer only.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq
import yaml


# ---------------------------------------------------------------------------
# Canonical schemas
# ---------------------------------------------------------------------------
# 15-column By_Pollutant / By_County schema. Keeping site_name as string avoids
# the NaN -> float coercion bug called out in PIPELINE_PROMPT.md §9 issue #6.
POLLUTANT_SCHEMA: dict[str, str] = {
    "state_code":         "Int32",
    "county_code":        "Int32",
    "site_number":        "Int32",
    "parameter_code":     "Int32",
    "poc":                "Int32",
    "date_local":         "string",
    "time_local":         "string",
    "sample_measurement": "float64",
    "method_code":        "Int32",
    "county_name":        "string",
    "pollutant_name":     "string",
    "aqsid":              "string",
    "data_source":        "string",
    "pollutant_group":    "string",
    "site_name":          "string",
}
POLLUTANT_COLUMNS: list[str] = list(POLLUTANT_SCHEMA.keys())

# Key weather columns used downstream. (The master has 45 columns; we only
# type-cast the ones we need. pandas will infer the rest.)
WEATHER_KEY_COLS: list[str] = [
    "dt", "datetime_local", "datetime_utc",
    "year", "month", "hour",
    "location",
    "temp", "feels_like", "dew_point",
    "humidity", "pressure",
    "wind_speed", "wind_deg", "wind_gust",
    "clouds_all", "visibility",
    "rain_1h", "snow_1h", "weather_id",
    "ghi_cloudy_sky", "ghi_clear_sky",
    "dni_cloudy_sky", "dhi_cloudy_sky",
]


# ---------------------------------------------------------------------------
# Config + path resolution
# ---------------------------------------------------------------------------
@dataclass
class PipelineConfig:
    """Parsed pipeline config with absolute paths.

    Attributes:
        root: Resolved absolute project root.
        raw: The raw YAML config dict (keys ``project``, ``paths``, ...).
    """
    root: Path
    raw: dict[str, Any]

    def path(self, key: str) -> Path:
        """Return an absolute path for a key in ``config.yaml:paths``.

        Example:
            >>> cfg.path("processed_pollutant")
            PosixPath('.../01_Data/Processed/By_Pollutant')
        """
        rel = self.raw["paths"][key]
        return (self.root / rel).resolve()

    def get(self, *keys: str, default: Any = None) -> Any:
        """Walk nested keys in the raw config. ``cfg.get('naaqs','ozone_8hr_ppm')``."""
        node: Any = self.raw
        for k in keys:
            if not isinstance(node, dict) or k not in node:
                return default
            node = node[k]
        return node


def resolve_root() -> Path:
    """Auto-detect the project ROOT across Colab, local Windows/OneDrive, or CWD.

    Resolution order:
        1. ``AQ_PIPELINE_ROOT`` environment variable (explicit override)
        2. Google Colab default: ``/content/drive/MyDrive/AirQuality South TX``
        3. Local Windows OneDrive: ``~/OneDrive/Desktop/AirQuality South TX``
           (also checks ``~/OneDrive/AirQuality South TX``)
        4. Current working directory (if it contains ``01_Data/Processed``)
        5. Walk up from CWD looking for ``PIPELINE_PROMPT.md``

    Raises:
        FileNotFoundError: if no candidate contains the expected structure.
    """
    candidates: list[Path] = []

    env = os.environ.get("AQ_PIPELINE_ROOT")
    if env:
        candidates.append(Path(env).expanduser())

    candidates.extend([
        Path("/content/drive/MyDrive/AirQuality South TX"),
        Path.home() / "OneDrive" / "Desktop" / "AirQuality South TX",
        Path.home() / "OneDrive" / "AirQuality South TX",
        Path.cwd(),
    ])

    for c in candidates:
        if (c / "01_Data" / "Processed").is_dir():
            return c.resolve()

    # Walk up from CWD for PIPELINE_PROMPT.md
    here = Path.cwd().resolve()
    for parent in [here, *here.parents]:
        if (parent / "PIPELINE_PROMPT.md").exists():
            return parent

    raise FileNotFoundError(
        "Could not resolve AQ pipeline ROOT. Set AQ_PIPELINE_ROOT env var, "
        "or run from the project directory. Checked: "
        + ", ".join(str(c) for c in candidates)
    )


def load_config(config_path: str | Path | None = None) -> PipelineConfig:
    """Load ``pipeline/config.yaml`` and resolve the project root.

    Args:
        config_path: Optional explicit path. Defaults to ``<ROOT>/pipeline/config.yaml``.
    """
    root = resolve_root()
    path = Path(config_path) if config_path else root / "pipeline" / "config.yaml"
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return PipelineConfig(root=root, raw=raw)


def ensure_dir(path: Path) -> Path:
    """Create ``path`` if missing. Returns the path for chaining."""
    path.mkdir(parents=True, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# Readers
# ---------------------------------------------------------------------------
def read_pollutant_csv(
    csv_path: str | Path,
    chunksize: int | None = None,
) -> pd.DataFrame | Iterable[pd.DataFrame]:
    """Read a By_Pollutant / By_County CSV with the canonical 15-col schema.

    Forces ``site_name`` to string (see PIPELINE_PROMPT.md §9 issue #6).

    Args:
        csv_path: Path to CSV.
        chunksize: If set, return a TextFileReader iterator instead of a DataFrame.
    """
    return pd.read_csv(
        csv_path,
        dtype=POLLUTANT_SCHEMA,
        chunksize=chunksize,
        low_memory=False,
    )


def read_parquet_dataset(
    path: str | Path,
    columns: list[str] | None = None,
    filters: list[tuple] | None = None,
) -> pd.DataFrame:
    """Read a partitioned parquet dataset with optional column/filter pushdown.

    Example:
        >>> df = read_parquet_dataset(
        ...     "data/parquet/pollutants",
        ...     filters=[("pollutant_group", "=", "Ozone"), ("year", "=", 2023)],
        ... )

    Explicitly enumerates ``*.parquet`` files so OneDrive-injected
    ``desktop.ini`` sidecars (and other junk files Windows drops into
    synced folders) don't crash the dataset scan.
    """
    root = Path(path)
    files = [str(p) for p in root.rglob("*.parquet")]
    if not files:
        raise FileNotFoundError(f"No .parquet files found under {root}")
    dataset = ds.dataset(files, format="parquet", partitioning="hive")
    table = dataset.to_table(columns=columns, filter=_build_filter(dataset, filters))
    return table.to_pandas()


def _build_filter(dataset: ds.Dataset, filters: list[tuple] | None):
    """Translate pandas-style filter tuples into pyarrow Expression objects."""
    if not filters:
        return None
    expr = None
    for col, op, val in filters:
        f = ds.field(col)
        match op:
            case "=" | "==":
                step = f == val
            case "!=":
                step = f != val
            case ">":
                step = f > val
            case ">=":
                step = f >= val
            case "<":
                step = f < val
            case "<=":
                step = f <= val
            case "in":
                step = f.isin(list(val))
            case _:
                raise ValueError(f"Unsupported filter op: {op}")
        expr = step if expr is None else (expr & step)
    return expr


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------
def write_parquet_partitioned(
    df: pd.DataFrame,
    out_path: str | Path,
    partition_cols: list[str],
    existing: str = "delete_matching",
) -> Path:
    """Write a DataFrame to a Hive-partitioned parquet dataset.

    Idempotent: with ``existing='delete_matching'`` (default) pyarrow
    replaces only the partitions touched by this write, leaving other
    partitions intact.

    Args:
        df: DataFrame to write.
        out_path: Destination directory (created if missing).
        partition_cols: Columns to partition by (Hive style).
        existing: Passed to ``pyarrow.dataset.write_dataset``.
    """
    out = Path(out_path)
    ensure_dir(out)
    table = pa.Table.from_pandas(df, preserve_index=False)
    ds.write_dataset(
        table,
        base_dir=str(out),
        format="parquet",
        partitioning=partition_cols,
        partitioning_flavor="hive",
        existing_data_behavior=existing,
    )
    return out


def write_csv(df: pd.DataFrame, out_path: str | Path, index: bool = False) -> Path:
    """Write a DataFrame to CSV, creating parent dirs as needed."""
    out = Path(out_path)
    ensure_dir(out.parent)
    df.to_csv(out, index=index)
    return out
