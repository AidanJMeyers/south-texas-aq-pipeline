# v0.4.0 — TCEQ-only migration

**Released:** 2026-05-28
**Previous version:** v0.3.7 (EPA + TCEQ hybrid)
**Migration scope:** Full ingestion / storage / schema rewrite
**Rollback procedure:** see `!Archive_v0_3_7/README.md` in the project tree (not on the docs site — the archive is local-only because it's 1.1 GB)

> v0.4.0 is the first version where **TCEQ is the sole source of truth** for
> every site. The EPA AQS API integration path is retired. Historical v0.3.7
> data is preserved indefinitely in Neon schema `aq_v0_3_7_epa`.

---

## TL;DR for collaborators

If you have a Colab notebook that ran against v0.3.7, here's what changed:

| Old (v0.3.7) | New (v0.4.0) | Action |
|---|---|---|
| `SELECT * FROM aq.pollutant_hourly WHERE pollutant_group='VOCs'` | Use `aq.vocs_1hr` or `aq.vocs_24hr` | VOCs split into their own tables |
| `SELECT data_source FROM ...` | Column removed | All data is TCEQ-sourced now |
| `SELECT * FROM aq.aq_weather_daily` | JOIN `pollutant_daily` + `weather_hourly` in your query | Combined table dropped |
| Calaveras Lake Park (480291609) data | Removed | TSP-only, outside scope |
| Von Ormy (480291097) data | Removed | Not in TCEQ pull |
| Site 0060 in `pollutant_hourly` | Moved to `aq.pollutant_daily_24hr` | 24hr-only sampler |

If you only query criteria pollutants (`Ozone`, `PM2.5`, `PM10`, `CO`, `SO2`,
`NOx_Family`) at hourly cadence and don't use `data_source`, **your queries
keep working unchanged**.

---

## Why the rewrite

The v0.3.7 pipeline blended two upstream sources:

- **EPA AQS API** — pre-aggregated NAAQS metrics; some sites at 24hr cadence
  only; unit conventions varied per parameter; QA assumptions opaque
- **TCEQ TAMIS** — raw hourly observations from the same physical monitors

Every site that reports to EPA is reporting **the same data** to TCEQ, just
without EPA's middleware. Switching to TCEQ-only eliminates an entire class
of harmonization bugs (the v0.3.6 split-name issue documented in
`pipeline/docs/06_data_quality.md` was caused by exactly this mismatch).

Four reasons for the switch:

1. **Uniform cadence + units** — every site reports hourly in the same units.
2. **Weather-parameter alignment** — meteorological covariates are hourly;
   matching pollutant cadence enables direct same-hour joins for modeling
   without aggregation loss.
3. **Predictive modeling strength** — hourly granularity is strictly more
   information than EPA's pre-aggregated 8hr/24hr metrics.
4. **Audit transparency** — re-implementing NAAQS in-pipeline per
   [40 CFR Part 50](https://www.ecfr.gov/current/title-40/chapter-I/subchapter-C/part-50)
   lets us document and version-control every step rather than inheriting an
   opaque EPA aggregation.

---

## The 19 architectural decisions

The full decision matrix was locked in conversation with Aidan on 2026-05-27.
Captured here for the manuscript and for future maintainers.

### Source & history
| # | Decision |
|---:|---|
| 1 | TCEQ is the sole source forever |
| 2 | EPA path is retired — `notebooks/EPA_Refresh_2025_AM.py` is archive-only |
| 3 | `data_source` column dropped (canonical 15 → 14 cols) |
| 4 | `aq_v0_3_7_epa` schema preserved indefinitely |

### Hourly / sampling architecture
| # | Decision |
|---:|---|
| 5 | Site 480290060 (Palo Alto) excluded from `pollutant_hourly` (24hr only) |
| 6 | New `pollutant_daily_24hr` table for any sample-duration-7/X feed |
| 7 | A/B file splits concatenated at ingest |
| 8 | 4 TSP-only sites dropped from registry: 480290623, 480290625, 480290626, 480291609 |

### VOC handling
| # | Decision |
|---:|---|
| 9 | Separate `vocs_1hr` + `vocs_24hr` tables (no forced cadence harmonization) |
| 10 | VOCs excluded from `pollutant_hourly` (criteria pollutants only) |

### NAAQS
| # | Decision |
|---:|---|
| 11 | NAAQS for criteria pollutants per 40 CFR Part 50 |
| 12 | Site 0060 24hr design values still computed (PM10 only) |

### Weather
| # | Decision |
|---:|---|
| 13 | NO combined `aq_weather_daily` table — handle joins in user code |
| 14 | Hourly weather preserved as-is for ad-hoc joins |

### Reference / registry
| # | Decision |
|---:|---|
| 15 | Single `site_registry` with `pollutant_groups_hourly[]` + `pollutant_groups_daily_24hr[]` + `voc_cadence` columns |
| 16 | `parameter_reference` exists as both Postgres table AND markdown doc |

### Post-Phase-1 refinements
| # | Decision |
|---:|---|
| 17 | Parameter reference primary source = EPA AQS code tables (TCEQ SWQM secondary) |
| 18 | Von Ormy 480291097 dropped (not in TCEQ pull) |
| 19 | `pollutant_daily_24hr` routing based on Sample Duration Code 7/X, not hardcoded site list |

---

## New schema layout (`aq.*`)

```
aq.site_registry              42 rows           Sites + pollutant_groups arrays + voc_cadence
aq.parameter_reference        57 rows           AQS codes + units + chemical family + HAP flags
aq.naaqs_design_values       759 rows           Per-site, per-year, per-metric (incl. site 0060 24hr)
aq.pollutant_hourly      4,710,663 rows         CRITERIA pollutants only; site 0060 + VOCs routed away
aq.pollutant_daily         201,290 rows         Per-site daily aggregates from pollutant_hourly
aq.pollutant_daily_24hr        636 rows         24hr-only criteria readings (site 0060 PM10 today)
aq.pollutant_monthly         6,804 rows         Per-site monthly rollups
aq.vocs_1hr              4,964,065 rows         AutoGC 1hr-cadence VOCs (5 sites, 46 chemicals)
aq.vocs_24hr                97,244 rows         AutoGC 24hr-cadence VOCs (8 sites, 48 chemicals)
aq.weather_hourly        1,470,049 rows         OpenWeather + Solcast hourly (unchanged from v0.3.7)
```

Total ~11.5M rows across 10 tables. All `SELECT` rights granted to
`anonymous` + `authenticated` Data API roles; `DEFAULT PRIVILEGES` set so
future tables auto-inherit.

### Canonical 14-column schema (criteria + VOC tables)

```
state_code        Int32      48 always
county_code       Int32      Texas FIPS (13, 29, 61, 91, 187, 215, 255,
                                          273, 323, 355, 469, 479, 493)
site_number       Int32      AQS site number (last 4 digits of aqsid)
parameter_code    Int32      AQS parameter code (see aq.parameter_reference)
poc               Int32      Parameter Occurrence Code (multi-instrument disambiguation)
date_local        text       YYYY-MM-DD
time_local        text       HH:MM (00:00 for daily readings)
sample_measurement double    Reading in canonical units (ppm for Ozone, ppb otherwise)
method_code       Int32      AQS method code
county_name       text       Title-case (e.g. "Bexar", "Nueces")
pollutant_name    text       Friendly name (e.g. "Ozone", "Benzene", "PM2.5 FRM/FEM")
aqsid             text       9-digit AQS site ID (zero-padded state+county+site)
pollutant_group   text       One of: CO, SO2, NOx_Family, Ozone, PM10, PM2.5, VOCs
site_name         text       Canonical site name (e.g. "Camp Bullis_0052")
```

`pollutant_hourly` adds derived `datetime`, `year`, `month`, `hour`, `season`
columns (partition keys: `pollutant_group / year`).

---

## Example queries (v0.4.0)

```sql
-- Most recent ozone hourly readings across all sites
SELECT aqsid, site_name, date_local, time_local, sample_measurement AS ppm
FROM aq.pollutant_hourly
WHERE pollutant_group = 'Ozone'
ORDER BY date_local DESC, time_local DESC
LIMIT 20;

-- VOC profile at Camp Bullis for a specific day
SELECT date_local, time_local, pollutant_name, sample_measurement
FROM aq.vocs_1hr
WHERE aqsid = '480290052' AND date_local = '2024-08-01'
ORDER BY time_local, parameter_code;

-- NAAQS exceedances for 2024
SELECT site_name, metric, value, naaqs_level
FROM aq.naaqs_design_values
WHERE year = 2024 AND exceeds = true
ORDER BY pollutant_group, value DESC;

-- HAP-only VOC measurements (regulatory-relevant subset)
SELECT v.aqsid, v.date_local, v.pollutant_name, v.sample_measurement
FROM aq.vocs_1hr v
JOIN aq.parameter_reference p USING (parameter_code)
WHERE p.is_hap = true AND v.date_local >= '2025-01-01';

-- Sites that measure VOCs (any cadence)
SELECT aqsid, site_name, county_name, voc_cadence
FROM aq.site_registry
WHERE voc_cadence != ''
ORDER BY county_name, aqsid;

-- Site 0060 PM10 24hr readings (not in pollutant_hourly!)
SELECT date_local, sample_measurement AS pm10_ugm3
FROM aq.pollutant_daily_24hr
WHERE aqsid = '480290060'
ORDER BY date_local DESC LIMIT 30;

-- Cross-table join: pollutant + weather (replaces dropped aq_weather_daily)
SELECT p.date_local, p.time_local, p.aqsid, p.sample_measurement AS ozone_ppm,
       w.temp_c, w.humidity, w.wind_speed
FROM aq.pollutant_hourly p
JOIN aq.weather_hourly w
  ON w.date_local = p.date_local
 AND w.hour_local = CAST(SPLIT_PART(p.time_local, ':', 1) AS INTEGER)
 AND w.county_name = p.county_name
WHERE p.aqsid = '480290052' AND p.pollutant_group = 'Ozone'
  AND p.date_local = '2024-08-01';
```

---

## Verification (Phase 6, 2026-05-28)

### Row-count parity

All 10 tables match local v0.4.0 parquet/CSV artifacts exactly. Full report at `!Archive_v0_3_7/db_metadata/cutover_verification.md` in the project tree (archive is local-only).

### Spot-check (raw TXT → Neon)

Validated 14 random rows across 5 representative cases:

| Site / file | Cases checked | Result |
|---|---:|---|
| Site 480290060 Palo Alto (24hr-only routing) | 3 | ✓ All match |
| Pleasanton 480131090 (criteria PM2.5) | 3 | ✓ All match |
| Bexar VOC AutoGC 1hr (county-level routing) | 3 | ✓ All match incl. ethane parameter 43202 |
| Heritage MS 480290622 A-split | 3 | ✓ All match incl. negative SO2 value preserved |
| Heritage MS 480290622 B-split | 3 | ✓ All match incl. multi-POC (POC=03) |

Ozone ppb → ppm conversion verified: 5/5 ozone values land in expected 0.01-0.05 ppm range.

### NAAQS sanity (vs v0.3.7 archive)

Ozone 8hr 4th-max for 2024:
- 7 of 14 sites: **exact match** (diff = 0.00000)
- 7 of 14 sites: tiny diff (0.18-0.57 ppb) attributable to additional 2025 data in the 2026-05-21 pull

Top-3 sites (Elm Creek 0.084, Heritage MS 0.082, Garden Ridge 0.075) all
match exactly between v0.4.0 and v0.3.7 — pipeline correctness confirmed.

---

## Rollback (if ever needed)

```sql
-- 1. Move broken v0.4.0 out of the way
ALTER SCHEMA aq RENAME TO aq_v0_4_0_broken;
-- 2. Restore v0.3.7
ALTER SCHEMA aq_v0_3_7_epa RENAME TO aq;
-- 3. Verify grants survived
SELECT grantee, table_schema, COUNT(*) FROM information_schema.role_table_grants
WHERE table_schema = 'aq' AND grantee IN ('anonymous','authenticated')
GROUP BY 1, 2;
```

Local fallback: `!Archive_v0_3_7/csv_by_pollutant/` + `!Archive_v0_3_7/parquet/`
preserve the v0.3.7 build artifacts at the time of cutover. Git tag
`pre-v0.4.0-migration` (commit `52d1ffd`) marks the v0.3.7 code state.
