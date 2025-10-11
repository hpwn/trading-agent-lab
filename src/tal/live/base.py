from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import pandas as pd


@dataclass
class Order:
    symbol: str
    side: str  # "buy" | "sell"
    qty: float
    type: str = "market"
    ref_price: float | None = None  # optional price hint used by paper broker


@dataclass
class Fill:
    symbol: str
    side: str
    qty: float
    price: float


class Broker(ABC):
    @abstractmethod
    def cash(self) -> float: ...

    @abstractmethod
    def position(self, symbol: str) -> float: ...

    @abstractmethod
    def submit(self, order: Order) -> Fill: ...

    @abstractmethod
    def cancel_all(self) -> None: ...


class MarketData(ABC):
    @abstractmethod
    def latest_price(self, symbol: str) -> float: ...

    @abstractmethod
    def history(self, symbol: str, bars: int) -> "pd.DataFrame": ...
