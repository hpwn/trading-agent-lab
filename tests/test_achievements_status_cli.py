from __future__ import annotations

from typer.testing import CliRunner

from tal.achievements import (
    record_profit_dollars,
    record_trade_notional,
    reset_achievements,
)
from tal.cli import app


def test_achievements_status_cli(monkeypatch, tmp_path):
    achievements_dir = tmp_path / "achievements"
    monkeypatch.setenv("ACHIEVEMENTS_DIR", str(achievements_dir))
    monkeypatch.setenv("ACHIEVEMENTS_ENABLED", "1")
    monkeypatch.setenv("ACHIEVEMENTS_PROFIT_SOURCE", "eval")
    reset_achievements()

    record_trade_notional(2.0, "paper")
    record_profit_dollars(2.5, "paper")

    runner = CliRunner()
    result = runner.invoke(app, ["achievements", "status"])

    assert result.exit_code == 0
    output = result.stdout.strip().splitlines()
    assert any("paper_first_$1_trade" in line for line in output)
    assert any("paper_first_$1_profit" in line for line in output)
    assert any("notional [live]" in line for line in output)
    assert any("profit [eval]" in line for line in output)
    assert any("paper -> $10" in line for line in output)
    assert any("real -> $1" in line for line in output)
