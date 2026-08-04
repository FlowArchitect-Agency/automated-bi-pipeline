"""SQLAlchemy engine helpers for the warehouse.

Keeps engine creation in one place so the whole stack shares connection
pooling and echo settings. The schema bootstrap applies `sql/01_schema.sql`.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from .config import get_settings


def make_engine(dsn: str | None = None, *, echo: bool = False) -> Engine:
    """Build a SQLAlchemy engine for the warehouse."""
    cfg = dsn or get_settings().warehouse_dsn
    return create_engine(
        cfg,
        echo=echo,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        future=True,
    )


@contextmanager
def session_scope(engine: Engine) -> Iterator[object]:
    """Transaction context: commit on success, rollback on error."""
    conn = engine.connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def wait_for_db(engine: Engine, *, timeout: float = 60.0) -> None:
    """Block until the DB accepts a connection (used at DAG start)."""
    import time

    deadline = time.time() + timeout
    last_err: Exception | None = None
    while time.time() < deadline:
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except Exception as exc:  # pragma: no cover - depends on env
            last_err = exc
            time.sleep(2)
    raise ConnectionError(f"Database not reachable within {timeout}s: {last_err}")


def bootstrap_schema(engine: Engine) -> None:
    """Apply sql/01_schema.sql (idempotent). Run once before the first load.

    Uses the raw DBAPI connection (psycopg2) because the script contains a
    ``DO $$ ... $$`` plpgsql block and multiple statements, which SQLAlchemy's
    ``text()`` is not designed to parse.
    """
    from .config import ROOT

    sql_path = ROOT / "sql" / "01_schema.sql"
    raw = sql_path.read_text(encoding="utf-8")

    # The schema SQL uses a psql-style variable :reader_password; substitute it
    # with the configured reader password before executing.
    settings = get_settings()
    reader_pw = settings.warehouse_reader_password.get_secret_value().replace("'", "''")
    raw = raw.replace(":reader_password", f"'{reader_pw}'")

    with engine.begin() as conn:
        # exec_driver_sql sends the raw string straight to psycopg2, which
        # correctly parses dollar-quoting and multi-statement scripts.
        conn.exec_driver_sql(raw)
