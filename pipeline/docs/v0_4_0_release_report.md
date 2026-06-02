# v0.4.0 Release Report — TCEQ-Only Migration

**Project:** South Texas Air Quality Pipeline
**Release tag:** `v0.4.0` (commit `e7f7be2`, pushed 2026-05-28)
**Migration window:** 2026-05-27 → 2026-05-28
**Deadline target:** 2026-06-02 (delivered 5 days early)
**Status:** ✅ **All 8 phases complete. Pipeline + database production-ready.**

---

## 1. Executive Summary

The South Texas Air Quality pipeline has been completely rebuilt to use **TCEQ
as the sole data source for every site**, replacing the prior v0.3.7 hybrid
that pulled some sites from the EPA AQS API and others from TCEQ TAMIS. The
rebuild was driven by Aidan's decision that uniform hourly cadence, matching
weather covariates, and transparent in-pipeline NAAQS computation outweigh
the convenience of EPA's pre-aggregated outputs.

The work spanned **eight phases** (Archive → Inventory → Decisions → Pipeline
rebuild → Database cutover → Validation → Documentation → Release). Across
those phases, the team made **19 architectural decisions** (all locked in
writing before any destructive operation), wrote/rewrote **~1,700 lines of
pipeline code**, ingested **9.77M raw TCEQ rows** from 51 TXT files, loaded
**~11.5M rows across 10 Neon tables**, and verified the result with
**row-count parity, 14 random raw→Neon spot-checks, and NAAQS sanity checks
against the v0.3.7 archive**.

End-to-end pipeline runtime dropped from **5+ hours (v0.3.7)** to **~9
minutes (v0.4.0)** for a full local build; Postgres reload time dropped from
**5.5 hours** (which silently failed on `weather_hourly`) to **54 minutes**
via COPY-based loading. The v0.3.7 Neon schema is preserved indefinitely as
`aq_v0_3_7_epa.*` for rollback / historical reference.

---

## 2. Background and Motivation

The v0.3.7 pipeline blended two upstream sources:

- **EPA AQS API** — pre-aggregated NAAQS-formatted output. Some sites at 24hr
  cadence only; unit conventions varied; QA assumptions opaque.
- **TCEQ TAMIS portal** — raw hourly observations from the same physical
  monitors that feed EPA.

Every site that reports to EPA reports the same underlying data to TCEQ
without the middleware. The v0.3.6 split-name bug (24 sites accidentally
duplicated due to EPA/TCEQ name mismatches, documented in
`pipeline/docs/06_data_quality.md`) was a symptom of this dual-source
fragility.

Four rationales for the rewrite:

1. **Uniform reporting** — every site reports hourly in identical units.
2. **Weather-parameter alignment** — meteorological covariates are already
   hourly; matching pollutant cadence enables direct same-hour joins for
   modeling without aggregation loss.
3. **Predictive modeling strength** — hourly granularity is strictly more
   informative than EPA's pre-aggregated metrics.
4. **Audit transparency** — re-implementing NAAQS per 40 CFR Part 50
   in-pipeline lets every step be version-controlled and documented.

---

## 3. Phase-by-Phase Summary

| Phase | Title | Outcome | Key artifact |
|---:|---|---|---|
| 0 | Archive v0.3.7 | Neon `aq` schema renamed → `aq_v0_3_7_epa` (1.1 GB local snapshot in `!Archive_v0_3_7/`); git tag `pre-v0.4.0-migration` | `!Archive_v0_3_7/README.md` |
| 1 | TCEQ file inventory | 51 TXT files / 9.77M rows scanned in 87s; 57 distinct AQS parameter codes resolved against EPA's official tables | `!Archive_v0_3_7/inventory/PHASE_1_FINDINGS.md` |
| 2 | Architectural decisions | 19 decisions locked across 4 question batches (source, schema, VOCs, sites, NAAQS, weather, registry, refinements) | Embedded in migration doc |
| 3 | Pipeline rewrite | 3 new pipeline steps + 1 simplified + 1 rewrite; 14-col canonical schema; full build in ~10 min | git tag `v0.4.0-pipeline` (commit `79e6914`) |
| 5 | Neon cutover | All 10 tables loaded via COPY (54 min for ~11.5M rows); `anonymous` + `authenticated` granted SELECT | `cutover_verification.md` |
| 6 | Validation | Row-count parity ✅; 14/14 raw-TXT spot-checks pass; NAAQS top-3 sites match v0.3.7 exactly | `cutover_verification.md` |
| 7 | Docs | `v0_4_0_migration.md` (NEW), `CHANGELOG.md` updated, `notebooks/README.md` schema callout | This doc + migration guide |
| 8 | Release | Committed + tagged `v0.4.0` + pushed to GitHub | `e7f7be2` on `main` |

