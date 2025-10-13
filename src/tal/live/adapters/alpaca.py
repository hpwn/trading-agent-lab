from __future__ import annotations

from ..base import Broker, Fill, Order
from . import AlpacaClient


class AlpacaBroker(Broker):
    """Broker implementation backed by an :class:`AlpacaClient` instance."""

    def __init__(
        self,
        client: AlpacaClient,
        slippage_bps: float = 0.0,
        max_order_usd: float | None = None,
        max_position_pct: float | None = None,
        max_daily_loss_pct: float | None = None,
        allow_after_hours: bool = False,
        paper: bool = True,
    ) -> None:
        self.client = client
        self.slippage_bps = float(slippage_bps)
        self.max_order_usd = max_order_usd
        self.max_position_pct = max_position_pct
        self.max_daily_loss_pct = max_daily_loss_pct
        self.allow_after_hours = bool(allow_after_hours)
        self.paper = bool(paper)
        self._known_symbols: set[str] = set()

    # Broker interface -------------------------------------------------
    def cash(self) -> float:
        account = self.client.get_account()
        cash = account.get("cash", 0.0)
        return float(cash)

    def position(self, symbol: str) -> float:
        qty = self.client.get_position(symbol)
        self._known_symbols.add(symbol)
        return float(qty)

    def submit(self, order: Order) -> Fill:
        if order.qty <= 0:
            raise ValueError("Order quantity must be positive")
        symbol = order.symbol
        side = order.side.lower()
        qty = float(order.qty)
        px = float(order.ref_price) if order.ref_price is not None else self.price(symbol)
        self._guardrails(symbol, side, qty, px)
        slip = px * (self.slippage_bps / 1e4)
        exec_px = px + slip if side == "buy" else px - slip
        extended_hours = self.allow_after_hours and self.paper
        if extended_hours:
            raw_order = self.client.submit_order(
                symbol=symbol,
                side=side,
                qty=qty,
                type=order.type,
                time_in_force="day",
                extended_hours=True,
            )
        else:
            raw_order = self.client.submit_order(
                symbol=symbol,
                side=side,
                qty=qty,
                type=order.type,
                time_in_force="day",
            )
        self._known_symbols.add(symbol)
        broker_order_id = None
        status = "submitted"
        if isinstance(raw_order, dict):
            broker_order_id = raw_order.get("id") or raw_order.get("order_id")
            status = raw_order.get("status", status)
        fill = Fill(symbol, side, qty, exec_px)
        fill.status = status
        fill.broker_order_id = broker_order_id
        return fill

    def cancel_all(self) -> None:
        # The simple paper adapter does not expose cancelation.
        return None

    # Adapter specific API ---------------------------------------------
    def price(self, symbol: str) -> float:
        px = self.client.get_last_price(symbol)
        self._known_symbols.add(symbol)
        return float(px)

    def positions(self) -> dict[str, float]:
        return {symbol: float(self.client.get_position(symbol)) for symbol in sorted(self._known_symbols)}

    def cash_available(self) -> float:
        return self.cash()

    def is_market_open(self) -> bool:
        return bool(self.client.is_market_open())

    # Helpers ----------------------------------------------------------
    def _guardrails(self, symbol: str, side: str, qty: float, px: float) -> None:
        if not self.is_market_open() and not self.allow_after_hours:
            raise ValueError("Market is closed")
        notional = qty * px
        if self.max_order_usd is not None and notional > self.max_order_usd:
            raise ValueError(
                f"Order value ${notional:0.2f} exceeds max_order_usd ${self.max_order_usd:0.2f}"
            )
        account = self.client.get_account()
        equity_val = float(account.get("equity", 0.0) or 0.0)
        if (
            self.max_position_pct is not None
            and equity_val > 0
            and side.lower() == "buy"
        ):
            current_qty = float(self.client.get_position(symbol) or 0.0)
            target_qty = current_qty + qty
            limit = equity_val * (self.max_position_pct / 100.0)
            position_value = abs(target_qty) * px
            if position_value > limit:
                raise ValueError(
                    f"Position value ${position_value:0.2f} exceeds max_position_pct {self.max_position_pct}%"
                )
        if self.max_daily_loss_pct is not None:
            last_equity = account.get("last_equity")
            if last_equity:
                last_equity = float(last_equity)
                if last_equity > 0:
                    equity_loss_pct = max(0.0, (last_equity - equity_val) / last_equity * 100.0)
                    if equity_loss_pct > self.max_daily_loss_pct:
                        raise ValueError(
                            f"Daily loss {equity_loss_pct:.2f}% exceeds max_daily_loss_pct {self.max_daily_loss_pct}%"
                        )
