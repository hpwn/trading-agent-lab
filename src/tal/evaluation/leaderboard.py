"""Leaderboard and evaluation helpers."""

from __future__ import annotations

import json
import numbers
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence, cast

import pandas as pd

from tal.storage.db import fetch_agents, fetch_metrics_for_runs, fetch_runs_since

WINDOW_MAP = {
    "1d": timedelta(days=1),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}


def resolve_window(key: str, now: datetime | None = None) -> tuple[datetime, str]:
    """Return the start datetime and ISO string for the provided window key."""

    if key not in WINDOW_MAP:
        raise ValueError(f"Unsupported window '{key}'. Choose from {', '.join(WINDOW_MAP)}")
    now = now or datetime.now(timezone.utc)
    since_dt = now - WINDOW_MAP[key]
    return since_dt, since_dt.isoformat()


def build_leaderboard(engine: Any, since_iso: str) -> pd.DataFrame:
    """Build a leaderboard DataFrame for runs since the provided ISO timestamp."""

    runs = fetch_runs_since(engine, since_iso)
    if not runs:
        return pd.DataFrame(columns=["agent_id", "runs", "profit_factor", "sharpe", "max_dd", "win_rate"])

    runs_df = pd.DataFrame(runs)
    runs_df["ts_end"] = pd.to_datetime(runs_df["ts_end"], utc=True, errors="coerce")
    runs_df["ts_start"] = pd.to_datetime(runs_df["ts_start"], utc=True, errors="coerce")

    metrics = fetch_metrics_for_runs(engine, runs_df["id"].tolist())
    metrics_df = pd.DataFrame(metrics)
    if not metrics_df.empty:
        metrics_pivot = metrics_df.pivot(index="run_id", columns="name", values="value")
    else:
        metrics_pivot = pd.DataFrame()

    counts = runs_df.groupby("agent_id").size().rename("runs").reset_index()

    runs_df = runs_df.sort_values("ts_end")
    latest = runs_df.groupby("agent_id", as_index=False).tail(1)
    latest = latest.merge(counts, on="agent_id", how="left")
    metric_cols = ["profit_factor", "sharpe", "max_dd", "win_rate"]
    if not metrics_pivot.empty:
        latest = latest.merge(
            metrics_pivot,
            left_on="id",
            right_index=True,
            how="left",
        )
    else:
        for col in metric_cols:
            latest[col] = pd.NA

    leaderboard = latest[["agent_id", "runs", *metric_cols]].copy()
    leaderboard["runs"] = leaderboard["runs"].fillna(0).astype(int)
    leaderboard[metric_cols] = leaderboard[metric_cols].apply(pd.to_numeric, errors="coerce")
    leaderboard = leaderboard.sort_values(
        by=["profit_factor", "sharpe", "max_dd"],
        ascending=[False, False, False],
        na_position="last",
    ).reset_index(drop=True)
    return leaderboard


def _ensure_engine(db: Any) -> Any:
    return getattr(db, "sa", db)


def by_agent(db: Any, since_days: int = 30) -> list[dict[str, Any]]:
    engine = _ensure_engine(db)
    since_dt = datetime.now(timezone.utc) - timedelta(days=since_days)
    df = build_leaderboard(engine, since_dt.isoformat())
    records = cast(list[dict[str, Any]], df.to_dict(orient="records"))
    agents_meta = {row["agent_id"]: row for row in fetch_agents(engine)}
    for row in records:
        meta = agents_meta.get(row["agent_id"])
        if meta:
            row.update({
                "builder_name": meta.get("builder_name"),
                "builder_model": meta.get("builder_model"),
                "prompt_hash": meta.get("prompt_hash"),
                "parent_id": meta.get("parent_id"),
                "version": meta.get("version"),
                "mutation": meta.get("mutation"),
                "notes": meta.get("notes"),
            })
    return records


def _safe_add_metric(container: dict[str, list[float]], key: str, value: Any) -> None:
    if pd.isna(value):
        return
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return
    container.setdefault(key, []).append(numeric)


