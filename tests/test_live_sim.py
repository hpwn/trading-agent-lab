from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from tal.cli import app


def test_live_once_sim(tmp_path):
    txt = Path("config/agents/codex_seed.yaml").read_text()
    cfg = tmp_path / "agent.yaml"
    txt = txt.replace("./artifacts", str(tmp_path / "artifacts")).replace(
        "sqlite:///./lab.db", f"sqlite:///{tmp_path / 'lab.db'}"
    )
    cfg.write_text(txt)

    runner = CliRunner()
    result = runner.invoke(app, ["live", "--config", str(cfg)])
    assert result.exit_code == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["symbol"] == "SPY"
    assert (tmp_path / "artifacts/live/trades.csv").exists()
