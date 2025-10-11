from __future__ import annotations

from pathlib import Path

from ..base import Broker, Fill, MarketData, Order


class SimMarketData(MarketData):
    def __init__(self, price_map: dict[str, float]):
        self.price_map = price_map

    def latest_price(self, symbol: str) -> float:
        return float(self.price_map.get(symbol, 100.0))


class SimBroker(Broker):
    def __init__(
        self,
        cash: float,
        ledger_dir: Path,
        commission: float = 0.0,
        slippage_bps: float = 0.0,
    ):
        self._cash = float(cash)
        self._pos: dict[str, float] = {}
        self.ledger_dir = Path(ledger_dir)
        self.ledger_dir.mkdir(parents=True, exist_ok=True)
        self.commission = float(commission)
        self.slippage_bps = float(slippage_bps)
        trades = self.ledger_dir / "trades.csv"
        if not trades.exists():
            trades.write_text("ts,symbol,side,qty,price\n")

    def cash(self) -> float:
        return self._cash

    def position(self, symbol: str) -> float:
        return float(self._pos.get(symbol, 0.0))

    def submit(self, order: Order) -> Fill:
        import time

        px = self._price(order.symbol)
        slip = px * (self.slippage_bps / 1e4)
        exec_px = px + slip if order.side == "buy" else px - slip
        if order.side == "buy":
            cost = exec_px * order.qty + self.commission
            if cost > self._cash:
                raise ValueError("Insufficient cash")
            self._cash -= cost
            self._pos[order.symbol] = self.position(order.symbol) + order.qty
        else:
            if order.qty > self.position(order.symbol):
                raise ValueError("Insufficient position")
            self._cash += exec_px * order.qty - self.commission
            self._pos[order.symbol] = self.position(order.symbol) - order.qty
        with (self.ledger_dir / "trades.csv").open("a") as f:
            f.write(f"{int(time.time())},{order.symbol},{order.side},{order.qty},{exec_px}\n")
        return Fill(order.symbol, order.side, order.qty, exec_px)

    def cancel_all(self) -> None:  # no-op for sim
        return

    def _price(self, symbol: str) -> float:
        return float(self._pos.get("__last_px__", 100.0)) if symbol not in self._pos else 100.0
