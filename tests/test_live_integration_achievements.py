from __future__ import annotations

from pathlib import Path

import pandas as pd
from typer.testing import CliRunner

from tal.cli import app


class _StubStrategy:
    def __init__(self, **_: object) -> None:
        pass

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:  # type: ignore[override]
        return pd.Series([1], dtype=int)


class _StubMarketData:
    def __init__(self, *_: object, **__: object) -> None:
        pass

    def history(self, symbol: str, bars: int) -> pd.DataFrame:
        return pd.DataFrame({"Close": [1.01] * max(1, bars)})

    def latest_price(self, symbol: str) -> float:
        return 1.01


def test_live_integration_unlocks(monkeypatch, tmp_path):
    achievements_dir = tmp_path / "achievements"
    monkeypatch.setenv("ACHIEVEMENTS_DIR", str(achievements_dir))
    monkeypatch.setenv("ACHIEVEMENTS_ENABLED", "1")
    monkeypatch.setenv("LIVE_EXECUTE", "0")

    config_text = Path("config/agents/codex_seed.yaml").read_text()
    config_text = config_text.replace("cash: 10000", "cash: 1.05")
    config_text = config_text.replace("size_pct: 10", "size_pct: 100")
    config_text = config_text.replace("commission: 0.0", "commission: 0.0\n  max_position_pct: 100\n  size_pct: 100")
    config_text = config_text.replace(
        "./artifacts", str(tmp_path / "artifacts")
    ).replace("sqlite:///./lab.db", f"sqlite:///{tmp_path / 'lab.db'}")
    cfg_path = tmp_path / "agent.yaml"
    cfg_path.write_text(config_text)

    monkeypatch.setattr("tal.live.wrapper.SimMarketData", _StubMarketData)
    monkeypatch.setattr("tal.live.wrapper._load_strategy", lambda *_: _StubStrategy)

    runner = CliRunner()
    result = runner.invoke(app, ["live", "--config", str(cfg_path)])
    assert result.exit_code == 0, result.output
    assert "[achievements] unlocked" in result.stdout
