from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..base import Broker, Fill, MarketData, Order


class SimMarketData(MarketData):
    def __init__(self, series_map: dict[str, pd.Series] | dict[str, list[float]]):
        self._series: dict[str, pd.Series] = {}
        self._cursor: dict[str, int] = {}
        for symbol, values in series_map.items():
            if isinstance(values, pd.Series):
                ser = values.rename("Close")
            else:
                ser = pd.Series(list(values), name="Close")
            if not len(ser):
                ser = pd.Series([100.0], name="Close")
            if not isinstance(ser.index, pd.RangeIndex):
                ser = ser.reset_index(drop=True)
            self._series[symbol] = ser.astype(float)
            self._cursor[symbol] = len(self._series[symbol]) - 1

    def latest_price(self, symbol: str) -> float:
        ser = self._series.get(symbol)
        if ser is None or ser.empty:
            return 100.0
        idx = self._cursor.get(symbol, len(ser) - 1)
        idx = max(0, min(idx, len(ser) - 1))
        self._cursor[symbol] = idx
        return float(ser.iloc[idx])

    def history(self, symbol: str, bars: int) -> pd.DataFrame:
        ser = self._series.get(symbol)
        if ser is None or ser.empty:
            ser = pd.Series([100.0] * max(1, bars), name="Close")
        tail = ser.iloc[-bars:] if bars > 0 else ser
        if bars > 0 and len(tail) < bars:
            last_val = float(tail.iloc[-1]) if len(tail) else 100.0
            pad_len = bars - len(tail)
            pad = pd.Series([last_val] * pad_len, name="Close")
            tail = pd.concat([pad, tail], ignore_index=True)
        return tail.rename("Close").to_frame()


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

    def cash(self) -> float:
        return self._cash

    def position(self, symbol: str) -> float:
        return float(self._pos.get(symbol, 0.0))

    def submit(self, order: Order) -> Fill:
        px = float(order.ref_price) if order.ref_price is not None else self._price(order.symbol)
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
        fill = Fill(order.symbol, order.side, order.qty, exec_px)
        fill.status = "filled"
        fill.broker_order_id = None
        return fill

    def cancel_all(self) -> None:  # no-op for sim
        return

    def _price(self, symbol: str) -> float:
        return float(self._pos.get("__last_px__", 100.0)) if symbol not in self._pos else 100.0