def by_builder(db: Any, since_days: int = 30) -> list[dict[str, Any]]:
    rows = by_agent(db, since_days=since_days)
    if not rows:
        return []
    groups: dict[str, dict[str, Any]] = {}
    metrics: dict[str, dict[str, list[float]]] = defaultdict(dict)
    for row in rows:
        builder = row.get("builder_name") or "unknown"
        grp = groups.setdefault(
            builder,
            {
                "builder_name": builder,
                "builder_model": row.get("builder_model"),
                "agent_ids": [],
                "runs": 0,
            },
        )
        if grp.get("builder_model") is None and row.get("builder_model"):
            grp["builder_model"] = row.get("builder_model")
        grp["agent_ids"].append(str(row.get("agent_id") or ""))
        grp["runs"] += int(row.get("runs", 0))
        metric_container = metrics.setdefault(builder, {})
        for metric in ("profit_factor", "sharpe", "max_dd", "win_rate"):
            _safe_add_metric(metric_container, metric, row.get(metric))
    results: list[dict[str, Any]] = []
    for builder, info in groups.items():
        metric_container = metrics.get(builder, {})
        for metric, values in metric_container.items():
            if values:
                info[metric] = sum(values) / len(values)
        for metric in ("profit_factor", "sharpe", "max_dd", "win_rate"):
            info.setdefault(metric, None)
        results.append(info)
    results.sort(
        key=lambda r: (
            r.get("profit_factor") if r.get("profit_factor") is not None else float("-inf"),
            r.get("sharpe") if r.get("sharpe") is not None else float("-inf"),
        ),
        reverse=True,
    )
    return results


def summarize(db: Any, since_days: int = 30, group: str = "agent") -> list[dict[str, Any]]:
    group_key = (group or "agent").lower()
    if group_key == "builder":
        return by_builder(db, since_days=since_days)
    return by_agent(db, since_days=since_days)


def print_table(rows: Sequence[Mapping[str, Any]], group: str = "agent") -> str:
    if not rows:
        return "No runs found in the selected window."
    group_key = (group or "agent").lower()
    if group_key == "builder":
        columns = [
            "builder_name",
            "builder_model",
            "runs",
            "profit_factor",
            "sharpe",
            "max_dd",
            "win_rate",
        ]
    else:
        columns = [
            "agent_id",
            "builder_name",
            "runs",
            "profit_factor",
            "sharpe",
            "max_dd",
            "win_rate",
        ]

    def fmt(value: Any) -> str:
        if pd.isna(value):
            return "-"
        if isinstance(value, numbers.Integral):
            return str(int(value))
        if isinstance(value, numbers.Real):
            return f"{value:.4f}"
        if value is None:
            return "-"
        return str(value)

    table_rows: list[list[str]] = []
    for row in rows:
        table_rows.append([fmt(row.get(col)) for col in columns])

    widths = [max(len(col), *(len(r[idx]) for r in table_rows)) for idx, col in enumerate(columns)]
    header = " | ".join(col.ljust(widths[idx]) for idx, col in enumerate(columns))
    separator = "-+-".join("-" * widths[idx] for idx in range(len(columns)))
    body = [" | ".join(r[idx].ljust(widths[idx]) for idx in range(len(columns))) for r in table_rows]
    return "\n".join([header, separator, *body])


def format_table(data: Sequence[Mapping[str, Any]] | pd.DataFrame, group: str = "agent") -> str:
    """Format leaderboard rows as a plain text table."""

    if isinstance(data, pd.DataFrame):
        if data.empty:
            return "No runs found in the selected window."
        records = cast(list[dict[str, Any]], data.to_dict(orient="records"))
    else:
        records = [dict(row) for row in data]
        if not records:
            return "No runs found in the selected window."
    return print_table(records, group=group)


def format_json(data: Sequence[Mapping[str, Any]] | pd.DataFrame) -> str:
    """Format the leaderboard as JSON."""

    if isinstance(data, pd.DataFrame):
        records = cast(list[dict[str, Any]], data.to_dict(orient="records"))
    else:
        records = [dict(row) for row in data]
    return json.dumps(records, indent=2)
