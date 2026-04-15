# 09 — Google Colab Quickstart

Running the pipeline (or querying its outputs) from Google Colab.

## Setup

### Mount your Google Drive

```python
from google.colab import drive
drive.mount('/content/drive')
```

### Change into the project root

```python
import os
os.chdir('/content/drive/MyDrive/AirQuality South TX')
!ls pipeline/
```

The pipeline's path resolver automatically detects Colab and uses
`/content/drive/MyDrive/AirQuality South TX` as `ROOT` — nothing to configure.

### Install dependencies

```python
!pip install -q pyarrow pyyaml sqlalchemy "psycopg[binary]"
```

Pandas, numpy, and openpyxl are preinstalled on Colab.

## Option A: Run the pipeline from Colab

If you need to rebuild outputs (e.g. after adding new raw data):

```python
!python pipeline/run_pipeline.py
```

Expected runtime on a standard Colab CPU runtime: ~15–20 minutes. Most of
the time is I/O against Google Drive, which is slower than a local SSD.

Skip slow steps if you just need the NAAQS recomputation:

```python
!python pipeline/run_pipeline.py --only 03
```

## Option B: Query pre-built outputs (common case)

```python
import pandas as pd

# Fast parquet query with predicate pushdown
df = pd.read_parquet(
    '/content/drive/MyDrive/AirQuality South TX/data/parquet/pollutants',
    filters=[('pollutant_group', '=', 'Ozone'), ('year', '=', 2023)],
)
print(df.shape)
print(df.head())
```

## Option C: Connect to the Postgres (Neon) database

Avoids syncing large files through Drive — queries go over HTTPS to Neon.

### Set the connection URL as a Colab secret

In Colab, go to the 🔑 key icon in the left sidebar → "Add new secret":
- Name: `AQ_POSTGRES_URL`
- Value: `postgresql://user:pass@ep-xxx.us-east-2.aws.neon.tech/neondb?sslmode=require`
- Enable notebook access

Then in a cell:

```python
from google.colab import userdata
import os
os.environ['AQ_POSTGRES_URL'] = userdata.get('AQ_POSTGRES_URL')
```

### Connect and query

```python
import os
import pandas as pd
from sqlalchemy import create_engine

engine = create_engine(os.environ['AQ_POSTGRES_URL'], pool_pre_ping=True)

dv = pd.read_sql(
    """
    SELECT county_name, site_name, year, value, naaqs_level, exceeds
    FROM aq.naaqs_design_values
    WHERE metric = 'ozone_8hr_4th_max'
      AND year >= 2020
    ORDER BY year DESC, value DESC
    """,
    engine,
)
dv.head(20)
```

### First-query slowness on Neon

Neon's free tier auto-pauses after 5 minutes of idle. The first query after
a pause takes ~500 ms to wake the compute. Subsequent queries are fast.
`pool_pre_ping=True` handles this transparently for you.

## A complete Colab notebook example

```python
# Cell 1: setup
from google.colab import drive, userdata
import os, pandas as pd, matplotlib.pyplot as plt
drive.mount('/content/drive')
os.chdir('/content/drive/MyDrive/AirQuality South TX')
os.environ['AQ_POSTGRES_URL'] = userdata.get('AQ_POSTGRES_URL')

# Cell 2: load the design values table
from sqlalchemy import create_engine
engine = create_engine(os.environ['AQ_POSTGRES_URL'], pool_pre_ping=True)
dv = pd.read_sql("SELECT * FROM aq.naaqs_design_values WHERE metric='ozone_8hr_4th_max'", engine)

# Cell 3: plot
fig, ax = plt.subplots(figsize=(10, 6))
for county, grp in dv.groupby('county_name'):
    ax.plot(grp.year, grp.value, marker='o', label=county)
ax.axhline(0.070, color='red', linestyle='--', label='NAAQS 0.070 ppm')
ax.set_xlabel('Year')
ax.set_ylabel('4th-highest daily max 8-hr O₃ (ppm)')
ax.set_title('Ozone 8-hr Design Values by County — South Texas')
ax.legend(loc='upper left', fontsize=8)
plt.tight_layout()
plt.show()
```

## Persistent storage

Anything you write back to Google Drive persists across Colab sessions.
**Nothing written to `/content/`** (i.e. Colab's ephemeral disk) persists —
always save outputs under `/content/drive/MyDrive/…`.

The pipeline automatically writes to `data/` under the project ROOT, which
resolves to `/content/drive/MyDrive/AirQuality South TX/data/` in Colab, so
outputs are preserved automatically.

## Speed tips

1. **Prefer Postgres for ad-hoc queries.** No Drive I/O; indexed reads.
2. **If using parquet in Colab, copy partitions to `/content/`** before
   repeated scans:
   ```python
   !cp -r "/content/drive/MyDrive/AirQuality South TX/data/parquet/naaqs" /content/naaqs
   dv = pd.read_parquet("/content/naaqs/design_values.parquet")
   ```
3. **Use filters on parquet reads** — every filter skips partitions.
4. **Don't process raw 1M+ row weather master in Colab.** Use the partitioned
   parquet in `data/parquet/weather/` instead.

## Troubleshooting

**`FileNotFoundError: Could not resolve AQ pipeline ROOT`** — Drive didn't
mount or the folder isn't at `/content/drive/MyDrive/AirQuality South TX`.
Set the env var explicitly:
```python
os.environ['AQ_PIPELINE_ROOT'] = '/path/to/project'
```

**Pipeline is very slow on Drive** — Google Drive's filesystem is slow for
many small files. If you need to rerun, consider:
1. Copying `01_Data/Processed/` to `/content/` before running the pipeline
2. Running steps `--only 03,04,05` which work on parquet (already fast)
