from __future__ import annotations

import importlib
import math
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict, model_validator

from .adapters import AlpacaClient, SimMarketData, build_broker
from .base import Order
from tal.storage.db import get_engine, record_run


class LiveCfg(BaseModel):
    model_config = ConfigDict(extra="allow")

    adapter: str = "sim"
    broker: str | None = None  # backwards compatibility alias
    cash: float = 10_000
    commission: float = 0.0
    slippage_bps: float = 1.0
    ledger_dir: str = "./artifacts/live"
    bars: int = 200
    max_position_pct: float = 50.0
    max_order_usd: float | None = None
    max_daily_loss_pct: float | None = None
    paper: bool = True
    base_url: str | None = None
    symbol: str | None = None
    size_pct: float | None = None

    @model_validator(mode="before")
    @classmethod
    def _alias_adapter(cls, values: Any) -> Any:
        if isinstance(values, dict) and "adapter" not in values and "broker" in values:
            values = {**values, "adapter": values["broker"]}
        return values


def _load_strategy(strategy_name: str):
    if strategy_name == "rsi_mean_rev":
        mod = importlib.import_module("tal.strategies.rsi_mean_rev")
        return mod.RSIMeanReversion
    raise ValueError(f"Unknown strategy: {strategy_name}")


def run_live_once(
    engine_cfg: dict,
    price_map: dict[str, list[float]] | None = None,
    *,
    alpaca_client: AlpacaClient | None = None,
) -> dict[str, Any]:
    """Execute a single deterministic live trading step."""

    ts_start = datetime.now(timezone.utc)
    live_cfg = LiveCfg(**engine_cfg.get("live", {}))
    universe = engine_cfg.get("universe", {})
    symbols: list[str] = []
    if isinstance(universe, dict):
        symbols = list(universe.get("symbols", []))
    elif isinstance(universe, (list, tuple)):
        symbols = list(universe)
    if not symbols and live_cfg.symbol:
        symbols = [live_cfg.symbol]
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

    broker_kwargs: dict[str, Any]
    broker_client: AlpacaClient | None = None
    if live_cfg.adapter == "alpaca":
        broker_kwargs = {
            "slippage_bps": live_cfg.slippage_bps,
            "max_order_usd": live_cfg.max_order_usd,
            "max_position_pct": live_cfg.max_position_pct,
            "max_daily_loss_pct": live_cfg.max_daily_loss_pct,
        }
        broker_client = alpaca_client or _build_alpaca_client_from_env(
            paper=live_cfg.paper,
            base_url=live_cfg.base_url,
        )
    else:
        broker_kwargs = {
            "cash": live_cfg.cash,
            "ledger_dir": Path(live_cfg.ledger_dir),
            "commission": live_cfg.commission,
            "slippage_bps": live_cfg.slippage_bps,
        }
    br = build_broker(live_cfg.adapter, client=broker_client, **broker_kwargs)

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
    if live_cfg.adapter == "alpaca":
        px = br.price(sym)  # type: ignore[attr-defined]
    current_pos = br.position(sym)
    equity = br.cash() + current_pos * px
    cap = equity * (live_cfg.max_position_pct / 100.0)
    target_qty = 0
    if last_sig > 0:
        live_size_pct = live_cfg.size_pct if live_cfg.size_pct is not None else params.get("size_pct")
        size_pct = float(live_size_pct if live_size_pct is not None else 10.0) / 100.0
        dollars = min(cap, equity * size_pct)
        target_qty = max(0, math.floor(dollars / max(px, 1e-6)))
    delta = target_qty - current_pos
    fill = None
    if delta > 0:
        fill = br.submit(Order(sym, "buy", qty=float(delta), ref_price=px))
    elif delta < 0:
        fill = br.submit(Order(sym, "sell", qty=float(-delta), ref_price=px))

    ts_end = datetime.now(timezone.utc)
    result = {
        "symbol": sym,
        "signal": last_sig,
        "target_qty": float(target_qty),
        "delta": float(delta),
        "price": float(px),
        "cash_after": br.cash(),
        "fill": fill.__dict__ if fill else None,
    }
    storage_cfg = engine_cfg.get("storage", {})
    db_url = storage_cfg.get("db_url")
    if db_url:
        agent_cfg = engine_cfg.get("agent") or {}
        agent_id = (
            agent_cfg.get("id")
            or engine_cfg.get("agent_id")
            or engine_cfg.get("agent", {}).get("id")
            or "unknown"
        )
        mode = engine_cfg.get("mode", "live")
        run_id = engine_cfg.get("run_id") or str(uuid.uuid4())
        engine = get_engine(db_url)
        record_run(
            engine,
            {
                "id": run_id,
                "agent_id": agent_id,
                "mode": mode,
                "ts_start": ts_start.isoformat(),
                "ts_end": ts_end.isoformat(),
                "commit_sha": engine_cfg.get("commit_sha"),
                "config_hash": engine_cfg.get("config_hash"),
            },
            [],
            engine_cfg=engine_cfg,
        )
    return result


