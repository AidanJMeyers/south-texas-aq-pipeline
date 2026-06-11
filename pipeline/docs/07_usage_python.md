# 07 — Python Usage Guide

Everything you need to load and analyze pipeline outputs from Python. Works
on Windows, macOS, Linux, and Google Colab.

## Install

```bash
pip install pandas pyarrow
# Optional for Postgres:
pip install "psycopg[binary]" sqlalchemy
```

Python 3.10+ is required (the pipeline uses PEP 604 type hints and `match`
statements). 3.11+ recommended.

## Loading parquet — the primary workflow

Parquet is **10–50× faster** than CSV for analytical queries. Use it whenever
possible.

### Load all ozone data for 2023

```python
import pandas as pd

df = pd.read_parquet(
    "data/parquet/pollutants",
    filters=[("pollutant_group", "=", "Ozone"), ("year", "=", 2023)],
)
print(df.shape)  # (~165000, 21)
print(df.county_name.value_counts())
```

The `filters` kwarg pushes the predicate down into the parquet reader, so
only the relevant partition files are opened — orders of magnitude faster
than loading everything and filtering in pandas.

### Load specific columns only

```python
df = pd.read_parquet(
    "data/parquet/pollutants",
    filters=[("pollutant_group", "=", "PM2.5"), ("county_name", "=", "Bexar")],
    columns=["date_local", "time_local", "sample_measurement", "site_name", "aqsid"],
)
```

### Scan with PyArrow for larger-than-memory queries

```python
import pyarrow.dataset as ds

dataset = ds.dataset("data/parquet/pollutants", format="parquet", partitioning="hive")

# Count rows per year without loading the data
for frag in dataset.get_fragments():
    meta = frag.metadata
    print(frag.path, meta.num_rows)
```

### Filter by a list of sites

```python
bexar_o3_sites = ["480290052", "480290055", "480291091", "480291610"]
df = pd.read_parquet(
    "data/parquet/pollutants",
    filters=[
        ("pollutant_group", "=", "Ozone"),
        ("aqsid", "in", bexar_o3_sites),
    ],
)
```

## Daily aggregates

```python
daily = pd.read_csv("data/csv/daily_pollutant_means.csv")
# Or, faster:
daily = pd.read_parquet("data/parquet/daily/pollutant_daily.parquet")

# Use only days that meet the 75% completeness threshold
valid = daily[daily.valid_day]

# Annual mean PM2.5 per county
pm25 = valid[valid.pollutant_group == "PM2.5"].copy()
pm25["year"] = pd.to_datetime(pm25.date_local).dt.year
annual = (pm25.groupby(["year", "county_name"])["mean"]
              .mean()
              .reset_index()
              .rename(columns={"mean": "annual_mean_ugm3"}))
```

## NAAQS design values

```python
dv = pd.read_csv("data/csv/naaqs_design_values.csv")

# What sites exceeded the 8-hr ozone standard in 2023?
exceedances_2023 = dv.query(
    "metric == 'ozone_8hr_4th_max' and year == 2023 and exceeds"
)
print(exceedances_2023[["county_name", "site_name", "value", "naaqs_level"]])
```

## AQ + weather correlation (v0.4.0 — join in user code)

