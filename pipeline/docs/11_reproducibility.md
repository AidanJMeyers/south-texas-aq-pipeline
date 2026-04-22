# 11 — Reproducibility Guide

How to reproduce the pipeline outputs from scratch on a fresh machine.

!!! success "Pipeline engineering: complete (April 22, 2026)"

    The pipeline is built, validated end-to-end, deployed to Neon, and
    documented. Engineering work is done — the team is now in the
    **analysis phase** ([timeline →](./16_project_timeline.md)).

    **What's in place:**

    - 8 pipeline steps (validate → pollutant parquet → weather parquet →
      NAAQS → daily aggregates → AQ+weather merge → CSV/RDS export →
      Postgres load), all idempotent, all halt-on-error
    - 7 Postgres tables in `aq` schema on Neon Launch plan (~2.3 GB)
      including the full hourly resolution data
    - Anonymous + authenticated Data API access via PostgREST + Neon Auth
    - 17 documentation pages on the public docs site (this site)
    - Self-contained 177 MB inputs bundle on OneDrive for collaborators
    - Source on GitHub at `AidanJMeyers/south-texas-aq-pipeline`

    **Future engineering work** is limited to a single planned data
    refresh in **Week 1 of the analysis timeline (May 1, 2026)** to
    ingest finalized 2025 EPA + TCEQ data. After that refresh, the
    pipeline locks until manuscript submission.

## Pipeline engineering history

How the pipeline got built — for the Methods section and so future
maintainers know what shipped when.

| Version | Date | Engineering milestone |
|---|---|---|
| 0.1.0 | 2026-04-13 | Initial pipeline: 7 By_Pollutant CSVs → partitioned parquet store + NAAQS design value computation per 40 CFR Part 50 |
| 0.2.0 | 2026-04-13 | PostgreSQL loader added (Neon free tier, daily-resolution tables only) |
| 0.2.1 | 2026-04-14 | EPA/TCEQ ozone unit mismatch caught and fixed (TCEQ ppb → ppm normalization in step 01) |
| 0.3.0 | 2026-04-14 | Publication-grade documentation suite (15 docs); 47-site registry with `data_status` tagging |
| 0.3.1 | 2026-04-15 | Site registry corrections; Calaveras Lake (EPA) vs. Calaveras Lake Park (TCEQ) clarified as separate physical stations |
| 0.3.2 | 2026-04-15 | Real Corpus Christi Palm VOCs raw data ingested (1 → 2 active VOC sites; +3.3M rows) |
| 0.3.3 | 2026-04-15 | Calaveras Lake TCEQ feed filter added (drops 478k duplicate rows); Calaveras Lake Park officially excluded (TSP only — outside project scope) |
| 0.3.4 | 2026-04-15 | MkDocs docs site with Material theme; auto-deployment to GitHub Pages via Actions; Mermaid pipeline schematic |
| 0.3.5 | 2026-04-22 | Hourly tables (`pollutant_hourly`, `weather_hourly`) loaded to Neon Launch plan (~2.3 GB total); Data API enabled with `anonymous` + `authenticated` PostgREST roles; Neon Auth provisioned (Google OAuth + email/password) |

The full per-version changelog is at
`pipeline/CHANGELOG.md` in the repo.

---

## Environment requirements

| Component | Minimum | Tested |
|---|---|---|
| OS | Windows 10+, macOS 12+, Linux (Ubuntu 20.04+) | Windows 11 |
| Python | 3.10 | 3.13 |
| Free disk | 5 GB for outputs, 2 GB for raw inputs | — |
| RAM | 8 GB | 16 GB |
| Network | Only needed for step 07 (Postgres load) | — |

Optional:
- **R ≥ 4.0** (for step 06 RDS export; skipped if absent)
- **Postgres access** (for step 07; skipped if `AQ_POSTGRES_URL` unset)

## 1. Clone the code repository

```bash
git clone https://github.com/AidanJMeyers/south-texas-aq-pipeline.git
cd south-texas-aq-pipeline
```

