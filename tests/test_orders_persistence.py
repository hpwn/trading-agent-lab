import sqlite3

import pandas as pd

from tal.live.base import Fill
from tal.live.wrapper import run_live_once


class _AlwaysLongStrategy:
    def __init__(self, **_: object) -> None:
        return

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:  # type: ignore[override]
        if df.empty:
            return pd.Series([1])
        return pd.Series([1] * len(df), index=df.index)


class _FakeBroker:
    def __init__(self) -> None:
        self._cash = 10_000.0
        self._pos = 0.0

    def cash(self) -> float:
        return self._cash

    def position(self, symbol: str) -> float:
        return self._pos

    def submit(self, order) -> Fill:
        price = float(order.ref_price or 100.0)
        qty = float(order.qty)
        if order.side == "buy":
            self._cash -= price * qty
            self._pos += qty
        else:
            self._cash += price * qty
            self._pos -= qty
        fill = Fill(order.symbol, order.side, qty, price)
        fill.status = "filled"
        fill.broker_order_id = "fake-001"
        return fill

    def price(self, symbol: str) -> float:
        return 100.0

    def cancel_all(self) -> None:
        return None


def test_orders_persisted_to_csv_and_db(monkeypatch, tmp_path):
    monkeypatch.setattr("tal.live.wrapper._load_strategy", lambda name: _AlwaysLongStrategy)

    fake_broker = _FakeBroker()

    def fake_build_broker(adapter: str, **_: object):
        assert adapter == "sim"
        return fake_broker

    monkeypatch.setattr("tal.live.wrapper.build_broker", fake_build_broker)

    ledger_dir = tmp_path / "artifacts/live"
    db_path = tmp_path / "lab.db"

    engine_cfg = {
        "universe": {"symbols": ["SPY"]},
        "strategy": {"name": "rsi_mean_rev", "params": {"size_pct": 50}},
        "live": {
            "adapter": "sim",
            "ledger_dir": str(ledger_dir),
            "cash": 10_000.0,
            "slippage_bps": 0.0,
        },
        "storage": {"db_url": f"sqlite:///{db_path}"},
        "agent": {"id": "agent-test"},
    }

    run_live_once(engine_cfg, price_map={"SPY": [95.0] * 200})

    trades_path = ledger_dir / "trades.csv"
    assert trades_path.exists()
    rows = [line for line in trades_path.read_text().splitlines() if line]
    assert rows[0] == "ts,symbol,side,qty,price"
    assert len(rows) == 2

    conn = sqlite3.connect(db_path)
    try:
        stored = conn.execute(
            "SELECT broker, broker_order_id, agent_id, symbol, status FROM orders"
        ).fetchall()
    finally:
        conn.close()

    assert len(stored) == 1
    broker, broker_order_id, agent_id, symbol, status = stored[0]
    assert broker == "sim"
    assert broker_order_id == "fake-001"
    assert agent_id == "agent-test"
    assert symbol == "SPY"
    assert status == "filled"
