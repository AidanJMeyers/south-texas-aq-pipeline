# 17 — Colab + Neon Database Guide

The complete guide to querying the South Texas AQ pipeline data from
Google Colab. Covers both **direct SQL** (the recommended fast path) and
the **Neon Data API** (for lightweight HTTP-based access). Includes
worked examples against every table, performance tips, and copy-paste
recipes for common analytical workflows.

> **Database:** Neon Postgres 16 · project `south-texas-aq` · schema `aq`
> **Plan:** Launch ($19/mo, 10 GB storage, 300 CU-hours/month included)
> **Region:** AWS us-east-1
> **Last updated:** 2026-04-22

---

## What's in the database

After the pipeline runs, the `aq` schema contains:

| Table | Rows | Size | Use this for |
|---|---:|---:|---|
| `aq.site_registry` | 47 | <100 kB | Site metadata, network membership, status, coordinates |
| `aq.naaqs_design_values` | 764 | 200 kB | Per-site, per-year, per-metric NAAQS compliance values |
| `aq.pollutant_monthly` | ~11k | 2 MB | Quick monthly trends, low-resolution dashboards |
| `aq.pollutant_daily` | ~390k | 70 MB | Daily aggregates with completeness flags (most common) |
| `aq.aq_weather_daily` | ~390k | 130 MB | Daily pollutants joined to nearest-station weather |
| `aq.pollutant_hourly` | ~7.7M | ~2.5 GB | Hourly resolution; diurnal cycles, episode analysis |
| `aq.weather_hourly` | ~1.47M | ~900 MB | Hourly weather organized by original station name |

For column-level schemas see [03_data_schemas.md](./03_data_schemas.md).

---

## Connection method 1: Direct SQL (recommended)

This is the **fast path** — connects to Postgres directly via the binary
wire protocol. Use this for any analytical workload (anything pulling
more than ~100 rows back).

### One-time setup in Colab

#### Step 1 — Get your connection string

The connection string lives in your Neon console:
**https://console.neon.tech/app/projects/aged-salad-62359207** →
"Connection Details" tab → copy the URL that starts with
`postgresql://...`

It looks like:
```
postgresql://neondb_owner:npg_...@ep-xxx.us-east-1.aws.neon.tech/neondb?sslmode=require
```

#### Step 2 — Add it as a Colab secret

1. In Colab, click the 🔑 key icon in the left sidebar
2. **Add new secret**:
   - Name: `AQ_POSTGRES_URL`
   - Value: paste the connection string
3. Toggle **"Notebook access"** ON for the notebook you're using

This stores the credential outside your notebook code so you can share
the notebook freely without leaking the password.

#### Step 3 — Install the client (one-time per Colab runtime)

```python
!pip install -q "psycopg[binary]" sqlalchemy pandas
```

#### Step 4 — Connect

```python
from google.colab import userdata
from sqlalchemy import create_engine
import pandas as pd

engine = create_engine(
    userdata.get('AQ_POSTGRES_URL'),
    pool_pre_ping=True,         # handles Neon auto-pause
)

# Sanity check
print(pd.read_sql("SELECT version()", engine).iloc[0, 0])
```

That's it. From this point on, every query is `pd.read_sql(SQL, engine)`.

### Performance tips

1. **Always filter at the SQL level**, not in pandas:
   ```python
   # SLOW (downloads 7.7M rows then filters)
   df = pd.read_sql("SELECT * FROM aq.pollutant_hourly", engine)
   df_2023 = df[df.year == 2023]

   # FAST (Postgres filters server-side; ~100x less data over the wire)
   df_2023 = pd.read_sql(
       "SELECT * FROM aq.pollutant_hourly WHERE year = 2023",
       engine
   )
   ```

2. **Select only the columns you need.** `pollutant_hourly` has 21 columns;
   if you only need 4, name them explicitly.

3. **Use `LIMIT` while exploring** to avoid pulling millions of rows by accident.

4. **Neon auto-pauses after 5 min idle.** Your first query after a long
   pause takes ~500 ms to wake the compute. `pool_pre_ping=True` makes
   this transparent.

5. **For huge result sets (>1M rows)**, consider `chunksize`:
   ```python
   chunks = pd.read_sql(SQL, engine, chunksize=50_000)
   df = pd.concat(chunks, ignore_index=True)
   ```

---

## Connection method 2: Neon Data API (HTTP / REST)

Useful for **lightweight integrations** — dashboards, web apps,
serverless functions — anywhere you don't want to ship a Postgres
driver. Slower than direct SQL for large pulls because everything
serializes to JSON.

### How the Data API roles work

Neon's Data API uses **PostgREST** under the hood, with these built-in
Postgres roles:

