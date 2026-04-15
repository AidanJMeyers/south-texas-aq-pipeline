"""Standardized logging for pipeline steps.

Every step calls ``get_logger('01_build_pollutant_store')`` at the top of
``main()``. The returned logger writes to stdout AND to
``data/_logs/{step}.log`` so reruns are auditable.
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from pathlib import Path


def get_logger(step_name: str, log_dir: str | Path = "data/_logs") -> logging.Logger:
    """Return a configured logger that writes to stdout + ``log_dir/{step_name}.log``.

    Re-entrant: calling twice with the same ``step_name`` returns the same
    logger without duplicating handlers.
    """
    logger = logging.getLogger(f"aq_pipeline.{step_name}")
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    logger.addHandler(stream)

    log_dir_p = Path(log_dir)
    log_dir_p.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(log_dir_p / f"{step_name}.log", mode="a", encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    logger.propagate = False
    return logger


@contextmanager
def step_timer(logger: logging.Logger, label: str):
    """Context manager that logs a start message and wall-clock duration.

    Usage::

        with step_timer(log, "read CSV"):
            df = pd.read_csv(...)
    """
    logger.info(f"START {label}")
    t0 = time.perf_counter()
    try:
        yield
    finally:
        dt = time.perf_counter() - t0
        logger.info(f"DONE  {label}  ({dt:.1f}s)")
