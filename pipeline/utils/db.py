"""Postgres connection helpers for the pipeline loader.

Credentials live **only** in the ``AQ_POSTGRES_URL`` environment variable —
never in config.yaml, never on disk in the project tree. If the env var is
missing, ``get_engine()`` returns ``None`` and the loader step gracefully
skips itself.

Target databases tested: Neon, Supabase, local Postgres 14+, AWS RDS.
Uses psycopg (v3) under the hood via SQLAlchemy 2.x.
"""

from __future__ import annotations

import logging
import os
from typing import Iterable

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError


ENV_VAR = "AQ_POSTGRES_URL"


def _normalize_url(url: str) -> str:
    """Force the psycopg (v3) driver and ensure sslmode=require."""
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://") and "+psycopg" not in url:
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    if "sslmode=" not in url:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}sslmode=require"
    return url


def get_engine(log: logging.Logger | None = None) -> Engine | None:
    """Return a SQLAlchemy Engine, or None if ``AQ_POSTGRES_URL`` is unset.

    The engine uses ``pool_pre_ping=True`` so Neon's auto-pause doesn't
    produce stale connections.
    """
    url = os.environ.get(ENV_VAR)
    if not url:
        if log:
            log.warning(
                f"{ENV_VAR} not set — Postgres loader will be skipped. "
                "Set it with: "
                f'[Environment]::SetEnvironmentVariable("{ENV_VAR}", "postgresql://...", "User")'
            )
        return None
    engine = create_engine(
        _normalize_url(url),
        pool_pre_ping=True,
        future=True,
    )
    return engine


def ping(engine: Engine) -> str:
    """Run ``SELECT version()`` and return the version string. Raises on failure."""
    with engine.connect() as conn:
        row = conn.execute(text("SELECT version()")).scalar_one()
    return str(row)


def ensure_schema(engine: Engine, schema: str) -> None:
    """Create ``schema`` if it doesn't already exist."""
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))


def create_indexes(
    engine: Engine,
    schema: str,
    table: str,
    columns: Iterable[str],
) -> list[str]:
    """Create a BTREE index per column if it doesn't exist. Returns names created."""
    created: list[str] = []
    with engine.begin() as conn:
        for col in columns:
            name = f"ix_{table}_{col}"
            stmt = (
                f'CREATE INDEX IF NOT EXISTS "{name}" '
                f'ON "{schema}"."{table}" ("{col}")'
            )
            conn.execute(text(stmt))
            created.append(name)
    return created


def is_quota_error(err: Exception) -> bool:
    """Heuristic: does this error look like a free-tier storage quota hit?"""
    msg = str(err).lower()
    needles = (
        "quota", "storage limit", "disk full",
        "out of memory", "no space left",
        "compute time", "project is suspended",
    )
    return any(n in msg for n in needles)
