from __future__ import annotations

import json

from typer.testing import CliRunner

from tal.achievements import record_trade_notional, reset_achievements
from tal.cli import app


def test_achievements_cli(monkeypatch, tmp_path):
    achievements_dir = tmp_path / "achievements"
    monkeypatch.setenv("ACHIEVEMENTS_DIR", str(achievements_dir))
    monkeypatch.setenv("ACHIEVEMENTS_ENABLED", "1")
    reset_achievements()

    record_trade_notional(1.5, "paper")

    runner = CliRunner()
    result = runner.invoke(app, ["achievements", "ls"])
    assert result.exit_code == 0
    entries = json.loads(result.stdout)
    assert any(entry.get("key") == "paper_first_$1_trade" for entry in entries)

    reset_result = runner.invoke(app, ["achievements", "reset", "--yes"])
    assert reset_result.exit_code == 0

    result_after_reset = runner.invoke(app, ["achievements", "ls"])
    assert result_after_reset.exit_code == 0
    assert json.loads(result_after_reset.stdout) == []
