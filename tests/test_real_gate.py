from __future__ import annotations

import textwrap
import types
import sys

from typer.testing import CliRunner

from tal.cli import app


def _install_alpaca_stubs(monkeypatch) -> None:
    pkg_common = types.ModuleType("alpaca.common.exceptions")

    class _APIError(Exception):
        pass

    pkg_common.APIError = _APIError

    pkg_trading_client = types.ModuleType("alpaca.trading.client")

    class _FakeTradingClient:
        def __init__(self, *_, **__):
            self._positions: dict[str, float] = {}

        def get_clock(self):
            return types.SimpleNamespace(is_open=True)

        def get_account(self):
            return {
                "cash": 1000.0,
                "equity": 1000.0,
                "buying_power": 1000.0,
                "last_equity": 1000.0,
            }

        def get_open_position(self, symbol: str):
            if symbol in self._positions:
                return types.SimpleNamespace(qty=self._positions[symbol])
            raise _APIError("position not found")

        def submit_order(self, symbol: str, side: str, qty: float, **_):
            sign = 1.0 if side.lower() == "buy" else -1.0
            self._positions[symbol] = self._positions.get(symbol, 0.0) + sign * float(qty)
            return types.SimpleNamespace(id="stub-order", status="filled")

    pkg_trading_client.TradingClient = _FakeTradingClient

    pkg_data_hist = types.ModuleType("alpaca.data.historical")

    class _FakeHistoricalClient:
        def __init__(self, *_, **__):
            pass

        def get_stock_latest_trade(self, request):
            symbol = getattr(request, "symbol_or_symbols", "SPY")
            return {symbol: types.SimpleNamespace(price=100.0)}

    pkg_data_hist.StockHistoricalDataClient = _FakeHistoricalClient

    pkg_data_requests = types.ModuleType("alpaca.data.requests")

    class _FakeTradeRequest:
        def __init__(self, symbol_or_symbols):
            self.symbol_or_symbols = symbol_or_symbols

    pkg_data_requests.StockLatestTradeRequest = _FakeTradeRequest

    pkg_trading_enums = types.ModuleType("alpaca.trading.enums")
    pkg_trading_enums.OrderSide = types.SimpleNamespace(BUY="buy", SELL="sell")
    pkg_trading_enums.TimeInForce = types.SimpleNamespace(DAY="day")

    pkg_trading_requests = types.ModuleType("alpaca.trading.requests")

    class _FakeMarketOrderRequest:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    pkg_trading_requests.MarketOrderRequest = _FakeMarketOrderRequest
    pkg_trading_requests.LimitOrderRequest = _FakeMarketOrderRequest

    modules = {
        "alpaca.common.exceptions": pkg_common,
        "alpaca.trading.client": pkg_trading_client,
        "alpaca.data.historical": pkg_data_hist,
        "alpaca.data.requests": pkg_data_requests,
        "alpaca.trading.enums": pkg_trading_enums,
        "alpaca.trading.requests": pkg_trading_requests,
    }

    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)


class _StubAlpacaClient:
    def __init__(self) -> None:
        self._positions: dict[str, float] = {}

    def get_last_price(self, symbol: str) -> float:
        return 100.0

    def is_market_open(self) -> bool:
        return True

    def get_account(self) -> dict:
        return {
            "cash": 1000.0,
            "equity": 1000.0,
            "buying_power": 1000.0,
            "last_equity": 1000.0,
        }

    def get_position(self, symbol: str) -> float:
        return self._positions.get(symbol, 0.0)

    def submit_order(self, symbol: str, side: str, qty: float, type: str) -> dict:
        sign = 1.0 if side.lower() == "buy" else -1.0
        self._positions[symbol] = self._positions.get(symbol, 0.0) + sign * float(qty)
        return {"id": "stub-order", "status": "filled"}


def _write_live_config(tmp_path, *, paper: bool) -> str:
    cfg_text = textwrap.dedent(
        f"""
        live:
          adapter: "alpaca"
          paper: {'true' if paper else 'false'}
          symbol: "SPY"
          size_pct: 5
        universe:
          symbols: ["SPY"]
        strategy:
          name: "rsi_mean_rev"
          params:
            rsi_len: 14
            oversold: 30
            overbought: 70
            size_pct: 5
        storage:
          db_url: "sqlite:///./lab.db"
        """
    ).strip()
    path = tmp_path / ("live_paper.yaml" if paper else "live_real.yaml")
    path.write_text(cfg_text)
    return str(path)


def test_real_broker_fails_without_unlock(monkeypatch, tmp_path):
    config_path = _write_live_config(tmp_path, paper=False)
    monkeypatch.setenv("LIVE_BROKER", "alpaca_real")
    monkeypatch.delenv("REAL_TRADING_ENABLED", raising=False)

    import tal.live.wrapper as wrapper

    monkeypatch.setattr(
        wrapper,
        "_build_alpaca_client_from_env",
        lambda **_: types.SimpleNamespace(),
    )

    runner = CliRunner()
    result = runner.invoke(app, ["live", "--config", config_path])
    assert result.exit_code != 0
    assert isinstance(result.exception, RuntimeError)
    assert "Real trading is locked" in str(result.exception)


def test_doctor_shows_gate(monkeypatch):
    _install_alpaca_stubs(monkeypatch)
    monkeypatch.setenv("ALPACA_API_KEY_ID", "key")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "secret")
    monkeypatch.setenv("LIVE_BROKER", "alpaca_real")
    monkeypatch.delenv("REAL_TRADING_ENABLED", raising=False)

    monkeypatch.setattr(
        "tal.cli._build_alpaca_client_from_env",
        lambda **_: _StubAlpacaClient(),
    )
    monkeypatch.setattr(
        "tal.live.wrapper._build_alpaca_client_from_env",
        lambda **_: _StubAlpacaClient(),
    )

    runner = CliRunner()
    result = runner.invoke(app, ["doctor", "alpaca", "--symbol", "SPY"])
    assert result.exit_code == 0, f"{result.stdout}\n{result.stderr}\n{result.exception}"
    assert "real_trading_enabled: False" in result.stdout
    assert "live_broker: alpaca_real" in result.stdout
    assert "WARNING: real broker selected" in result.stdout


def test_real_broker_allows_with_unlock(monkeypatch, tmp_path):
    _install_alpaca_stubs(monkeypatch)
    config_path = _write_live_config(tmp_path, paper=False)
    monkeypatch.setenv("ALPACA_API_KEY_ID", "key")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "secret")
    monkeypatch.setenv("LIVE_BROKER", "alpaca_real")
    monkeypatch.setenv("REAL_TRADING_ENABLED", "true")

    import tal.live.wrapper as wrapper

    monkeypatch.setattr(
        wrapper,
        "_build_alpaca_client_from_env",
        lambda **_: _StubAlpacaClient(),
    )
    monkeypatch.setattr(
        "tal.cli._build_alpaca_client_from_env",
        lambda **_: _StubAlpacaClient(),
    )

    runner = CliRunner()
    doctor = runner.invoke(app, ["doctor", "alpaca", "--symbol", "SPY", "--live"])
    assert doctor.exit_code == 0, f"{doctor.stdout}\n{doctor.stderr}\n{doctor.exception}"
    assert "real_trading_enabled: True" in doctor.stdout

    live = runner.invoke(app, ["live", "--config", config_path])
    assert live.exit_code == 0, f"{live.stdout}\n{live.stderr}\n{live.exception}"
