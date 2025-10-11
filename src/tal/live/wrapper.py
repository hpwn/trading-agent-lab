from __future__ import annotations

from pathlib import Path
import importlib
import math
from typing import Any

import pandas as pd
from pydantic import BaseModel

from .adapters.sim import SimBroker, SimMarketData
from .base import Order


class LiveCfg(BaseModel):
    broker: str = "sim"  # "sim" | "alpaca" (future)
    cash: float = 10_000
    commission: float = 0.0
    slippage_bps: float = 1.0
    ledger_dir: str = "./artifacts/live"
    bars: int = 200
    max_position_pct: float = 50.0


def _load_strategy(strategy_name: str):
    if strategy_name == "rsi_mean_rev":
        mod = importlib.import_module("tal.strategies.rsi_mean_rev")
        return mod.RSIMeanReversion
    raise ValueError(f"Unknown strategy: {strategy_name}")


def run_live_once(engine_cfg: dict, price_map: dict[str, list[float]] | None = None) -> dict[str, Any]:
    """Execute a single deterministic live trading step."""

    live_cfg = LiveCfg(**engine_cfg.get("live", {}))
    universe = engine_cfg.get("universe", {})
    if isinstance(universe, dict):
        symbols = universe.get("symbols", ["SPY"])
    elif isinstance(universe, (list, tuple)):
        symbols = list(universe) or ["SPY"]
    else:
        symbols = ["SPY"]
    if not symbols:
        symbols = ["SPY"]
    bars = max(1, int(live_cfg.bars))
    history_map: dict[str, list[float] | pd.Series] = {}
    for symbol in symbols:
        prices = None
        if price_map is not None:
            prices = price_map.get(symbol)
        if prices is None:
            prices = [100.0] * bars
        history_map[symbol] = prices
    md = SimMarketData(history_map)
    br = SimBroker(
        live_cfg.cash,
        Path(live_cfg.ledger_dir),
        commission=live_cfg.commission,
        slippage_bps=live_cfg.slippage_bps,
    )
    sym = symbols[0]
    strat_cfg = engine_cfg.get("strategy", {})
    strat_name = strat_cfg.get("name", "rsi_mean_rev")
    params = strat_cfg.get("params", {})
    StratCls = _load_strategy(strat_name)
    allowed_params = {k: params[k] for k in ("rsi_len", "oversold", "overbought") if k in params}
    strat = StratCls(**allowed_params)

    df = md.history(sym, bars)
    sig_series = strat.generate_signals(df)
    last_sig = int(sig_series.iloc[-1]) if not sig_series.empty else 0

    px = md.latest_price(sym)
    current_pos = br.position(sym)
    equity = br.cash() + current_pos * px
    cap = equity * (live_cfg.max_position_pct / 100.0)
    target_qty = 0
    if last_sig > 0:
        size_pct = float(params.get("size_pct", 10.0)) / 100.0
        dollars = min(cap, equity * size_pct)
        target_qty = max(0, math.floor(dollars / max(px, 1e-6)))
    delta = target_qty - current_pos
    fill = None
    if delta > 0:
        fill = br.submit(Order(sym, "buy", qty=float(delta)))
    elif delta < 0:
        fill = br.submit(Order(sym, "sell", qty=float(-delta)))

    return {
        "symbol": sym,
        "signal": last_sig,
        "target_qty": float(target_qty),
        "delta": float(delta),
        "price": float(px),
        "cash_after": br.cash(),
        "fill": fill.__dict__ if fill else None,
    }
