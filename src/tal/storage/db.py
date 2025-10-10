"""Utilities for persisting Trading Agent Lab runs and metrics."""

from __future__ import annotations

from typing import Iterable, Mapping, Sequence

from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.engine import Engine

INIT_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS runs (
        id TEXT PRIMARY KEY,
        agent_id TEXT,
        mode TEXT,
        ts_start TEXT,
        ts_end TEXT,
        commit_sha TEXT,
        config_hash TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS metrics (
        run_id TEXT,
        name TEXT,
        value REAL,
        PRIMARY KEY (run_id, name),
        FOREIGN KEY (run_id) REFERENCES runs(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS trades (
        run_id TEXT,
        ts TEXT,
        symbol TEXT,
        side TEXT,
        qty REAL,
        price REAL,
        pnl REAL,
        FOREIGN KEY (run_id) REFERENCES runs(id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_runs_agent_ts ON runs(agent_id, ts_start)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_metrics_run ON metrics(run_id)
    """,
)


def get_engine(db_url: str) -> Engine:
    """Create an engine for the configured SQLite database and ensure schema."""

    engine = create_engine(db_url, echo=False, future=True)
    init_db(engine)
    return engine


def init_db(engine: Engine) -> None:
    """Create required tables if they do not exist."""

    with engine.begin() as conn:
        for statement in INIT_STATEMENTS:
            conn.execute(text(statement))


def record_run(
    engine: Engine,
    run_row: Mapping[str, object],
    metrics_rows: Sequence[Mapping[str, object]],
    trades_rows: Iterable[Mapping[str, object]] | None = None,
) -> None:
    """Persist a run along with associated metrics and (future) trades."""

    trades_rows = list(trades_rows or [])
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO runs (
                    id, agent_id, mode, ts_start, ts_end, commit_sha, config_hash
                ) VALUES (
                    :id, :agent_id, :mode, :ts_start, :ts_end, :commit_sha, :config_hash
                )
                """
            ),
            run_row,
        )
        if metrics_rows:
            conn.execute(
                text(
                    """
                    INSERT OR REPLACE INTO metrics (run_id, name, value)
                    VALUES (:run_id, :name, :value)
                    """
                ),
                metrics_rows,
            )
        if trades_rows:
            conn.execute(
                text(
                    """
                    INSERT INTO trades (run_id, ts, symbol, side, qty, price, pnl)
                    VALUES (:run_id, :ts, :symbol, :side, :qty, :price, :pnl)
                    """
                ),
                trades_rows,
            )


def fetch_runs_since(engine: Engine, since_iso: str) -> list[dict[str, object]]:
    """Return runs that started on or after the provided ISO timestamp."""

    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT * FROM runs WHERE ts_start >= :since"),
            {"since": since_iso},
        ).mappings()
        return [dict(row) for row in rows]


def fetch_metrics_for_runs(engine: Engine, run_ids: Sequence[str]) -> list[dict[str, object]]:
    """Return metric rows for the given run IDs."""

    if not run_ids:
        return []

    stmt = (
        text("SELECT run_id, name, value FROM metrics WHERE run_id IN :run_ids")
        .bindparams(bindparam("run_ids", expanding=True))
    )
    with engine.connect() as conn:
        rows = conn.execute(stmt, {"run_ids": tuple(run_ids)}).mappings()
        return [dict(row) for row in rows]
