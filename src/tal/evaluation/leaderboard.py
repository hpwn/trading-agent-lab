"""Leaderboard and evaluation helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import numbers

import pandas as pd

from tal.storage.db import fetch_metrics_for_runs, fetch_runs_since

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


def build_leaderboard(engine, since_iso: str) -> pd.DataFrame:
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
        ascending=[False, False, True],
        na_position="last",
    ).reset_index(drop=True)
    return leaderboard


def format_table(df: pd.DataFrame) -> str:
    """Format the leaderboard DataFrame as a plain text table."""

    if df.empty:
        return "No runs found in the selected window."

    display = df.copy()

    def fmt(value):
        if pd.isna(value):
            return "-"
        if isinstance(value, numbers.Integral):
            return str(value)
        if isinstance(value, numbers.Real):
            return f"{value:.4f}"
        return str(value)

    columns = ["agent_id", "runs", "profit_factor", "sharpe", "max_dd", "win_rate"]
    rows: list[list[str]] = []
    for _, row in display.iterrows():
        formatted = [
            str(row["agent_id"]),
            str(int(row["runs"])),
            fmt(row.get("profit_factor")),
            fmt(row.get("sharpe")),
            fmt(row.get("max_dd")),
            fmt(row.get("win_rate")),
        ]
        rows.append(formatted)

    all_rows: list[list[str]] = [columns] + rows
    widths = [max(len(str(r[i])) for r in all_rows) for i in range(len(columns))]
    header = " | ".join(str(columns[i]).ljust(widths[i]) for i in range(len(columns)))
    separator = "-+-".join("-" * widths[i] for i in range(len(columns)))
    body_lines = [
        " | ".join(row[i].ljust(widths[i]) for i in range(len(columns))) for row in rows
    ]
    return "\n".join([header, separator, *body_lines])


def format_json(df: pd.DataFrame) -> str:
    """Format the leaderboard as JSON."""

    records = df.to_dict(orient="records")
    return json.dumps(records, indent=2)
