"""Step 05b — Build site_registry + parameter_reference metadata tables.

v0.4.0 step that produces the small metadata tables Postgres needs:

    1. data/csv/site_registry.csv         — built fresh from parquet stores
                                            via pipeline.utils.site_lookup.
    2. data/csv/parameter_reference.csv   — copied from the Phase 1 inventory
                                            artifact (the seed for aq.parameter_reference).

These two CSVs are loaded into Postgres in step 07.

Runs after the parquet stores exist (01/01c) but before the loader (07).
"""

from __future__ import annotations

import shutil
import sys

from pipeline.utils.io import PipelineConfig, ensure_dir, load_config, write_csv
from pipeline.utils.logging import get_logger, step_timer
from pipeline.utils.site_lookup import build_site_registry


def main(cfg: PipelineConfig | None = None) -> bool:
    cfg = cfg or load_config()
    log = get_logger("05b_build_metadata", log_dir=cfg.path("logs"))

    csv_dir = ensure_dir(cfg.path("csv_exports"))

    # ---- 1. Build site_registry from the new parquet stores ---------------
    with step_timer(log, "build site_registry"):
        reg = build_site_registry(cfg)
        n_active   = (reg["data_status"] == "active").sum()
        n_disabled = (reg["data_status"] == "disabled").sum()
        n_voc1     = (reg["voc_cadence"] == "1hr").sum()
        n_voc24    = (reg["voc_cadence"] == "24hr").sum()
        n_vocboth  = (reg["voc_cadence"] == "both").sum()
        log.info(
            f"  registry: {len(reg)} rows "
            f"(active={n_active}, disabled={n_disabled})"
        )
        log.info(
            f"  voc cadence: 1hr={n_voc1}, 24hr={n_voc24}, both={n_vocboth}"
        )

    target = csv_dir / "site_registry.csv"
    write_csv(reg, target)
    log.info(f"  wrote {target} ({target.stat().st_size/1024:.1f} KB)")

    # ---- 2. Copy parameter_reference.csv from inventory artifact ----------
    src = cfg.root / "!Archive_v0_3_7" / "inventory" / "parameter_reference.csv"
    dst = csv_dir / "parameter_reference.csv"
    if not src.exists():
        log.error(f"parameter_reference seed not found at {src}")
        return False
    shutil.copy2(src, dst)
    log.info(f"  copied parameter_reference: {dst} ({dst.stat().st_size/1024:.1f} KB)")

    # Also copy a canonical reference into 01_Data/Reference/ for any
    # downstream script that uses cfg.path("parameter_reference").
    ref_target = cfg.path("parameter_reference")
    ensure_dir(ref_target.parent)
    shutil.copy2(src, ref_target)
    log.info(f"  copied parameter_reference: {ref_target}")

    return True


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