This clones the pipeline code, configs, and documentation (~3 MB).

## 1b. Download the raw data bundle (~2 GB)

The raw EPA, TCEQ, and OpenWeather files are **not** committed to git —
they total ~2 GB and are treated as immutable inputs. They live in a
separate OneDrive share for Melaram Lab members:

**Download:** See the [downloads section on the docs site](https://aidanjmeyers.github.io/south-texas-aq-pipeline/#download-the-pipeline-inputs)
for the current OneDrive URL. External collaborators can request access by
emailing [aidan.meyers@tamucc.edu](mailto:aidan.meyers@tamucc.edu).

**Install into the repo:**

```powershell
# Download south-texas-aq-inputs.zip from OneDrive into the repo root
Expand-Archive south-texas-aq-inputs.zip -DestinationPath .
```

After extraction, the repo tree should look like:

```
south-texas-aq-pipeline/
├── !Final Raw Data/          (from OneDrive)
├── 01_Data/                  (from OneDrive)
├── pipeline/                 (from git)
├── requirements.txt          (from git)
├── README.md                 (from git)
└── ...
```

The pipeline's ROOT auto-detector will find this layout automatically.

## 2. Install Python dependencies

```bash
cd "AirQuality South TX"
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate
pip install -r requirements.txt
```

The required packages (`requirements.txt`):

```
pandas>=2.0
pyarrow>=14.0
pyyaml>=6.0
numpy>=1.24
python-dateutil>=2.8
openpyxl>=3.1
sqlalchemy>=2.0
psycopg[binary]>=3.1
```

## 3. Set the Postgres connection URL (optional)

If you want the pipeline to load into Postgres, set the environment variable.

**Windows (PowerShell, persistent):**
```powershell
[Environment]::SetEnvironmentVariable(
  "AQ_POSTGRES_URL",
  "postgresql://user:pass@host.example.com/dbname?sslmode=require",
  "User"
)
```
Close and reopen PowerShell.

**macOS / Linux:**
```bash
echo 'export AQ_POSTGRES_URL="postgresql://user:pass@host.example.com/dbname?sslmode=require"' >> ~/.zshrc
source ~/.zshrc
```

**For this session only:**
```bash
export AQ_POSTGRES_URL="postgresql://..."
```

Verify:
```bash
echo $AQ_POSTGRES_URL   # unix
echo $env:AQ_POSTGRES_URL   # powershell
```

If unset, step 07 logs a warning and is skipped — this is not a failure.

## 4. Run the pipeline

### Full run from scratch

```bash
python pipeline/run_pipeline.py
```

Expected runtime on a modern laptop SSD: **~15 minutes**, dominated by:
- Step 00 (validation, reads all raw CSVs): ~60s
- Step 01 (pollutant parquet write): ~3 min
- Step 02 (weather parquet write): ~20s
- Step 03 (NAAQS): ~10s
- Step 04 (daily aggregates): ~15s
- Step 05 (AQ+weather merge): ~90s
- Step 06 (CSV verify + optional RDS): ~5s
- Step 07 (Postgres load): ~5–9 minutes (network-bound to Neon)

### Expected output at the end

```
========== PIPELINE SUMMARY ==========
  00  PASS    58.3s
  01  PASS   183.2s
  02  PASS    19.4s
  03  PASS    10.1s
  04  PASS    18.7s
  05  PASS    89.5s
  06  PASS     0.3s
  07  PASS   312.5s
Overall: PASS ✓
```

## 5. Verify the outputs

### Step counts sanity check

```python
import pandas as pd

# Pollutant parquet: ~4.87M rows
all_poll = pd.read_parquet(
    "data/parquet/pollutants",
    filters=[("pollutant_group", "=", "Ozone")],
)
assert 1_400_000 < len(all_poll) < 1_700_000

# NAAQS design values: 764 rows
dv = pd.read_csv("data/csv/naaqs_design_values.csv")
assert 700 <= len(dv) <= 800
assert set(dv.metric) >= {
    "ozone_8hr_4th_max", "pm25_annual_mean", "pm25_24hr_p98",
    "so2_1hr_p99", "no2_1hr_p98",
}

# Site registry: 47 rows (with status tags)
sites = pd.read_csv("data/csv/site_registry.csv")
assert len(sites) == 47
assert sites.data_status.value_counts().get("active", 0) >= 40
```

### Known-good reference values

The following values are expected after a clean run. Significant deviation
means something regressed.

| Metric | Expected |
|---|---|
| Total pollutant rows after dedup | 4,870,334 |
| Exact dupes dropped by step 01 | 973,294 |
| Ozone rows unit-normalized | 638,174 |
| Weather rows | 1,470,049 |
| Weather stations | 15 |
| Daily pollutant rows | 236,070 |
| Monthly pollutant rows | 6,070 |
| NAAQS design value rows | 764 |
| Site registry rows | 47 |
| Active sites | 41 |
| Combined AQ+weather rows | 236,070 |
| Postgres DB total size | ~114 MB |

### Sanity-check NAAQS values (the critical test)

```python
import pandas as pd
dv = pd.read_csv("data/csv/naaqs_design_values.csv")

# Ozone 8-hr 4th-max should be in ppm, not ppb. Bexar values should be
# around 0.05-0.08 ppm (San Antonio MSA is nonattainment).
bexar_o3 = dv.query(
    "county_name == 'Bexar' and metric == 'ozone_8hr_4th_max' and year == 2023"
)
assert (bexar_o3.value < 0.15).all(), "ozone still in ppb? unit normalization broken"
assert (bexar_o3.value > 0.03).all(), "ozone values too low; check data"

# PM2.5 annual means should be 6-15 ug/m3
pm25 = dv.query("metric == 'pm25_annual_mean'")
assert (pm25.value.between(3, 25)).all()
```

## 6. Rebuild a subset

If you only changed one step, rerun just that step:

```bash
# Example: changed NAAQS formulas
python pipeline/run_pipeline.py --only 03,06,07
```

Steps are independent — as long as upstream parquet exists, any downstream
step can run alone.

## 7. Reset and rebuild

To nuke outputs and start fresh:

```bash
rm -rf data/
python pipeline/run_pipeline.py
```

This does NOT touch `01_Data/` or `!Final Raw Data/`.

## 8. Verifying reproducibility across machines

If you want to confirm two machines produce identical outputs:

```bash
# On machine A
python pipeline/run_pipeline.py --skip 07
md5sum data/csv/*.csv

# On machine B
python pipeline/run_pipeline.py --skip 07
md5sum data/csv/*.csv
```

The CSV hashes should match byte-for-byte. The parquet files may have
small size differences due to pyarrow's compression — use row counts
instead:

```python
import pyarrow.dataset as ds
ds.dataset("data/parquet/pollutants").count_rows()
```

## Dependencies pinned for publication reproducibility

For a manuscript protocol, pin exact versions:

```
pandas==2.2.3
pyarrow==17.0.0
pyyaml==6.0.2
numpy==2.1.3
python-dateutil==2.9.0
openpyxl==3.1.5
sqlalchemy==2.0.36
psycopg[binary]==3.2.3
```

Save these to `requirements-pinned.txt` and reference in the Methods section.

## Troubleshooting

**`FileNotFoundError: Could not resolve AQ pipeline ROOT`** — Run from
inside the project directory, or set `AQ_PIPELINE_ROOT`.

**`OSError: [Errno 28] No space left on device`** — Clear `data/` or
move the project off OneDrive (which sometimes has virtual storage limits).

**Step 07 times out** — Neon woke from auto-pause. Re-run `--only 07` and
it should succeed on the second attempt once the compute is warm.

**`psycopg.OperationalError: number of parameters must be between 0 and 65535`** —
Should be fixed in v0.2.1+. If you see this, the chunk-size clamp logic in
step 07 regressed; check `step_07_load_postgres.py::_load_table`.

**Validation warnings but not errors** — Expected. Warnings for duplicates
and site counts are documented data quirks, not failures.
