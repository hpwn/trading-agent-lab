import pandas as pd
import types
import tal.backtest.engine as engine
from typer.testing import CliRunner
from tal.cli import app
from tests.conftest import make_price_df


def test_backtest_cli_with_mocked_data(monkeypatch, tmp_path):
    # Mock yfinance.download to avoid network
    def fake_download(symbol, period="max", interval="1d", auto_adjust=True):
        return make_price_df(n=120)

    monkeypatch.setattr(engine, "yf", types.SimpleNamespace(download=fake_download))
    runner = CliRunner()
    result = runner.invoke(app, ["backtest", "--config", "config/base.yaml"])
    assert result.exit_code == 0
    assert "[BACKTEST]" in result.stdout
