from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tal.evaluation.leaderboard import (
    build_leaderboard,
    format_json,
    format_table,
    summarize,
)
from tal.storage.db import get_engine, record_run


def test_leaderboard_single_run(tmp_path):
    db_path = tmp_path / "lab.db"
    engine = get_engine(f"sqlite:///{db_path}")

    now = datetime.now(timezone.utc)
    run_id = "run-1"
    record_run(
        engine,
        {
            "id": run_id,
            "agent_id": "agent-1",
            "mode": "backtest",
            "ts_start": (now - timedelta(minutes=5)).isoformat(),
            "ts_end": now.isoformat(),
            "commit_sha": "deadbeef",
            "config_hash": "hash",
        },
        [
            {"run_id": run_id, "name": "pnl", "value": 0.05},
            {"run_id": run_id, "name": "profit_factor", "value": 1.8},
            {"run_id": run_id, "name": "sharpe", "value": 1.2},
            {"run_id": run_id, "name": "max_dd", "value": 0.1},
            {"run_id": run_id, "name": "win_rate", "value": 0.6},
        ],
    )

    since_iso = (now - timedelta(days=1)).isoformat()
    leaderboard = build_leaderboard(engine, since_iso)
    assert not leaderboard.empty
    row = leaderboard.iloc[0]
    assert row["agent_id"] == "agent-1"
    assert row["runs"] == 1
    assert row["profit_factor"] == 1.8

    table_output = format_table(leaderboard)
    assert "agent-1" in table_output

    json_output = format_json(leaderboard)
    assert "profit_factor" in json_output

    summary_rows = summarize(engine, since_days=1)
    assert summary_rows and summary_rows[0]["agent_id"] == "agent-1"

    builder_rows = summarize(engine, since_days=1, group="builder")
    assert builder_rows and builder_rows[0]["runs"] == 1
    builder_table = format_table(builder_rows, group="builder")
    assert "builder" in builder_table.lower()
