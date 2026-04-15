# 13 — Architecture Decision Record

A running log of significant design decisions, why they were made, and
what alternatives were considered. Format: Architecture Decision Records
(ADR). Each decision is one subsection; once accepted, decisions are not
edited in place — a new ADR supersedes.

---

## ADR-001: Parquet as the primary storage format

**Status:** Accepted (v0.1.0, 2026-04-13)

### Context
The project's raw data is scattered across ~30 CSV files totaling ~1.5 GB.
Loading `Weather_Irradiance_Master_2015_2025.csv` (440 MB) in pandas takes
~20 seconds per run. Notebooks were rebuilding daily means on every
execution.

### Options considered
1. **Keep flat CSVs** — universal, but slow
2. **SQLite** — fast, but poor columnar scan performance for analytical queries
3. **Parquet with Hive partitioning** — columnar, partition pruning, broad tool support
4. **DuckDB-backed file** — fast, but adds a dependency that isn't already in R workflows

### Decision
**Parquet, partitioned by `pollutant_group, year` for pollutants and
`location, year` for weather.**

### Consequences
- 10–50× faster load times with filter pushdown
- ~4× smaller on disk than CSV (compression)
- Requires `pyarrow` (~30 MB install) and `arrow` R package
- Partition pruning means `filters=[("year","=",2023)]` opens only
  ~40 files out of ~100
- Adds a second file format to the project (CSV still emitted for R/Colab
  fallback)

### Trade-offs accepted
- **Binary format** — can't `grep` or `head` a parquet file. OK because
  pipeline logs everything to plain text.
- **Arrow dependency** — negligible cost for Python users, small install for
  R users. Anyone who can't install Arrow has the flat CSVs.

---

## ADR-002: Neon Postgres (free tier) for SQL access

**Status:** Accepted (v0.2.0, 2026-04-13)

### Context
Users want to query data from R, Python, and BI tools without downloading
gigabytes of parquet. They also want to share specific tables with
collaborators who don't have the full project tree.

### Options considered
1. **Local Postgres** — fast, free, but not shareable
2. **Neon (serverless Postgres)** — free tier 0.5 GB, hosted, auto-pause
3. **Supabase** — similar to Neon, 500 MB free, auth features not needed
4. **DuckDB** — no server, but not accessible from other apps
5. **BigQuery** — generous free tier but needs Google Cloud setup

### Decision
**Neon free tier for the hosted database; pipeline loads only the
analysis-ready tables (daily, monthly, NAAQS, combined, site registry).
Raw hourly data stays in parquet only.**

### Consequences
- Zero setup cost to collaborators — they just need a connection string
- 0.5 GB storage ceiling means we can't load hourly data
- Auto-pause after 5 min idle is a minor UX wrinkle (first query is slow)
- Credentials live only in `AQ_POSTGRES_URL` env var, never on disk
- Works from any SQL client or BI tool

### Trade-offs accepted
- **No hourly data in SQL** — acceptable because interactive SQL is for
  aggregates; hourly analysis goes through parquet
- **Free tier limits** — if the project grows past 500 MB, upgrade to
  Neon Launch plan ($19/mo) or move to a university-hosted Postgres

---

## ADR-003: Warning-severity validation for data quirks

**Status:** Accepted (v0.2.1, 2026-04-14)