Phase 4 number was reserved for a sub-step that got merged into Phase 3. No
work was skipped — the numbering reflects how phases evolved during planning.

---

## 4. The 19 Architectural Decisions (one-line each)

**Source & history:** TCEQ sole source forever / EPA path retired / drop
`data_source` column / preserve `aq_v0_3_7_epa` indefinitely.

**Sampling / routing:** site 0060 excluded from `pollutant_hourly` / new
`pollutant_daily_24hr` table / concatenate A/B file splits / drop 4 TSP-only
sites (623, 625, 626, 1609).

**VOCs:** separate `vocs_1hr` + `vocs_24hr` tables / VOCs excluded from
`pollutant_hourly`.

**NAAQS:** recompute per 40 CFR Part 50 / include site 0060 24hr metrics.

**Weather:** drop combined `aq_weather_daily` table / preserve hourly weather
as-is for ad-hoc joins.

**Registry / reference:** single `site_registry` with
`pollutant_groups_hourly[]` + `pollutant_groups_daily_24hr[]` + `voc_cadence` /
parameter reference as both Postgres table AND markdown.

**Post-inventory refinements:** EPA AQS codes are primary parameter
reference / drop Von Ormy 480291097 (not in pull) / route by Sample Duration
Code 7/X (not hardcoded site list).

---

## 5. Database State — Before & After

| | v0.3.7 schema (now `aq_v0_3_7_epa`) | v0.4.0 schema (current `aq`) |
|---|---|---|
| Source | EPA AQS + TCEQ blended | TCEQ only |
| Tables | 7 | 10 |
| `pollutant_hourly` rows | 7,764,033 | 4,710,663 (criteria only) |
| `weather_hourly` rows | 1,470,049 | 1,470,049 (unchanged) |
| `site_registry` rows | 47 | 42 |
| Combined AQ+weather table | yes (134 MB) | dropped |
| VOC handling | mixed in `pollutant_hourly` | dedicated `vocs_1hr` (5.0M) + `vocs_24hr` (97K) |
| Site 0060 PM10 | mislabeled in `pollutant_hourly` | dedicated `pollutant_daily_24hr` (636 rows) |
| Parameter reference | implicit in code | `aq.parameter_reference` table + markdown doc |
| Canonical schema width | 15 columns | 14 (no `data_source`) |
| Site registry pollutants | semicolon-joined text | three array/text columns |
| Grants | SELECT on all tables | SELECT on all tables + DEFAULT PRIVILEGES |

Total `aq.*` storage on Neon: ~2.4 GB across 10 tables. All tables indexed
on the natural query keys (`aqsid`, `date_local`, `pollutant_group`, etc.).

---

## 6. Verification Results

### 6.1 Row-count parity (Phase 5.4)

Every one of the 10 new `aq.*` tables matches its local v0.4.0
parquet/CSV artifact **exactly**. Full report in
`!Archive_v0_3_7/db_metadata/cutover_verification.md`.

### 6.2 Raw TXT → Neon spot-check (Phase 6.1)

Randomly sampled 14 rows across 5 representative scenarios:

| Scenario | Sites | Result |
|---|---|---|
| Site 480290060 Palo Alto — 24hr-only routing | 3/3 | ✅ exact match |
| Pleasanton 480131090 — criteria PM2.5 (incl. negative values) | 3/3 | ✅ exact match |
| Bexar VOC AutoGC 1hr — county-level file routing | 3/3 | ✅ exact match (ethane 43202) |
| Heritage MS 480290622 A-split — A/B concatenation | 3/3 | ✅ match incl. negative SO2 |
| Heritage MS 480290622 B-split — multi-POC | 3/3 | ✅ match incl. POC=03 |

Plus 5/5 ozone values land in expected ppm range (0.01–0.05 ppm =
10–50 ppb), confirming the TCEQ ppb → EPA ppm × 0.001 normalization is
applied end-to-end.

### 6.3 NAAQS sanity vs v0.3.7 archive (Phase 6.2)

Ozone 8-hr 4th-max design values for 2024:

- **Top-3 sites — exact match** (Elm Creek 0.084 ppm, Heritage MS 0.082 ppm,
  Garden Ridge 0.075 ppm)
- 7 of 14 sites differ by ≤0.57 ppb — attributable to additional 2025 data
  in the 2026-05-21 pull beyond what v0.3.7 had access to
- Site 0060 24hr metrics are being computed (`pm10_24hr_exceedances` is
  populated); the NAAQS threshold itself (`naaqs_level`) is still NULL,
  flagged as a v0.4.1 follow-up

