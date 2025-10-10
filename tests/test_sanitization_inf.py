import os, json, types
from pathlib import Path
from typer.testing import CliRunner
from tal.cli import app
import tal.backtest.engine as engine
from tests.conftest import make_price_df


def test_profit_factor_infinite_is_sanitized(monkeypatch, tmp_path):
    cfg_in = Path("config/base.yaml").read_text()
    cfg_out = tmp_path / "cfg.yaml"
    cfg_in = cfg_in.replace("sqlite:///./lab.db", f"sqlite:///{tmp_path / 'lab.db'}") \
                   .replace("./artifacts", str(tmp_path / "artifacts"))
    cfg_out.write_text(cfg_in)

    # strictly up-only prices → PF=inf
    def fake_download(symbol, period="max", interval="1d", auto_adjust=True):
        return make_price_df(n=60, up_only=True)
    monkeypatch.setattr(engine, "yf", types.SimpleNamespace(download=fake_download))

    os.environ["RUN_ID"] = "test-run-inf"

    runner = CliRunner()
    res = runner.invoke(app, ["backtest", "--config", str(cfg_out)])
    assert res.exit_code == 0

    # metrics.json should contain null for profit_factor (sanitized)
    metrics_json = next((tmp_path / "artifacts" / "runs").rglob("metrics.json"))
    data = json.loads(metrics_json.read_text())
    assert "profit_factor" in data
    assert data["profit_factor"] is None