### Context
The first validation run had 9 failing checks, but several of them
(duplicate rows, site count of 41 vs. spec's 43, date range mismatches)
were data artifacts downstream steps could handle automatically. Halting
on all of them would break reruns whenever the data had benign drift.

### Options considered
1. **Halt on every failure** — strictest, but blocks legit runs
2. **Log all checks but never halt** — silent failures
3. **Two-level severity: error (halt) + warning (log loudly, continue)** — pragmatic

### Decision
**Introduce `CheckResult.severity` with `error` and `warning` levels.
Errors halt, warnings log loudly but continue. Downstream steps are
required to handle what validation flags as warnings.**

### Consequences
- Validation output now shows `30/34 passed (0 errors, 4 warnings)`
- Reruns are resilient to known data quirks (duplicates, minor site changes)
- Documentation (`06_data_quality.md`) explains what each warning means
- CI can still fail the build by treating warnings as errors if desired

### Trade-offs accepted
- **Tolerance creep risk** — over time, operators might keep adding warnings
  until nothing is an error. Mitigation: the reviewer list in
  `06_data_quality.md` forces us to justify each warning explicitly.

---

## ADR-004: Unit normalization at step 01, not at step 03

**Status:** Accepted (v0.2.1, 2026-04-14)

### Context
Ozone rows needed conversion from ppb to ppm. Two places to apply it:
- At the raw-parquet write (step 01) — affects every downstream consumer
- At the NAAQS computation (step 03) — affects only NAAQS math

### Options considered
1. **Normalize only in step 03** — least intrusive, but daily aggregates
   would still be in mixed units
2. **Normalize only in the By_Pollutant CSVs upstream** — out of pipeline scope
3. **Normalize at step 01** — raw parquet becomes the "single source of truth"

### Decision
**Normalize at step 01 via the `UNIT_CONVERSIONS` dictionary.**

### Consequences
- Every downstream step (daily, monthly, NAAQS, combined) inherits correct
  units automatically
- The parquet store is a clean, canonical representation
- Step 01 is the single place to maintain conversion logic
- Documented conversion table in `DATA_CATALOG.md` and `05_methodology.md`

### Trade-offs accepted
- **Loses the "raw" flavor** — parquet is technically not a raw mirror.
  Acceptable because the real raw data lives in `!Final Raw Data/` and is
  untouched.

---

## ADR-005: Haversine nearest-neighbor for AQ↔weather pairing

**Status:** Accepted (v0.2.1, 2026-04-14)

### Context
Pollutant sites and weather stations aren't co-located. The existing
`AQ_Weather_SiteMapping.csv` was keyed by raw lat/lon tuples without a
usable join key, so we needed to recompute pairings from scratch.

### Options considered
1. **Use the existing mapping file as-is** — blocked by missing site IDs
2. **Haversine nearest-neighbor** — simple, reproducible, well-understood
3. **K-nearest with weighted averaging** — more accurate but over-scoped
4. **Kriging / spatial interpolation** — out of scope; user will do this downstream

### Decision
**Haversine nearest-neighbor. Each AQ site is paired to exactly one
weather station by great-circle distance. The `distance_km` is stored in
`aq_weather_daily` so downstream consumers can weight or threshold.**

### Consequences
- Simple, reproducible, unambiguous
- Works for all 41 active sites after merging coordinates from the xlsx
- Many-to-one is allowed (multiple AQ sites → one weather station)
- Downstream spatial interpolation work has a clean handoff

### Trade-offs accepted
- **Single-pairing bias** — a site 25 km from its paired station gets the
  same weight as a site 2 km away. Downstream users must decide when to
  drop or reweight.

---

## ADR-006: Daily rollup in parquet, hourly kept separately

**Status:** Accepted (v0.2.0, 2026-04-13)

### Context
Some analysis needs hourly granularity (diurnal cycles, rolling averages);
most needs daily granularity (correlations, trends, regulatory compliance).

### Decision
**Keep hourly data in `data/parquet/pollutants/` and `data/parquet/weather/`.
Emit daily aggregates in `data/parquet/daily/` and `data/parquet/combined/`.
Both layers are reproducible from hourly; neither is authoritative except
for its level of resolution.**

### Consequences
- Users pick the right layer for their question
- Daily is small enough for Postgres; hourly is not
- Reruns are fast because daily aggregation takes ~15 seconds

---

## ADR-007: Credential handling via environment variable only

**Status:** Accepted (v0.2.0, 2026-04-13)

### Context
Postgres connection strings contain secrets. They must not land on disk
(especially under OneDrive / GitHub).

### Options considered
1. **Plain text in config.yaml** — never OK
2. **`.env` file + python-dotenv** — extra dependency, file on disk
3. **Environment variable only** — zero disk footprint

### Decision
**Read exclusively from `AQ_POSTGRES_URL` env var. Step 07 skips cleanly
(non-fatal) when the variable is absent.**

### Consequences
- No secrets in the pipeline tree — safe to commit the whole `pipeline/`
  directory to git
- User must set the env var before running step 07 on a new machine
- Cross-platform: PowerShell `SetEnvironmentVariable`, shell `export`,
  Colab `userdata.get`

---

## ADR-008: 47-site registry with data_status tags

**Status:** Accepted (v0.3.0, 2026-04-14)

### Context
Data shows 41 active sites. Project spec says 43. Inventory HTML says 47.
Any fixed number was wrong.

### Decision
**Emit all 47 sites in `site_registry.csv` with a `data_status` column:**
- `active` (41) — has measurement data in the pipeline
- `reference` (3) — CPS fence-line monitors, no data yet
- `pending` (2) — TCEQ TAMIS downloads not yet done
- `active+dual_id` (1) — Calaveras Lake EPA side (same physical location as TCEQ 480291609)

Config's `expected.active_sites: 41`, `target_sites: 43`,
`total_inventory: 47`, with validation warnings (not errors) on site-count
drift.

### Consequences
- Site counts across documents finally reconcile
- Future expansion (adding 2 VOC sites → 43 active) is a data change, not
  a code change
- Downstream consumers can filter by `data_status == 'active'` to ignore
  reference-only and pending rows

---

## Potential future ADRs (not yet written)

- **ADR-009:** Migration to a git-tracked repository + GitHub remote
- **ADR-010:** Integration with spatial interpolation (kriging) pipeline
- **ADR-011:** Automated upstream EPA AQS refresh (weekly cron)
- **ADR-012:** Unit tests for NAAQS formulas using synthetic data
