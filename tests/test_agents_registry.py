import json
import types
from pathlib import Path

from typer.testing import CliRunner

import tal.backtest.engine as engine
from tal.agents.registry import load_agent_config, to_engine_config
from tal.cli import app
from tests.conftest import make_price_df


def test_spec_load_and_translate(tmp_path):
    spec = load_agent_config("config/agents/codex_seed.yaml")
    assert spec.id == "codex_seed"
    eng = to_engine_config(spec)
    assert eng["agent_id"] == "codex_seed"
    assert eng["strategy"]["name"] == "rsi_mean_rev"


def test_agent_backtests_with_two_configs(monkeypatch, tmp_path):
    def fake_download(symbol, period="max", interval="1d", auto_adjust=True):
        return make_price_df(n=120)

    monkeypatch.setattr(engine, "yf", types.SimpleNamespace(download=fake_download))

    def rewrite(path_str: str) -> str:
        original = Path(path_str)
        txt = original.read_text()
        out = tmp_path / original.name
        txt = txt.replace("sqlite:///./lab.db", f"sqlite:///{tmp_path/'lab.db'}")
        txt = txt.replace("./artifacts", str(tmp_path / "artifacts"))
        out.write_text(txt)
        return str(out)

    c1 = rewrite("config/agents/codex_seed.yaml")
    c2 = rewrite("config/agents/rsi_v2.yaml")

    runner = CliRunner()
    result = runner.invoke(app, ["agent", "backtest", "--config", c1])
    assert result.exit_code == 0
    result = runner.invoke(app, ["agent", "backtest", "--config", c2])
    assert result.exit_code == 0

    result = runner.invoke(app, ["eval", "--since", "30d", "--format", "json"])
    assert result.exit_code == 0
    rows = json.loads(result.stdout)
    ids = {row.get("agent_id", "default") for row in rows}
    assert {"codex_seed", "rsi_v2"}.issubset(ids)
