from __future__ import annotations

from typing import Any, Optional, Protocol

from ..base import Broker


class AlpacaClient(Protocol):
    def get_last_price(self, symbol: str) -> float: ...

    def is_market_open(self) -> bool: ...

    def submit_order(
        self,
        *,
        symbol: str,
        side: str,
        qty: float,
        type: str = "market",
        time_in_force: str = "day",
        extended_hours: Optional[bool] = None,
    ) -> Any: ...

    def get_account(self) -> dict: ...

    def get_position(self, symbol: str) -> float: ...


from .alpaca import AlpacaBroker  # noqa: E402
from .sim import SimBroker, SimMarketData  # noqa: E402


def build_broker(
    adapter: str,
    *,
    client: AlpacaClient | None = None,
    **kwargs: Any,
) -> Broker:
    if adapter == "sim":
        return SimBroker(**kwargs)
    if adapter == "alpaca":
        if client is None:
            raise ValueError("Alpaca adapter requires an AlpacaClient instance")
        return AlpacaBroker(client=client, **kwargs)
    raise ValueError(f"Unknown live adapter: {adapter}")


__all__ = [
    "AlpacaBroker",
    "AlpacaClient",
    "build_broker",
    "SimBroker",
    "SimMarketData",
]