| Role | Purpose | Login? |
|---|---|---|
| `anonymous` | Public reads (no auth required) | No (assumed by API) |
| `authenticated` | Reads after JWT auth via Neon Auth | No (assumed by API) |
| `authenticator` | Login role the API uses to switch into the above two | Yes |

The pipeline grants `SELECT` on all `aq.*` tables to both `anonymous` and
`authenticated`, so anyone with your Data API URL can run read-only
queries against any table. **No write operations are exposed.**

### Get your Data API URL

In the Neon console: **Settings → Data API → enable** (if not already) →
copy the URL. It looks like:

```
https://app-xxx.dpl.myneon.app
```

### Example HTTP query

```python
import requests, pandas as pd

API_URL = "https://your-data-api-url.dpl.myneon.app"

# Get all NAAQS exceedances for 2023 — note the PostgREST query syntax
resp = requests.get(
    f"{API_URL}/aq/naaqs_design_values",
    params={
        "year": "eq.2023",
        "exceeds": "is.true",
        "select": "aqsid,site_name,county_name,metric,value",
        "order": "value.desc",
    },
    headers={"Accept": "application/json"},
)
df = pd.DataFrame(resp.json())
print(df)
```

### When to choose Data API vs. direct SQL

| Use Data API when | Use direct SQL when |
|---|---|
| Building a public dashboard | Doing analysis in Colab |
| Serverless function (no driver install) | Pulling >10k rows |
| You want HTTP-based caching | You need joins or window functions |
| External app without Postgres support | Performance matters |

For analysis in Colab → **always use direct SQL.**

---

## Worked examples

### Example 1 — Hourly diurnal ozone profile at Camp Bullis (2023)

```python
sql = """
SELECT EXTRACT(HOUR FROM datetime)::int AS hour_of_day,
       AVG(sample_measurement) AS mean_o3_ppm,
       PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY sample_measurement) AS median_o3,
       PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY sample_measurement) AS p95_o3
FROM aq.pollutant_hourly
WHERE aqsid = '480290052'
  AND pollutant_group = 'Ozone'
  AND year = 2023
  AND sample_measurement IS NOT NULL
GROUP BY hour_of_day
ORDER BY hour_of_day
"""
diurnal = pd.read_sql(sql, engine)

import matplotlib.pyplot as plt
fig, ax = plt.subplots(figsize=(9, 5))
ax.plot(diurnal.hour_of_day, diurnal.mean_o3_ppm, marker='o', label='Mean')
ax.plot(diurnal.hour_of_day, diurnal.median_o3, marker='s', label='Median')
ax.plot(diurnal.hour_of_day, diurnal.p95_o3, marker='^', label='95th %ile')
ax.set_xlabel('Hour of day (local)')
ax.set_ylabel('Ozone (ppm)')
ax.set_title('Diurnal Ozone Profile — Camp Bullis 2023')
ax.legend()
ax.grid(alpha=0.3)
ax.set_xticks(range(0, 24, 3))
plt.tight_layout()
```

**Expected pattern:** Concentration rises after sunrise as photochemistry
kicks in, peaks mid-afternoon (1–4 PM), declines through the evening as
NOx scavenging dominates. Classic diurnal curve.

### Example 2 — Weather time series for one station (March 2024)

```python
sql = """
SELECT datetime_local::timestamp AS ts,
       temp_c, humidity, wind_speed, wind_deg, pressure
FROM aq.weather_hourly
WHERE location = 'SA Northwest'
  AND year = 2024
  AND month = 3
ORDER BY ts
"""
wx = pd.read_sql(sql, engine, parse_dates=['ts'])
wx.set_index('ts', inplace=True)

import matplotlib.pyplot as plt
fig, axes = plt.subplots(4, 1, figsize=(12, 9), sharex=True)
wx['temp_c'].plot(ax=axes[0], color='#c2410c'); axes[0].set_ylabel('Temp (°C)')
wx['humidity'].plot(ax=axes[1], color='#0c6e8a'); axes[1].set_ylabel('RH (%)')
wx['wind_speed'].plot(ax=axes[2], color='#213c4e'); axes[2].set_ylabel('Wind (m/s)')
wx['pressure'].plot(ax=axes[3], color='#345372'); axes[3].set_ylabel('Pressure (hPa)')
fig.suptitle('SA Northwest weather — March 2024')
plt.tight_layout()
```

### Example 3 — Episode analysis: highest PM₂.₅ days

```python
sql = """
WITH daily_max AS (
    SELECT date_local, county_name, site_name,
           MAX(sample_measurement) AS peak_pm25
    FROM aq.pollutant_hourly
    WHERE pollutant_group = 'PM2.5'
      AND year = 2024
      AND sample_measurement IS NOT NULL
    GROUP BY date_local, county_name, site_name
)
SELECT date_local, county_name, site_name, ROUND(peak_pm25::numeric, 1) AS peak_pm25
FROM daily_max
ORDER BY peak_pm25 DESC
LIMIT 20
"""
episodes = pd.read_sql(sql, engine)
print(episodes.to_string(index=False))
```

