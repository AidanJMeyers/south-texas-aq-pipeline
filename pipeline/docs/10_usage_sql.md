# 10 — SQL / Postgres Usage Guide

Querying the pipeline's Postgres tables directly. Works with any SQL client,
BI tool, notebook, or application that speaks PostgreSQL wire protocol.

## Connection

**Host:** Neon (free tier) or your own Postgres 14+ instance
**Schema:** `aq`
**Credential source:** `AQ_POSTGRES_URL` environment variable

### Get the connection URL

The URL is stored as a User-scope Windows environment variable:

```powershell
# Print to verify (safe to share the host; redact the password before)
echo $env:AQ_POSTGRES_URL
```

Format:
```
postgresql://user:password@ep-xxx.us-east-2.aws.neon.tech/neondb?sslmode=require
```

### Connect with `psql`

```bash
psql "$AQ_POSTGRES_URL"
```

Inside psql:
```
\dn                    -- list schemas
\dt aq.*               -- list tables in aq
\d aq.pollutant_daily  -- describe a table
```

### Connect from a GUI (DBeaver, TablePlus, pgAdmin)

Parse the URL into host / db / user / password fields and set **SSL mode =
require**. Neon requires TLS.

## Tables

| Table | Rows | Primary indexes |
|---|---:|---|
| `aq.site_registry` | 47 | `aqsid` |
| `aq.naaqs_design_values` | 764 | `aqsid`, `year`, `metric`, `pollutant_group` |
| `aq.pollutant_daily` | 236,070 | `aqsid`, `date_local`, `pollutant_group` |
| `aq.pollutant_monthly` | 6,070 | `aqsid`, `year_month`, `pollutant_group` |
| `aq.aq_weather_daily` | 236,070 | `aqsid`, `date_local` |

See [03_data_schemas.md](./03_data_schemas.md) for column-level documentation.

## Canonical queries

### Q1 — Which sites exceeded the 8-hr ozone NAAQS in 2023?

```sql
SELECT aqsid, site_name, county_name, value, naaqs_level
FROM aq.naaqs_design_values
WHERE year   = 2023
  AND metric = 'ozone_8hr_4th_max'
  AND exceeds
ORDER BY value DESC;
```

### Q2 — Annual ozone trend at Camp Bullis (480290052)

```sql
SELECT year, value AS fourth_max_ppm
FROM aq.naaqs_design_values
WHERE aqsid  = '480290052'
  AND metric = 'ozone_8hr_4th_max'
ORDER BY year;
```

### Q3 — County-level annual average ozone design values

```sql
SELECT year, county_name,
       COUNT(*)            AS n_sites,
       ROUND(AVG(value)::numeric, 4) AS avg_ppm,
       ROUND(MAX(value)::numeric, 4) AS max_ppm
FROM aq.naaqs_design_values
WHERE metric = 'ozone_8hr_4th_max'
GROUP BY year, county_name
ORDER BY year, county_name;
```

### Q4 — Daily PM₂.₅ mean in Bexar County by month

```sql
SELECT DATE_TRUNC('month', date_local::date) AS month,
       ROUND(AVG(mean)::numeric, 2) AS mean_pm25_ugm3,
       COUNT(*)                     AS n_site_days
FROM aq.pollutant_daily
WHERE pollutant_group = 'PM2.5'
  AND county_name     = 'Bexar'
  AND valid_day
GROUP BY 1
ORDER BY 1;
```

### Q5 — Correlate daily ozone and temperature at a single site

```sql
SELECT date_local,
       mean   AS ozone_ppm,
       temp_c,
       humidity,
       wind_speed
FROM aq.aq_weather_daily
WHERE aqsid           = '480290052'
  AND pollutant_group = 'Ozone'
  AND valid_day
ORDER BY date_local;
```

### Q6 — Summer vs winter PM₂.₅ across all counties

```sql
WITH seasons AS (
  SELECT *,
         CASE
           WHEN EXTRACT(month FROM date_local::date) IN (6,7,8)  THEN 'JJA'
           WHEN EXTRACT(month FROM date_local::date) IN (12,1,2) THEN 'DJF'
           ELSE NULL
         END AS season
  FROM aq.pollutant_daily
  WHERE pollutant_group = 'PM2.5' AND valid_day
)
SELECT county_name, season,
       ROUND(AVG(mean)::numeric, 2) AS mean_pm25
FROM seasons
WHERE season IS NOT NULL
GROUP BY county_name, season
ORDER BY county_name, season;
```

