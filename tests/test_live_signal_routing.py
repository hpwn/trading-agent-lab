from __future__ import annotations

from pathlib import Path

import numpy as np
from typer.testing import CliRunner

from tal.agents.registry import load_agent_config, to_engine_config
from tal.cli import app
from tal.live.wrapper import run_live_once


def _mk_series_triggers_long(n: int = 300):
    down = np.linspace(100.0, 90.0, n // 2)
    up = np.linspace(90.0, 101.0, n - len(down))
    return np.concatenate([down, up])


def test_live_routes_signal_and_sizes(tmp_path):
    cfg_src = Path("config/agents/codex_seed.yaml").read_text()
    artifacts_dir = tmp_path / "artifacts"
    db_path = tmp_path / "lab.db"
    cfg_txt = (
        cfg_src.replace("./artifacts", str(artifacts_dir))
        .replace("sqlite:///./lab.db", f"sqlite:///{db_path}")
    )
    cfg = tmp_path / "agent.yaml"
    cfg.write_text(cfg_txt)

    runner = CliRunner()
    result = runner.invoke(app, ["live", "--config", str(cfg)])
    assert result.exit_code == 0

    spec = load_agent_config(str(cfg))
    engine_cfg = to_engine_config(spec)
    prices = _mk_series_triggers_long(300).tolist()
    res = run_live_once(engine_cfg, {"SPY": prices})

    assert res["signal"] == 1
    assert res["target_qty"] > 0
    assert res["delta"] > 0
    trades_path = artifacts_dir / "live" / "trades.csv"
    assert trades_path.exists()
