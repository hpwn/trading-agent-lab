"""Utilities for persisting Trading Agent Lab runs and metrics."""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional, Sequence, cast

from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.engine import Engine as SAEngine

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
    CREATE TABLE IF NOT EXISTS agents (
        agent_id TEXT PRIMARY KEY,
        builder_name TEXT,
        builder_model TEXT,
        prompt_hash TEXT,
        parent_id TEXT,
        version INTEGER,
        mutation TEXT,
        notes TEXT
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


class Engine:
    """Lightweight convenience wrapper around SQLAlchemy engine."""

    def __init__(self, db_url: str):
        self.db_url = db_url
        self._engine = get_engine(db_url)

    @property
    def sa(self) -> SAEngine:
        return self._engine

    def query(self, sql: str, params: Mapping[str, object] | None = None):
        with self._engine.connect() as conn:
            result = conn.execute(text(sql), params or {})
            return result.fetchall()

    def query_dicts(self, sql: str, params: Mapping[str, object] | None = None) -> list[dict]:
        with self._engine.connect() as conn:
            rows = conn.execute(text(sql), params or {}).mappings()
            return [dict(row) for row in rows]


def get_engine(db_url: str) -> SAEngine:
    """Create an engine for the configured SQLite database and ensure schema."""

    engine = create_engine(db_url, echo=False, future=True)
    init_db(engine)
    return engine


def init_db(engine: SAEngine) -> None:
    """Create required tables if they do not exist."""

    with engine.begin() as conn:
        for statement in INIT_STATEMENTS:
            conn.execute(text(statement))


def upsert_agent(engine: SAEngine, agent: Mapping[str, Any]) -> None:
    agent_id = str(agent.get("id") or agent.get("agent_id") or "")
    meta_obj = agent.get("metadata")
    meta: Mapping[str, Any] = cast(Mapping[str, Any], meta_obj) if isinstance(meta_obj, Mapping) else {}
    builder_obj = meta.get("builder") if meta else None
    builder: Mapping[str, Any] = cast(Mapping[str, Any], builder_obj) if isinstance(builder_obj, Mapping) else {}
    lineage_obj = meta.get("lineage") if meta else None
    lineage: Mapping[str, Any] = cast(Mapping[str, Any], lineage_obj) if isinstance(lineage_obj, Mapping) else {}
    if not agent_id:
        return
    row = {
        "agent_id": agent_id,
        "builder_name": builder.get("name") or agent.get("builder_name"),
        "builder_model": builder.get("model") or agent.get("builder_model"),
        "prompt_hash": builder.get("prompt_hash") or agent.get("prompt_hash"),
        "parent_id": lineage.get("parent_id") or agent.get("parent_id"),
        "version": lineage.get("version") or agent.get("version"),
        "mutation": lineage.get("mutation") or agent.get("mutation"),
        "notes": lineage.get("notes") or agent.get("notes"),
    }
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT OR REPLACE INTO agents (
                    agent_id, builder_name, builder_model, prompt_hash,
                    parent_id, version, mutation, notes
                ) VALUES (
                    :agent_id, :builder_name, :builder_model, :prompt_hash,
                    :parent_id, :version, :mutation, :notes
                )
                """
            ),
            row,
        )


def fetch_agents(engine: SAEngine) -> list[dict[str, object]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT agent_id, builder_name, builder_model, prompt_hash,
                       parent_id, version, mutation, notes
                FROM agents
                """
            )
        ).mappings()
        return [dict(row) for row in rows]


def record_run(
    engine: SAEngine,
    run_row: Mapping[str, Any],
    metrics_rows: Sequence[Mapping[str, Any]],
    trades_rows: Optional[Iterable[Mapping[str, Any]]] = None,
    engine_cfg: Optional[Mapping[str, Any]] = None,
) -> None:
    """Persist a run along with associated metrics and (future) trades."""

    trades_rows = list(trades_rows or [])
    agent_info: Mapping[str, Any] | None = None
    if engine_cfg:
        agent_obj = engine_cfg.get("agent")  # type: Any
        if isinstance(agent_obj, Mapping):
            agent_data = dict(agent_obj)
            if not agent_data.get("id") and run_row.get("agent_id"):
                agent_data["id"] = run_row.get("agent_id")
            agent_info = agent_data
    if agent_info:
        upsert_agent(engine, agent_info)
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


def fetch_runs_since(engine: SAEngine, since_iso: str) -> list[dict[str, object]]:
    """Return runs that started on or after the provided ISO timestamp."""

    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT * FROM runs WHERE ts_start >= :since"),
            {"since": since_iso},
        ).mappings()
        return [dict(row) for row in rows]


def fetch_metrics_for_runs(engine: SAEngine, run_ids: Sequence[str]) -> list[dict[str, object]]:
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