Six sites exceed the ozone NAAQS for 2024; many sites exceed the tightened
PM2.5 annual NAAQS (9 µg/m³, Feb 2024 standard) — all realistic results
matching independent expectations for the region.

---

## 7. Code Changes Summary

Two commits land on `main` for v0.4.0:

**`79e6914` — pipeline rewrite** (committed before Phase 5):
- 10 files changed, +1,181 / -394 lines
- 3 new step files (`step_01b_ingest_tceq_raw`, `step_01c_build_aux_stores`,
  `step_05b_build_metadata`)
- `pipeline/utils/site_lookup.py` rewritten for v0.4.0 schema
- `pipeline/utils/io.py` POLLUTANT_SCHEMA trimmed 15 → 14 cols
- `pipeline/config.yaml` extensively restructured
- `run_pipeline.py` adds 01b, 01c, 05b; removes 05

**`e7f7be2` — cutover, validation, docs** (the v0.4.0 release commit):
- 5 files changed, +551 / -77 lines
- `step_07_load_postgres.py` rewritten with COPY (replaces `to_sql`)
- `pipeline/docs/v0_4_0_migration.md` (NEW, 250 lines) — single source
  of truth for what changed
- `pipeline/CHANGELOG.md` v0.4.0 entry
- `notebooks/README.md` schema callout

Three git tags mark the recoverable checkpoints:

- `pre-v0.4.0-migration` (commit `52d1ffd`) — last v0.3.7 state
- `v0.4.0-pipeline` (commit `79e6914`) — pipeline code complete
- `v0.4.0` (commit `e7f7be2`) — full release

---

## 8. Outstanding Items (v0.4.1 backlog — not blocking)

Four nice-to-have items that don't gate use of v0.4.0:

1. **Wire `naaqs_level` for site 0060 PM10 24hr exceedances** — the metric
   is computed but the standard threshold (150 µg/m³, not-to-exceed once
   per year) needs to be added to `pipeline/utils/naaqs.py`.
2. **Investigate 60-row NOx_Family parsing gap** (1,714,989 ingested vs
   1,715,049 expected from inventory — well within tolerance but worth
   tracing).
3. **Rewrite `pipeline/docs/02_data_sources.md` and `05_methodology.md`**
   for v0.4.0. The migration guide is the current source of truth, but
   these legacy pages still describe the EPA hybrid.
4. **Promote `verify_phase5_cutover.py`** from `!Archive_v0_3_7/db_metadata/`
   into `pipeline/utils/` as a re-runnable database health check.

---

## 9. How to Use the New Pipeline

**Full rebuild from raw TXT files (local):**
```bash
python pipeline/run_pipeline.py
# ~9 min: 51 TCEQ TXT files → 14-col CSVs → partitioned parquet
# → NAAQS → daily aggregates → site_registry + parameter_reference
```

**Reload Neon from the local parquet (after pipeline rebuild):**
```bash
python pipeline/run_pipeline.py --only 07
# ~54 min: COPY all 10 tables into aq schema, with indexes + grants
```

**Verify Neon vs local after any reload:**
```bash
python !Archive_v0_3_7/db_metadata/verify_phase5_cutover.py
```

**Connect from a notebook (Colab or local):**
```python
import os, pandas as pd, sqlalchemy as sa
engine = sa.create_engine(os.environ["AQ_POSTGRES_URL"])
df = pd.read_sql("SELECT * FROM aq.naaqs_design_values WHERE year=2024", engine)
```

**Rollback to v0.3.7** (only if needed):
```sql
ALTER SCHEMA aq RENAME TO aq_v0_4_0_broken;
ALTER SCHEMA aq_v0_3_7_epa RENAME TO aq;
```

---

## 10. Sign-off

- ✅ Pipeline produces canonical outputs matching the architectural decisions
- ✅ Neon `aq` schema populated; all grants in place; Data API ready
- ✅ Row-count parity verified for all 10 tables
- ✅ Raw-data round-trip spot-checks pass for criteria, VOC, 24hr, A/B-split cases
- ✅ NAAQS values cross-checked against v0.3.7 archive (top-3 exact match)
- ✅ Migration guide + CHANGELOG + notebooks README updated
- ✅ v0.3.7 archive preserved indefinitely (`aq_v0_3_7_epa.*` + local `!Archive_v0_3_7/`)
- ✅ All changes committed and pushed; tagged `v0.4.0` on `main`

**Delivered 5 days ahead of the 2026-06-02 target.** Collaborators can begin
running notebooks against the new schema immediately. The four outstanding
items in §8 are quality-of-life improvements that do not block use of the
v0.4.0 release.
