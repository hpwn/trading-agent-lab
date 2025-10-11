"""Optional Alpaca adapter skeletons."""

from __future__ import annotations

try:
    from alpaca.trading.client import TradingClient  # type: ignore
    from alpaca.data.historical import StockHistoricalDataClient  # type: ignore
except Exception:  # pragma: no cover - missing extra or runtime not configured
    TradingClient = None
    StockHistoricalDataClient = None

# Placeholder classes that would mirror Broker/MarketData in a future PR.
# Do not instantiate in tests; raise a clear error if used without the extra.


def _require_alpaca() -> None:
    if TradingClient is None or StockHistoricalDataClient is None:
        raise RuntimeError(
            "alpaca extra not installed. Install with `pip install -e '.[alpaca]'`"
        )


class AlpacaBroker:  # pragma: no cover - placeholder
    def __init__(self, *args, **kwargs):
        _require_alpaca()
        raise NotImplementedError("AlpacaBroker will be implemented in a future update")


class AlpacaMarketData:  # pragma: no cover - placeholder
    def __init__(self, *args, **kwargs):
        _require_alpaca()
        raise NotImplementedError("AlpacaMarketData will be implemented in a future update")
