from __future__ import annotations

import sqlite3
from pathlib import Path

import yaml
from typer.testing import CliRunner

from tal import achievements
from tal.cli import app


def _write_agent_config(tmp_path: Path, *, slippage_bps: float = 1.0) -> Path:
    base_cfg = yaml.safe_load(Path("config/agents/codex_seed.yaml").read_text())
    live_cfg = base_cfg.setdefault("live", {})
    ledger_dir = tmp_path / "artifacts" / "live"
    live_cfg["ledger_dir"] = str(ledger_dir)
    live_cfg["slippage_bps"] = slippage_bps
    storage_cfg = base_cfg.setdefault("storage", {})
    storage_cfg["db_url"] = f"sqlite:///{tmp_path / 'lab.db'}"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(base_cfg))
    return config_path


def _read_orders_balance(db_path: Path) -> float:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "select coalesce(sum(case when side='buy' then qty else -qty end), 0) from orders"
        ).fetchone()
        return float(row[0] if row and row[0] is not None else 0.0)
    finally:
        conn.close()


def test_live_loop_flatten_cli(monkeypatch, tmp_path):
    config_path = _write_agent_config(tmp_path)
    achievements_dir = tmp_path / "achievements"
    runner = CliRunner()
    env = {
        "ACHIEVEMENTS_DIR": str(achievements_dir),
        "ACHIEVEMENTS_ENABLED": "1",
    }

    result = runner.invoke(
        app,
        [
            "live",
            "--config",
            str(config_path),
            "--loop",
            "--max-steps",
            "3",
            "--interval",
            "0",
            "--flat-at-end",
        ],
        env=env,
    )
    assert result.exit_code == 0, result.stdout

    trades_path = tmp_path / "artifacts" / "live" / "trades.csv"
    lines = [line for line in trades_path.read_text().strip().splitlines() if line]
    assert lines, "expected trades to be recorded"
    assert lines[-1].split(",")[2] == "sell"

    balance = _read_orders_balance(tmp_path / "lab.db")
    assert abs(balance) < 1e-6


def test_live_close_unlocks_profit(monkeypatch, tmp_path):
    config_path = _write_agent_config(tmp_path, slippage_bps=-50.0)
    achievements_dir = tmp_path / "achievements"
    monkeypatch.setenv("ACHIEVEMENTS_DIR", str(achievements_dir))
    monkeypatch.setenv("ACHIEVEMENTS_ENABLED", "1")
    monkeypatch.setenv("ACHIEVEMENTS_PROFIT_SOURCE", "live")
    achievements.reset_achievements()

    runner = CliRunner()
    env = {
        "ACHIEVEMENTS_DIR": str(achievements_dir),
        "ACHIEVEMENTS_ENABLED": "1",
        "ACHIEVEMENTS_PROFIT_SOURCE": "live",
    }

    open_result = runner.invoke(
        app,
        [
            "live",
            "--config",
            str(config_path),
            "--loop",
            "--max-steps",
            "1",
            "--interval",
            "0",
            "--no-flat-at-end",
        ],
        env=env,
    )
    assert open_result.exit_code == 0, open_result.stdout

    close_result = runner.invoke(
        app,
        ["live", "close", "--config", str(config_path)],
        env=env,
    )
    assert close_result.exit_code == 0, close_result.stdout

    state = achievements.list_achievements()
    achievements_map = state.get("achievements", {})
    assert any(key.endswith("_first_$1_profit") for key in achievements_map)