### Q7 — All NAAQS exceedances across all years and pollutants

```sql
SELECT pollutant_group, metric, year,
       COUNT(*) FILTER (WHERE exceeds) AS n_exceeding_sites,
       COUNT(*)                         AS n_sites
FROM aq.naaqs_design_values
GROUP BY pollutant_group, metric, year
HAVING COUNT(*) FILTER (WHERE exceeds) > 0
ORDER BY pollutant_group, metric, year;
```

### Q8 — Weather pairing distances

```sql
SELECT DISTINCT aqsid, site_name, county_name, weather_station, distance_km
FROM aq.aq_weather_daily
ORDER BY distance_km DESC;
```

Rows with large `distance_km` indicate pollutant sites whose nearest weather
station is far away — worth flagging in analysis.

### Q9 — Sites with 2024 PM₂.₅ annual above 10 µg/m³

```sql
SELECT aqsid, site_name, county_name, value
FROM aq.naaqs_design_values
WHERE metric = 'pm25_annual_mean'
  AND year   = 2024
  AND value  > 10
ORDER BY value DESC;
```

### Q10 — Dual-ID deduplication sanity check

```sql
SELECT dual_id_group, aqsid, site_name, county_name, lat, lon, data_status
FROM aq.site_registry
WHERE dual_id_group <> ''
ORDER BY dual_id_group, aqsid;
```

Should return the 2 Calaveras Lake rows (480290059 EPA + 480291609 TCEQ) at
the same coordinates. Choose one canonical ID for spatial joins.

## Read-only users for collaborators

To share the Neon instance with collaborators without exposing write
permissions, create a read-only role:

```sql
-- Run as the owner (once)
CREATE ROLE aq_reader WITH LOGIN PASSWORD 'pick_a_password';
GRANT USAGE ON SCHEMA aq TO aq_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA aq TO aq_reader;

-- Ensure future tables are also readable
ALTER DEFAULT PRIVILEGES IN SCHEMA aq
  GRANT SELECT ON TABLES TO aq_reader;
```

Share the connection URL using the `aq_reader` user instead of
`neondb_owner`. Collaborators can read everything but cannot modify or drop.

## Database size monitoring

```sql
SELECT pg_size_pretty(pg_database_size(current_database())) AS total_size;

SELECT table_name,
       pg_size_pretty(pg_total_relation_size(('aq.' || table_name)::regclass)) AS size
FROM information_schema.tables
WHERE table_schema = 'aq'
ORDER BY pg_total_relation_size(('aq.' || table_name)::regclass) DESC;
```

Current size: **~114 MB / 500 MB** Neon free tier ceiling.

## BI tool connections

| Tool | Notes |
|---|---|
| **Tableau / Power BI** | Add a PostgreSQL data source, paste host/db/user, set SSL = require |
| **Metabase** | Native PostgreSQL driver; point schema to `aq` |
| **Grafana** | PostgreSQL data source plugin; works with Neon |
| **Excel** | Use `Data > Get Data > From Database > From PostgreSQL` on Windows; requires `psqlODBC` driver |

For any BI tool, **start with the NAAQS design values and monthly aggregates**
— they're small, already summarized, and render quickly.

## Gotchas

1. **`date_local` is stored as text.** Cast to `::date` before date
   arithmetic: `date_local::date + interval '7 days'`.

2. **`year_month` in `pollutant_monthly` is text** (e.g. `'2023-07'`). Parse
   with `to_date(year_month, 'YYYY-MM')` if needed.

3. **Neon auto-pauses after 5 min idle.** First query after a pause takes
   ~500 ms. Client libraries with `pool_pre_ping=True` handle this.

4. **Free tier = 500 MB storage.** If you need to add more data, either
   upgrade Neon ($19/mo for 10 GB), swap to a different host, or trim the
   `aq_weather_daily` table.

5. **Indexes are B-tree only.** If you add a lot of text-search queries,
   consider adding GIN indexes manually.