def _build_alpaca_client_from_env(*, paper: bool, base_url: str | None) -> AlpacaClient:
    api_key = os.environ.get("ALPACA_API_KEY_ID")
    api_secret = os.environ.get("ALPACA_API_SECRET_KEY")
    if not api_key or not api_secret:
        raise RuntimeError("Missing Alpaca API credentials in environment")
    url = base_url or os.environ.get("ALPACA_BASE_URL")
    if not url:
        url = "https://paper-api.alpaca.markets" if paper else "https://api.alpaca.markets"
    try:
        from alpaca.common.exceptions import APIError  # type: ignore
        from alpaca.data.historical import StockHistoricalDataClient  # type: ignore
        from alpaca.data.requests import StockLatestTradeRequest  # type: ignore
        from alpaca.trading.client import TradingClient  # type: ignore
        from alpaca.trading.enums import OrderSide, TimeInForce  # type: ignore
        from alpaca.trading.requests import MarketOrderRequest  # type: ignore
    except Exception as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("alpaca extra not installed. Install with `pip install -e '.[alpaca]'`") from exc

    class _RuntimeAlpacaClient:
        def __init__(self) -> None:
            self._trading = TradingClient(api_key, api_secret, paper=paper, base_url=url)
            self._data = StockHistoricalDataClient(api_key, api_secret, base_url=url)

        def get_last_price(self, symbol: str) -> float:
            req = StockLatestTradeRequest(symbol_or_symbols=symbol)
            latest = self._data.get_stock_latest_trade(req)
            trade = latest[symbol] if isinstance(latest, dict) else latest
            return float(trade.price)

        def is_market_open(self) -> bool:
            clock = self._trading.get_clock()
            return bool(getattr(clock, "is_open", False))

        def get_account(self) -> dict:
            account = self._trading.get_account()
            if hasattr(account, "model_dump") and callable(account.model_dump):
                data = account.model_dump()
            elif hasattr(account, "dict") and callable(account.dict):
                data = account.dict()
            else:
                data = {
                    "cash": float(getattr(account, "cash", 0.0)),
                    "equity": float(getattr(account, "equity", 0.0)),
                    "last_equity": float(getattr(account, "last_equity", getattr(account, "equity", 0.0))),
                }
            return data

        def get_position(self, symbol: str) -> float:
            try:
                pos = self._trading.get_open_position(symbol)
            except APIError:
                return 0.0
            except Exception:
                return 0.0
            qty = getattr(pos, "qty", getattr(pos, "quantity", 0.0))
            try:
                return float(qty)
            except (TypeError, ValueError):
                return float(getattr(pos, "qty_available", 0.0))

        def submit_order(self, symbol: str, side: str, qty: float, type: str) -> dict:
            if type.lower() != "market":
                raise ValueError("Only market orders are supported in AlpacaBroker")
            order_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL
            request = MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=order_side,
                time_in_force=TimeInForce.DAY,
            )
            order = self._trading.submit_order(order_data=request)
            if hasattr(order, "model_dump") and callable(order.model_dump):
                return order.model_dump()
            if hasattr(order, "dict") and callable(order.dict):
                return order.dict()
            return {"symbol": symbol, "side": side, "qty": qty, "type": type}

    return _RuntimeAlpacaClient()
