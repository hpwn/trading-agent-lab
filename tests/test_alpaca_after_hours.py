from __future__ import annotations

import pytest

from tal.live.adapters.alpaca import AlpacaBroker
from tal.live.base import Order


class StubAlpacaClient:
    def __init__(self) -> None:
        self.is_open = False
        self.submitted: list[dict[str, object]] = []

    def get_last_price(self, symbol: str) -> float:
        return 5.0

    def is_market_open(self) -> bool:
        return self.is_open

    def get_account(self) -> dict[str, float]:
        return {"cash": 100.0, "equity": 100.0}

    def get_position(self, symbol: str) -> float:
        return 0.0

    def submit_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        type: str,
        *,
        extended_hours: bool = False,
    ) -> dict:
        self.submitted.append(
            {
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "type": type,
                "extended_hours": extended_hours,
            }
        )
        return {"id": "order-1", "status": "accepted"}


def test_after_hours_disabled_raises() -> None:
    client = StubAlpacaClient()
    broker = AlpacaBroker(client, allow_after_hours=False, paper=True)
    order = Order("SPY", "buy", qty=1.0)

    with pytest.raises(ValueError, match="Market is closed"):
        broker.submit(order)


def test_after_hours_enabled_submits_with_flag() -> None:
    client = StubAlpacaClient()
    broker = AlpacaBroker(client, allow_after_hours=True, paper=True)
    order = Order("SPY", "buy", qty=1.0)

    fill = broker.submit(order)

    assert fill.status == "accepted"
    assert client.submitted
    payload = client.submitted[0]
    assert payload["extended_hours"] is True
