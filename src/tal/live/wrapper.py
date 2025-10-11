from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from .adapters.sim import SimBroker, SimMarketData
from .base import Order


class LiveCfg(BaseModel):
    broker: str = "sim"  # "sim" | "alpaca" (future)
    cash: float = 10_000
    commission: float = 0.0
    slippage_bps: float = 1.0
    ledger_dir: str = "./artifacts/live"


def run_live_once(engine_cfg: dict, price_map: dict[str, float] | None = None) -> dict:
    """Execute a single deterministic live trading step."""

    live_cfg = LiveCfg(**engine_cfg.get("live", {}))
    universe = engine_cfg.get("universe", {})
    if isinstance(universe, dict):
        symbols = universe.get("symbols", ["SPY"])
    elif isinstance(universe, (list, tuple)):
        symbols = list(universe) or ["SPY"]
    else:
        symbols = ["SPY"]
    md = SimMarketData(price_map or {s: 100.0 for s in symbols})
    br = SimBroker(
        live_cfg.cash,
        Path(live_cfg.ledger_dir),
        commission=live_cfg.commission,
        slippage_bps=live_cfg.slippage_bps,
    )
    sym = symbols[0]
    _ = md.latest_price(sym)
    fill = br.submit(Order(sym, "buy", qty=1))
    return {"symbol": sym, "fill": fill.__dict__, "cash_after": br.cash()}