`aq.aq_weather_daily` was dropped in v0.4.0 (decision #13). Join the daily
pollutant aggregates with the weather hourly store directly:

```python
poll = pd.read_parquet("data/parquet/daily/pollutant_daily.parquet")
wx   = pd.read_parquet("data/parquet/weather/", filters=[("year", "=", 2024)])

# Aggregate weather to daily, then join on (county_name, date_local)
wx_daily = (
    wx.groupby(["county_name", "date_local"])[["temp_c", "humidity", "wind_speed"]]
      .mean()
      .reset_index()
)

# Correlation between daily temp_c and daily ozone mean at a single site
site = poll.query("aqsid == '480290052' and pollutant_group == 'Ozone'")
joined = site.merge(wx_daily, on=["county_name", "date_local"])
print(joined[["mean", "temp_c", "wind_speed", "humidity"]].corr())
```

## Site registry (v0.4.0 — new columns)

```python
sites = pd.read_csv("data/csv/site_registry.csv")

# Only active sites
active = sites.query("data_status == 'active'")

# Which sites measure VOCs (new in v0.4.0)
voc_sites = active[active["voc_cadence"] != ""]
print(voc_sites[["aqsid", "site_name", "county_name", "voc_cadence"]])

# Count by county (the v0.3.7 'network' column is gone — all TCEQ now)
print(active.groupby("county_name").size())
```

## VOC profile at a single site (NEW in v0.4.0)

```python
voc = pd.read_parquet("data/parquet/vocs_1hr/",
                       filters=[("year", "=", 2024)])
# Camp Bullis Benzene daily mean
camp = voc.query("aqsid == '480290052' and pollutant_name == 'Benzene'")
daily = camp.groupby("date_local")["sample_measurement"].mean()
print(daily.describe())
```

## Site 0060 PM10 24hr-only readings (NEW table in v0.4.0)

```python
daily24 = pd.read_parquet("data/parquet/pollutant_daily_24hr/")
print(daily24[["date_local", "aqsid", "sample_measurement"]].head())
# All rows: 1 site (480290060 San Antonio Palo Alto), PM10 only,
# 24hr filter samples on a 1-in-6 day EPA schedule (~58/year).
```

## Full worked example: Bexar County ozone NAAQS trend

```python
import pandas as pd
import matplotlib.pyplot as plt

dv = pd.read_csv("data/csv/naaqs_design_values.csv")

bexar_o3 = dv.query(
    "county_name == 'Bexar' and metric == 'ozone_8hr_4th_max'"
)

annual_max = bexar_o3.groupby("year")["value"].max().reset_index()

fig, ax = plt.subplots(figsize=(8, 5))
ax.plot(annual_max.year, annual_max.value, marker="o", linewidth=2)
ax.axhline(0.070, color="red", linestyle="--", label="NAAQS 0.070 ppm")
ax.set_xlabel("Year")
ax.set_ylabel("4th-highest daily max 8-hr O₃ (ppm)")
ax.set_title("Bexar County Ozone Design Values, 2015–2025")
ax.legend()
ax.grid(alpha=0.3)
plt.tight_layout()
plt.savefig("bexar_ozone_trend.png", dpi=150)
```

## Postgres from Python (optional)

Requires `sqlalchemy>=2.0` and `psycopg[binary]>=3.1`.

```python
import os
import pandas as pd
from sqlalchemy import create_engine, text

url = os.environ["AQ_POSTGRES_URL"]  # Read from env var, never hardcode
engine = create_engine(url, pool_pre_ping=True)

# Read into a DataFrame
with engine.connect() as conn:
    df = pd.read_sql(
        "SELECT * FROM aq.naaqs_design_values WHERE year = 2023 AND exceeds",
        conn,
    )
```

Or use the helper:

```python
from pipeline.utils.db import get_engine
engine = get_engine()  # reads AQ_POSTGRES_URL, returns None if unset
```

See [10_usage_sql.md](./10_usage_sql.md) for more query examples.

## Common pitfalls

1. **Don't load the whole pollutant parquet without a filter.** It's ~5M
   rows. Always push predicates with `filters=[...]`.

2. **`date_local` is a string, not a datetime.** Use `pd.to_datetime()`
   before date arithmetic.

3. **`sample_measurement` units depend on `pollutant_group`.** See
   [03_data_schemas.md §Unit conventions](./03_data_schemas.md#unit-conventions-pollutant-parquet).

4. **`completeness_pct` is a fraction, not a percentage.** `0.75`, not `75`.

5. **Duplicate parameters per site.** Some sites report the same pollutant
   via multiple `parameter_code` values (e.g. NO₂ has 42602, NOx has 42603).
   If you want "NO₂ concentration" specifically, filter by `parameter_code == 42602`.

6. **2025 is incomplete.** See [06_data_quality.md issue 13](./06_data_quality.md#13-2025-data-is-partial).
