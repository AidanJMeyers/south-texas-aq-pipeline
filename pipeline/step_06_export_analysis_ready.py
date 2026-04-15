"""Step 06 — Export analysis-ready flat files (CSV + optional RDS).

Verifies that all expected ``data/csv/*.csv`` exist and shells out to R to
create ``.rds`` bundles for users who prefer R-native formats. RDS export is
best-effort: if R is not on PATH, the step logs a warning and continues.

Inputs: everything produced by steps 03–05.

Outputs:
    data/rds/master_pollutant.rds
    data/rds/master_weather.rds
    data/rds/combined_daily.rds
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from pipeline.utils.io import PipelineConfig, ensure_dir, load_config
from pipeline.utils.logging import get_logger, step_timer


EXPECTED_CSVS = [
    "daily_pollutant_means.csv",
    "naaqs_design_values.csv",
    "combined_aq_weather_daily.csv",
    "site_registry.csv",
]


def _check_csvs(cfg: PipelineConfig, log) -> bool:
    csv_dir = cfg.path("csv_exports")
    missing = [f for f in EXPECTED_CSVS if not (csv_dir / f).exists()]
    for f in EXPECTED_CSVS:
        p = csv_dir / f
        if p.exists():
            size_mb = p.stat().st_size / 1e6
            log.info(f"  ✓ {f} ({size_mb:.1f} MB)")
        else:
            log.error(f"  ✗ MISSING {f}")
    return not missing


def _export_rds(cfg: PipelineConfig, log) -> bool:
    rscript = shutil.which("Rscript")
    if not rscript:
        log.warning("Rscript not on PATH; skipping RDS export (flat CSVs are sufficient).")
        return True
    script = cfg.root / "pipeline" / "utils" / "export_rds.R"
    if not script.exists():
        log.warning(f"Helper script not found: {script}")
        return True
    ensure_dir(cfg.path("rds_exports"))
    with step_timer(log, f"Rscript {script.name}"):
        result = subprocess.run(
            [rscript, str(script), str(cfg.root)],
            capture_output=True, text=True,
        )
    log.info(result.stdout.strip())
    if result.returncode != 0:
        log.warning(f"Rscript failed:\n{result.stderr}")
        return True  # non-fatal
    return True


def main(cfg: PipelineConfig | None = None) -> bool:
    cfg = cfg or load_config()
    log = get_logger("06_export_analysis_ready", log_dir=cfg.path("logs"))

    log.info("Verifying CSV exports …")
    if not _check_csvs(cfg, log):
        return False

    log.info("Attempting RDS export …")
    _export_rds(cfg, log)

    log.info("Export layer complete.")
    return True


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
