from __future__ import annotations

import pytest
from typer.testing import CliRunner

from tal.cli import app
from tal.live.adapters.alpaca import AlpacaBroker
from tal.live.base import Order


class _StubClient:
    def __init__(self, *, market_open: bool = True, price: float = 660.0) -> None:
        self._market_open = market_open
        self._price = price
        self._cash = 50_000.0
        self._equity = 50_000.0
        self._positions: dict[str, float] = {}
        self.last_kwargs: dict[str, object] | None = None

    def is_market_open(self) -> bool:
        return self._market_open

    def get_last_price(self, symbol: str) -> float:
        return float(self._price)

    def get_account(self) -> dict[str, float]:
        return {"cash": self._cash, "equity": self._equity, "last_equity": self._equity}

    def get_position(self, symbol: str) -> float:
        return float(self._positions.get(symbol, 0.0))

    def submit_order(self, **kwargs: object) -> dict[str, object]:
        self.last_kwargs = kwargs
        side = str(kwargs.get("side", "buy"))
        qty = float(kwargs.get("qty", 0.0))
        symbol = str(kwargs.get("symbol", "SPY"))
        if side == "buy":
            self._positions[symbol] = self._positions.get(symbol, 0.0) + qty
        else:
            self._positions[symbol] = self._positions.get(symbol, 0.0) - qty
        return {"status": "submitted", "id": "stub"}


def test_live_max_order_env_override_allows_large_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIVE_MAX_ORDER_USD", "10000")
    client = _StubClient()
    broker = AlpacaBroker(client, max_order_usd=5.0)

    fill = broker.submit(Order("SPY", "buy", qty=1.0, ref_price=660.0))

    assert fill.qty == pytest.approx(1.0)
    assert client.last_kwargs and float(client.last_kwargs["qty"]) == pytest.approx(1.0)


def test_clip_order_to_max_downsizes_qty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIVE_MAX_ORDER_USD", "700")
    monkeypatch.setenv("CLIP_ORDER_TO_MAX", "1")
    client = _StubClient(price=660.0)
    broker = AlpacaBroker(client, max_order_usd=5.0)

    fill = broker.submit(Order("SPY", "buy", qty=7.0, ref_price=660.0))

    assert fill.qty == pytest.approx(1.0)
    assert client.last_kwargs and float(client.last_kwargs["qty"]) == pytest.approx(1.0)


def test_doctor_closed_market_hint_without_after_hours(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPACA_API_KEY_ID", "key")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "secret")
    monkeypatch.delenv("ALLOW_AFTER_HOURS", raising=False)

    stub = _StubClient(market_open=False, price=660.0)
    monkeypatch.setattr("tal.cli._build_alpaca_client_from_env", lambda **_: stub)

    runner = CliRunner()
    result = runner.invoke(app, ["doctor", "alpaca", "--symbol", "SPY"])

    assert result.exit_code == 0, result.stdout
    assert "export ALLOW_AFTER_HOURS=1" in result.stdout
    assert "Default max_order_usd" in result.stdout or "exceeds max_order_usd" in result.stdout
