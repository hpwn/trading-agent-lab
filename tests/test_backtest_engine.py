import types
from pathlib import Path

import tal.backtest.engine as engine
from typer.testing import CliRunner

from tal.cli import app
from tests.conftest import make_price_df


def test_backtest_cli_with_mocked_data(monkeypatch, tmp_path):
    # Mock yfinance.download to avoid network
    def fake_download(symbol, period="max", interval="1d", auto_adjust=True):
        return make_price_df(n=120)

    monkeypatch.setattr(engine, "yf", types.SimpleNamespace(download=fake_download))
    # Write to a tmp config so artifacts & DB live under tmp_path
    cfg_in = Path("config/base.yaml").read_text()
    cfg_out = tmp_path / "cfg.yaml"
    cfg_in = (
        cfg_in
        .replace("sqlite:///./lab.db", f"sqlite:///{tmp_path / 'lab.db'}")
        .replace("./artifacts", str(tmp_path / "artifacts"))
    )
    cfg_out.write_text(cfg_in)

    runner = CliRunner()
    result = runner.invoke(app, ["backtest", "--config", str(cfg_out)])
    assert result.exit_code == 0
    assert "[BACKTEST]" in result.stdout
