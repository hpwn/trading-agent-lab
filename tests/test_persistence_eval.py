import os, json, types
from pathlib import Path
from typer.testing import CliRunner
from tal.cli import app
import tal.backtest.engine as engine
from tests.conftest import make_price_df


def test_persist_and_eval(monkeypatch, tmp_path):
    # temp artifacts & DB via a copied config
    cfg_in = Path("config/base.yaml").read_text()
    cfg_out = tmp_path / "cfg.yaml"
    cfg_in = cfg_in.replace("sqlite:///./lab.db", f"sqlite:///{tmp_path / 'lab.db'}") \
                   .replace("./artifacts", str(tmp_path / "artifacts"))
    cfg_out.write_text(cfg_in)

    # mock yfinance to be offline/deterministic
    def fake_download(symbol, period="max", interval="1d", auto_adjust=True):
        return make_price_df(n=80)
    monkeypatch.setattr(engine, "yf", types.SimpleNamespace(download=fake_download))

    # fixed RUN_ID for reproducibility
    os.environ["RUN_ID"] = "test-run-001"

    runner = CliRunner()
    # run backtest to write DB + artifacts
    res_bt = runner.invoke(app, ["backtest", "--config", str(cfg_out)])
    assert res_bt.exit_code == 0

    # eval should surface at least one row (agent_id may be absent in v0 -> treat as 'default')
    res_eval = runner.invoke(app, ["eval", "--since", "30d", "--format", "json"])
    assert res_eval.exit_code == 0
    data = json.loads(res_eval.stdout)
    assert isinstance(data, list)
    assert len(data) >= 1