For each high-PM₂.₅ day, follow up by looking at hourly PM₂.₅ + weather
together to see whether it was a wildfire smoke plume, Saharan dust,
local stagnation, etc.

### Example 4 — Pull hourly pollutant + weather for a single site-day (regression-ready)

```python
sql = """
SELECT
    p.datetime,
    p.sample_measurement AS o3_ppm,
    w.temp_c, w.humidity, w.wind_speed, w.wind_u, w.wind_v
FROM aq.pollutant_hourly p
JOIN aq.weather_hourly  w
  ON w.location = 'SA Northwest'
 AND w.datetime_local::timestamp = p.datetime
WHERE p.aqsid = '480290052'
  AND p.pollutant_group = 'Ozone'
  AND p.date_local BETWEEN '2024-08-01' AND '2024-08-31'
ORDER BY p.datetime
"""
df = pd.read_sql(sql, engine, parse_dates=['datetime'])

# Quick correlation check
print(df.corr(numeric_only=True)['o3_ppm'].round(3))
```

**Note:** This joins on `(weather_station, datetime)` — the weather
station name is hardcoded here for the example. To do this for every
site automatically, join via `aq.site_registry` to look up each AQ
site's nearest weather station.

### Example 5 — Reproduce the NAAQS 8-hr ozone calculation from raw hourly

```python
sql = """
WITH ozone AS (
  SELECT aqsid, datetime, sample_measurement
  FROM aq.pollutant_hourly
  WHERE aqsid = '480290052'
    AND pollutant_group = 'Ozone'
    AND year = 2023
    AND sample_measurement IS NOT NULL
),
rolling_8hr AS (
  SELECT aqsid, datetime,
         AVG(sample_measurement) OVER (
           ORDER BY datetime
           ROWS BETWEEN 7 PRECEDING AND CURRENT ROW
         ) AS avg_8hr,
         COUNT(sample_measurement) OVER (
           ORDER BY datetime
           ROWS BETWEEN 7 PRECEDING AND CURRENT ROW
         ) AS hrs_in_window
  FROM ozone
),
daily_max AS (
  SELECT DATE(datetime) AS day, MAX(avg_8hr) AS daily_8hr_max
  FROM rolling_8hr
  WHERE hrs_in_window >= 6   -- 75% completeness rule
  GROUP BY DATE(datetime)
)
SELECT day, ROUND(daily_8hr_max::numeric, 4) AS daily_max_8hr_ppm
FROM daily_max
ORDER BY daily_8hr_max DESC
LIMIT 5
"""
top5 = pd.read_sql(sql, engine)
print(top5)
print(f"\n4th-highest = {top5.daily_max_8hr_ppm.iloc[3]} ppm")
```

Cross-check this against `aq.naaqs_design_values` —
the value should match what `step_03_compute_naaqs.py` computed.

### Example 6 — Multi-site monthly heatmap

```python
sql = """
SELECT site_name, year_month,
       monthly_mean::float AS pm25_ugm3
FROM aq.pollutant_monthly
WHERE pollutant_group = 'PM2.5'
  AND county_name = 'Bexar'
  AND year_month BETWEEN '2022-01' AND '2024-12'
ORDER BY site_name, year_month
"""
df = pd.read_sql(sql, engine)
pivot = df.pivot(index='site_name', columns='year_month', values='pm25_ugm3')

import seaborn as sns, matplotlib.pyplot as plt
fig, ax = plt.subplots(figsize=(14, 6))
sns.heatmap(pivot, cmap='RdYlBu_r', cbar_kws={'label': 'PM₂.₅ (µg/m³)'}, ax=ax)
ax.set_title('Bexar County PM₂.₅ Monthly Means 2022–2024')
plt.tight_layout()
```

### Example 7 — Summary table for the manuscript

```python
sql = """
SELECT
    pollutant_group,
    COUNT(DISTINCT aqsid)                                AS n_sites,
    COUNT(DISTINCT EXTRACT(YEAR FROM datetime)::int)     AS n_years,
    COUNT(*)                                             AS n_observations,
    ROUND(AVG(sample_measurement)::numeric, 4)           AS mean,
    ROUND(MIN(sample_measurement)::numeric, 4)           AS min,
    ROUND(MAX(sample_measurement)::numeric, 4)           AS max,
    ROUND(STDDEV(sample_measurement)::numeric, 4)        AS sd
FROM aq.pollutant_hourly
WHERE sample_measurement IS NOT NULL
GROUP BY pollutant_group
ORDER BY pollutant_group
"""
manuscript_table = pd.read_sql(sql, engine)
manuscript_table.to_csv('table_pollutant_summary.csv', index=False)
print(manuscript_table.to_string(index=False))
```

