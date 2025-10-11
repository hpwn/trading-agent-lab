from __future__ import annotations

from dataclasses import dataclass

import pytest

from tal.live.adapters.alpaca import AlpacaBroker, AlpacaClient
from tal.live.base import Order
from tal.live.wrapper import run_live_once
from tal.league import manager


@dataclass
class FakeOrder:
    symbol: str
    side: str
    qty: float
    type: str


class FakeClient:
    def __init__(self) -> None:
        self._cash = 10_000.0
        self._equity = 10_000.0
        self._last_equity = 10_000.0
        self._positions: dict[str, float] = {}
        self._market_open = True
        self.last_order: FakeOrder | None = None

    def get_last_price(self, symbol: str) -> float:
        return 50.0

    def is_market_open(self) -> bool:
        return self._market_open

    def get_account(self) -> dict:
        return {
            "cash": self._cash,
            "equity": self._equity,
            "last_equity": self._last_equity,
        }

    def get_position(self, symbol: str) -> float:
        return self._positions.get(symbol, 0.0)

    def submit_order(self, symbol: str, side: str, qty: float, type: str) -> dict:
        if side == "buy":
            self._positions[symbol] = self._positions.get(symbol, 0.0) + qty
            self._cash -= self.get_last_price(symbol) * qty
        else:
            self._positions[symbol] = self._positions.get(symbol, 0.0) - qty
            self._cash += self.get_last_price(symbol) * qty
        self.last_order = FakeOrder(symbol, side, qty, type)
        return {
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "type": type,
        }


def test_alpaca_broker_guardrails() -> None:
    client = FakeClient()
    broker = AlpacaBroker(
        client,
        slippage_bps=0.0,
        max_order_usd=1000.0,
        max_position_pct=10.0,
        max_daily_loss_pct=5.0,
    )
    fill = broker.submit(Order("SPY", "buy", qty=1.0, ref_price=50.0))
    assert fill.price == pytest.approx(50.0)
    # Order value guardrail
    tight_broker = AlpacaBroker(client, max_order_usd=1.0)
    with pytest.raises(ValueError, match="max_order_usd"):
        tight_broker.submit(Order("SPY", "buy", qty=1.0, ref_price=50.0))
    # Daily loss guardrail
    loss_client = FakeClient()
    loss_client._equity = 9_000.0
    loss_client._last_equity = 10_000.0
    loss_broker = AlpacaBroker(loss_client, max_daily_loss_pct=5.0)
    with pytest.raises(ValueError, match="Daily loss"):
        loss_broker.submit(Order("SPY", "buy", qty=1.0, ref_price=50.0))


def test_alpaca_broker_uses_ref_price() -> None:
    client = FakeClient()
    broker = AlpacaBroker(client, slippage_bps=0.0)
    fill = broker.submit(Order("SPY", "buy", qty=1.0, ref_price=42.0))
    assert fill.price == pytest.approx(42.0)
    assert client.last_order == FakeOrder("SPY", "buy", 1.0, "market")


def test_live_once_uses_injected_alpaca_client() -> None:
    client = FakeClient()
    cfg = {
        "live": {
            "adapter": "alpaca",
            "symbol": "SPY",
            "size_pct": 5,
            "max_position_pct": 10,
            "slippage_bps": 0,
        }
    }
    prices = [100.0 - i * 0.2 for i in range(100)] + [80.0 + i * 0.3 for i in range(100)]
    result = run_live_once(cfg, price_map={"SPY": prices}, alpaca_client=client)
    assert result["fill"] is not None
    assert client.last_order is not None


def test_league_live_step_all_injects_client(tmp_path) -> None:
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    agent_cfg = """
id: test_agent
components:
  strategy: rsi_mean_rev
live:
  adapter: alpaca
"""
    (agents_dir / "agent.yaml").write_text(agent_cfg)
    artifacts_dir = tmp_path / "artifacts"
    client = FakeClient()
    called: list[bool] = []

    def factory(cfg: dict) -> AlpacaClient:
        called.append(True)
        return client

    results = manager.live_step_all(
        "",
        str(agents_dir),
        str(artifacts_dir),
        alpaca_client_factory=factory,
    )
    assert called, "alpaca_client_factory should be invoked"
    assert results and results[0]["agent_id"] == "test_agent"
