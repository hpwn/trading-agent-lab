import sys
import types

from tal.live.wrapper import _build_alpaca_client_from_env


def test_alpaca_clients_use_correct_urls(monkeypatch):
    calls = {"trading_kwargs": None, "data_args": None, "data_kwargs": None}

    class FakeTradingClient:
        def __init__(self, *args, **kwargs):
            calls["trading_kwargs"] = kwargs

    class FakeStockHistoricalDataClient:
        def __init__(self, *args, **kwargs):
            calls["data_args"] = args
            calls["data_kwargs"] = kwargs

    pkg_common = types.ModuleType("alpaca.common.exceptions")
    pkg_common.APIError = RuntimeError
    pkg_trading_client = types.ModuleType("alpaca.trading.client")
    pkg_trading_client.TradingClient = FakeTradingClient
    pkg_data_hist = types.ModuleType("alpaca.data.historical")
    pkg_data_hist.StockHistoricalDataClient = FakeStockHistoricalDataClient
    pkg_data_req = types.ModuleType("alpaca.data.requests")
    pkg_data_req.StockLatestTradeRequest = object
    pkg_trading_enums = types.ModuleType("alpaca.trading.enums")
    pkg_trading_enums.OrderSide = object
    pkg_trading_enums.TimeInForce = object
    pkg_trading_req = types.ModuleType("alpaca.trading.requests")
    pkg_trading_req.MarketOrderRequest = object

    monkeypatch.setitem(sys.modules, "alpaca.common.exceptions", pkg_common)
    monkeypatch.setitem(sys.modules, "alpaca.trading.client", pkg_trading_client)
    monkeypatch.setitem(sys.modules, "alpaca.data.historical", pkg_data_hist)
    monkeypatch.setitem(sys.modules, "alpaca.data.requests", pkg_data_req)
    monkeypatch.setitem(sys.modules, "alpaca.trading.enums", pkg_trading_enums)
    monkeypatch.setitem(sys.modules, "alpaca.trading.requests", pkg_trading_req)

    monkeypatch.setenv("ALPACA_API_KEY_ID", "key")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "secret")

    _build_alpaca_client_from_env(
        paper=True,
        base_url="https://paper-api.alpaca.markets",
    )

    assert calls["trading_kwargs"]["paper"] is True
    assert calls["trading_kwargs"]["url_override"] == "https://paper-api.alpaca.markets"
    assert "base_url" not in calls["trading_kwargs"]

    assert calls["data_args"] == ("key", "secret")
    assert calls["data_kwargs"] == {}


def test_alpaca_data_override_respected(monkeypatch):
    calls = {"data_kwargs": None}

    class FakeTradingClient:
        def __init__(self, *_, **__):
            pass

    class FakeStockHistoricalDataClient:
        def __init__(self, *_, **kwargs):
            calls["data_kwargs"] = kwargs

    modules = {
        "alpaca.common.exceptions": types.ModuleType("alpaca.common.exceptions"),
        "alpaca.trading.client": types.ModuleType("alpaca.trading.client"),
        "alpaca.data.historical": types.ModuleType("alpaca.data.historical"),
        "alpaca.data.requests": types.ModuleType("alpaca.data.requests"),
        "alpaca.trading.enums": types.ModuleType("alpaca.trading.enums"),
        "alpaca.trading.requests": types.ModuleType("alpaca.trading.requests"),
    }

    modules["alpaca.common.exceptions"].APIError = RuntimeError
    modules["alpaca.trading.client"].TradingClient = FakeTradingClient
    modules["alpaca.data.historical"].StockHistoricalDataClient = (
        FakeStockHistoricalDataClient
    )
    modules["alpaca.data.requests"].StockLatestTradeRequest = object
    modules["alpaca.trading.enums"].OrderSide = object
    modules["alpaca.trading.enums"].TimeInForce = object
    modules["alpaca.trading.requests"].MarketOrderRequest = object

    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)

    monkeypatch.setenv("ALPACA_API_KEY_ID", "key")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "secret")
    monkeypatch.setenv("ALPACA_DATA_URL", "https://data.sandbox")

    _build_alpaca_client_from_env(
        paper=True,
        base_url=None,
    )

    assert calls["data_kwargs"] == {"base_url": "https://data.sandbox"}