This is exactly the kind of table that goes straight into a Methods or
Results section. Save once, paste anywhere.

### Example 8 — Wind-conditional ozone (pollution rose data)

```python
sql = """
SELECT
    CASE
        WHEN w.wind_deg < 22.5  OR w.wind_deg >= 337.5 THEN 'N'
        WHEN w.wind_deg < 67.5  THEN 'NE'
        WHEN w.wind_deg < 112.5 THEN 'E'
        WHEN w.wind_deg < 157.5 THEN 'SE'
        WHEN w.wind_deg < 202.5 THEN 'S'
        WHEN w.wind_deg < 247.5 THEN 'SW'
        WHEN w.wind_deg < 292.5 THEN 'W'
        WHEN w.wind_deg < 337.5 THEN 'NW'
    END AS wind_dir,
    AVG(p.sample_measurement) AS mean_o3_ppm,
    COUNT(*) AS n
FROM aq.pollutant_hourly p
JOIN aq.weather_hourly w
  ON w.location = 'SA Northwest'
 AND w.datetime_local::timestamp = p.datetime
WHERE p.aqsid = '480290052'
  AND p.pollutant_group = 'Ozone'
  AND w.wind_speed > 1.0   -- ignore calm-wind hours
GROUP BY wind_dir
ORDER BY mean_o3_ppm DESC
"""
rose = pd.read_sql(sql, engine)
print(rose)
```

---

## Cost and quota — what you'll actually pay

Your project is on the **Launch plan** ($19/month base):

| Resource | Included | Overage |
|---|---|---|
| Storage | 10 GB | $1.50/GB-month |
| Compute | 300 CU-hours/month | $0.16/CU-hour |
| Data transfer | unlimited | — |

### What is a CU?

A **Compute Unit** is roughly "one vCPU + 4 GB RAM running for one hour."
Your project autoscales between **0.25 CU and 2 CU** depending on demand,
and **suspends to 0 CU after 5 minutes idle**.

### Real-world cost examples

| Activity | CU-hours used |
|---|---|
| 100 short queries (each finishes in seconds) | <0.5 |
| One 10-minute Colab analysis session | ~0.3 |
| Loading the full hourly tables (one-time pipeline run) | ~2 |
| A team of 4 doing 2 hours of analysis each, daily for a month | ~120 |

**Bottom line:** Typical research use lands at **$0–5/month in compute**
(well within the 300 CU-hour allotment), so you're effectively paying
**$19/month flat** for everything.

### Monitoring usage

Check the Neon console → **Billing → Usage** tab any time. The hourly
breakdown shows exactly when compute is spent.

---

## Troubleshooting

### `psycopg.OperationalError: FATAL: password authentication failed`
The Colab secret value is wrong. Double-check you copied the full URL
including the password (the long `npg_...` string after the `:` in
`username:password@host`).

### First query after a few minutes is slow
Expected — Neon auto-pauses after 5 min idle. The first query wakes
the compute (~500 ms), subsequent queries are fast. `pool_pre_ping=True`
handles this transparently in SQLAlchemy.

### `SSL connection has been closed unexpectedly`
Pipeline is hammering the database (large `INSERT` batches). Wait a
few seconds and retry. If you're running queries from Colab while the
pipeline is loading, you'll see this occasionally.

### `relation "aq.pollutant_hourly" does not exist`
The hourly tables haven't been loaded yet. Run the pipeline:
`python pipeline/run_pipeline.py --only 07`. Until then, only the
five aggregate tables (daily, monthly, NAAQS, combined, registry) exist.

### Query is taking >30 seconds
Either you're missing a `WHERE` clause and pulling millions of rows, or
the query needs an index. The hourly tables are indexed on
`(aqsid, date_local, pollutant_group, year)` for pollutants and
`(location, year, date_local)` for weather — make sure your WHERE
clauses use one of those columns.

### `column "..." does not exist`
Schema reference is in [03_data_schemas.md](./03_data_schemas.md).
Watch out for: `date_local` is text, not date; cast with `::date` for
date arithmetic. `sample_measurement` units depend on `pollutant_group`
(see schema doc).

---

## See also

- [03_data_schemas.md](./03_data_schemas.md) — Complete column-by-column schemas
- [10_usage_sql.md](./10_usage_sql.md) — Original SQL guide (daily aggregates only)
- [09_usage_colab.md](./09_usage_colab.md) — Generic Colab quickstart
- [15_recipes.md](./15_recipes.md) — Worked recipes for common research tasks
- [16_project_timeline.md](./16_project_timeline.md) — Week-by-week analysis plan
