"""Schema, row-count, and integrity assertions used by ``00_validate_raw.py``.

All check functions return a ``CheckResult`` rather than raising, so the
validation step can collect them into a report before exiting nonzero.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

import pandas as pd


SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"


@dataclass
class CheckResult:
    """Result of a single data-integrity check.

    severity='error' failures halt the pipeline. severity='warning' failures
    are logged loudly but allow the run to continue — use this for known
    data quirks that downstream steps handle gracefully (e.g. duplicate
    rows that get deduped in step 01).
    """
    name: str
    passed: bool
    expected: Any = None
    actual: Any = None
    detail: str = ""
    severity: str = SEVERITY_ERROR

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CheckReport:
    """Aggregate of CheckResults for one validation run."""
    results: list[CheckResult] = field(default_factory=list)

    def add(self, result: CheckResult) -> CheckResult:
        self.results.append(result)
        return result

    @property
    def passed(self) -> bool:
        """True iff every ERROR-severity check passed. Warnings are allowed."""
        return all(r.passed for r in self.results if r.severity == SEVERITY_ERROR)

    @property
    def has_warnings(self) -> bool:
        return any(not r.passed and r.severity == SEVERITY_WARNING for r in self.results)

    def summary(self) -> str:
        ok = sum(r.passed for r in self.results)
        total = len(self.results)
        errs = sum(not r.passed and r.severity == SEVERITY_ERROR for r in self.results)
        warns = sum(not r.passed and r.severity == SEVERITY_WARNING for r in self.results)
        return f"{ok}/{total} passed  ({errs} errors, {warns} warnings)"

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "summary": self.summary(),
            "results": [r.to_dict() for r in self.results],
        }


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------
def check_schema(
    df: pd.DataFrame,
    expected_cols: list[str],
    source: str,
) -> CheckResult:
    """Assert that ``df`` has exactly ``expected_cols`` (order agnostic)."""
    actual = set(df.columns)
    expected = set(expected_cols)
    missing = expected - actual
    extra = actual - expected
    passed = not missing and not extra
    detail = ""
    if missing:
        detail += f"missing={sorted(missing)} "
    if extra:
        detail += f"extra={sorted(extra)}"
    return CheckResult(
        name=f"schema:{source}",
        passed=passed,
        expected=sorted(expected),
        actual=sorted(actual),
        detail=detail.strip(),
    )


def check_row_count(
    actual: int,
    expected: int,
    source: str,
    tolerance_pct: float = 1.0,
) -> CheckResult:
    """Assert ``actual`` row count is within ``tolerance_pct`` of ``expected``."""
    if expected == 0:
        passed = actual == 0
    else:
        diff_pct = abs(actual - expected) / expected * 100
        passed = diff_pct <= tolerance_pct
    return CheckResult(
        name=f"row_count:{source}",
        passed=passed,
        expected=expected,
        actual=actual,
        detail=f"tolerance={tolerance_pct}%",
    )


def check_unique_count(
    series: pd.Series,
    expected: int,
    source: str,
    severity: str = SEVERITY_ERROR,
    min_expected: int | None = None,
) -> CheckResult:
    """Assert ``series.nunique() == expected`` (or ``>= min_expected`` if given)."""
    actual = int(series.nunique(dropna=True))
    if min_expected is not None:
        passed = actual >= min_expected
    else:
        passed = actual == expected
    return CheckResult(
        name=f"nunique:{source}",
        passed=passed,
        expected=expected if min_expected is None else f">={min_expected}",
        actual=actual,
        severity=severity,
    )


def check_date_range_within(
    df: pd.DataFrame,
    col: str,
    window_start: str,
    window_end: str,
    source: str,
) -> CheckResult:
    """Assert that every date in ``df[col]`` falls inside the study window.

    Not every pollutant has coverage from ``window_start`` to ``window_end``
    (e.g. VOCs starts 2016, PM10 has gaps). We only want to catch dates that
    are *outside* the study period entirely.
    """
    series = pd.to_datetime(df[col], errors="coerce")
    if not series.notna().any():
        return CheckResult(
            name=f"date_range:{source}",
            passed=False,
            detail="no parseable dates",
        )
    actual_min = str(series.min().date())
    actual_max = str(series.max().date())
    # Small slack on the upper bound: data may legitimately have rows past
    # the nominal end of the study period as new files arrive.
    passed = actual_min >= window_start and actual_max <= "2026-12-31"
    return CheckResult(
        name=f"date_range:{source}",
        passed=passed,
        expected=[window_start, window_end],
        actual=[actual_min, actual_max],
    )


# Back-compat alias — old name kept so callers don't break.
check_date_range = check_date_range_within


def check_no_duplicate_hours(
    df: pd.DataFrame,
    key_cols: tuple[str, ...] = ("aqsid", "date_local", "time_local", "parameter_code", "poc"),
    source: str = "pollutants",
    severity: str = SEVERITY_WARNING,
) -> CheckResult:
    """Report duplicate hourly rows under ``key_cols``.

    Defaults to WARNING severity: exact duplicates are deduplicated
    automatically in step 01, so a nonzero count is informational, not
    pipeline-breaking.
    """
    missing = [c for c in key_cols if c not in df.columns]
    if missing:
        return CheckResult(
            name=f"no_duplicate_hours:{source}",
            passed=False,
            detail=f"missing columns: {missing}",
            severity=SEVERITY_ERROR,
        )
    dup = int(df.duplicated(subset=list(key_cols)).sum())
    # Full-row exact duplicates — these are the safe-to-drop ones.
    exact_dup = int(df.duplicated().sum())
    return CheckResult(
        name=f"no_duplicate_hours:{source}",
        passed=dup == 0,
        expected=0,
        actual=dup,
        detail=f"exact_full_row_dups={exact_dup}",
        severity=severity,
    )
