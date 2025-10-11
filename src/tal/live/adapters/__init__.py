from __future__ import annotations

from ..base import Broker
from .alpaca import AlpacaBroker, AlpacaClient
from .sim import SimBroker, SimMarketData


def build_broker(
    adapter: str,
    *,
    client: AlpacaClient | None = None,
    **kwargs,
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
