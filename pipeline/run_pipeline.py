"""Pipeline orchestrator — single entry point for the end-to-end build.

Usage::

    python pipeline/run_pipeline.py                     # full pipeline
    python pipeline/run_pipeline.py --only 01,02         # only steps 01, 02
    python pipeline/run_pipeline.py --skip 06            # skip RDS export
    python pipeline/run_pipeline.py --config my.yaml     # custom config
    python pipeline/run_pipeline.py --dry-run            # resolve + print only

Each step is idempotent — safe to re-run. The orchestrator halts on the first
failure unless ``--continue-on-error`` is passed.
"""

from __future__ import annotations

import argparse
import importlib
import sys
import time
from pathlib import Path
from typing import Callable

# Make "pipeline" importable when run as a script
_HERE = Path(__file__).resolve().parent
if str(_HERE.parent) not in sys.path:
    sys.path.insert(0, str(_HERE.parent))

from pipeline.utils.io import load_config, PipelineConfig       # noqa: E402
from pipeline.utils.logging import get_logger                   # noqa: E402


STEPS: list[tuple[str, str]] = [
    ("00", "pipeline.step_00_validate_raw"),
    ("01", "pipeline.step_01_build_pollutant_store"),
    ("02", "pipeline.step_02_build_weather_store"),
    ("03", "pipeline.step_03_compute_naaqs"),
    ("04", "pipeline.step_04_compute_daily_aggregates"),
    ("05", "pipeline.step_05_merge_aq_weather"),
    ("06", "pipeline.step_06_export_analysis_ready"),
    ("07", "pipeline.step_07_load_postgres"),
]


def _parse_csv_list(s: str | None) -> set[str]:
    return {x.strip() for x in s.split(",") if x.strip()} if s else set()


def _summary_row(tag: str, ok: bool, seconds: float) -> str:
    status = "PASS" if ok else "FAIL"
    return f"  {tag}  {status}  {seconds:6.1f}s"


def run(
    config_path: str | None = None,
    only: set[str] | None = None,
    skip: set[str] | None = None,
    dry_run: bool = False,
    continue_on_error: bool = False,
) -> bool:
    cfg = load_config(config_path)
    log = get_logger("run_pipeline", log_dir=cfg.path("logs"))

    log.info(f"ROOT    = {cfg.root}")
    log.info(f"Config  = {config_path or 'pipeline/config.yaml'}")
    log.info(f"Only    = {sorted(only) if only else 'ALL'}")
    log.info(f"Skip    = {sorted(skip) if skip else '(none)'}")
    log.info(f"Dry-run = {dry_run}")

    if dry_run:
        for tag, module in STEPS:
            log.info(f"  would run: {tag}  ({module})")
        return True

    overall_ok = True
    summary: list[str] = []

    for tag, module_name in STEPS:
        if only and tag not in only:
            continue
        if skip and tag in skip:
            continue

        log.info(f"\n========== STEP {tag}  {module_name} ==========")
        t0 = time.perf_counter()
        try:
            mod = importlib.import_module(module_name)
            main_fn: Callable[[PipelineConfig], bool] = getattr(mod, "main")
            step_ok = bool(main_fn(cfg))
        except Exception as e:  # noqa: BLE001
            log.exception(f"STEP {tag} raised: {e}")
            step_ok = False
        dt = time.perf_counter() - t0
        summary.append(_summary_row(tag, step_ok, dt))

        if not step_ok:
            overall_ok = False
            if not continue_on_error:
                log.error(f"Halting: step {tag} failed")
                break

    log.info("\n========== PIPELINE SUMMARY ==========")
    for row in summary:
        log.info(row)
    log.info("Overall: " + ("PASS ✓" if overall_ok else "FAIL ✗"))
    return overall_ok


def _cli() -> int:
    ap = argparse.ArgumentParser(description="Run the South Texas AQ data pipeline")
    ap.add_argument("--config", help="Path to config.yaml (default pipeline/config.yaml)")
    ap.add_argument("--only", help="Comma-separated step IDs to run (e.g. '01,02')")
    ap.add_argument("--skip", help="Comma-separated step IDs to skip")
    ap.add_argument("--dry-run", action="store_true", help="Resolve + print only")
    ap.add_argument("--continue-on-error", action="store_true")
    args = ap.parse_args()

    ok = run(
        config_path=args.config,
        only=_parse_csv_list(args.only),
        skip=_parse_csv_list(args.skip),
        dry_run=args.dry_run,
        continue_on_error=args.continue_on_error,
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_cli())
