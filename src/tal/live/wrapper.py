from __future__ import annotations

import importlib
import math
import os
import sys
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import time
from pathlib import Path
from typing import Any, Literal, Optional, cast

from pandas import Series
from pydantic import BaseModel, ConfigDict, model_validator

from .adapters import AlpacaClient, SimMarketData, build_broker
from .base import Broker, Fill, Order
from tal.achievements import record_trade_notional
from tal.storage.db import get_engine, record_order, record_run


def _truthy(value: str | None) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _require_real_trading_unlock() -> None:
    if not _truthy(os.environ.get("REAL_TRADING_ENABLED")):
        raise RuntimeError(
            "Real trading is locked. Set REAL_TRADING_ENABLED=true in your environment "
            "to allow orders to be sent to a real broker. "
            "Tip: keep LIVE_BROKER=alpaca_paper until you’re ready."
        )


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
    allow_after_hours: bool = False

    @model_validator(mode="before")
    @classmethod
    def _alias_adapter(cls, values: Any) -> Any:
        if isinstance(values, dict) and "adapter" not in values and "broker" in values:
            values = {**values, "adapter": values["broker"]}
        return values


def _ensure_ledger(ledger_dir: Path) -> Path:
    ledger_dir.mkdir(parents=True, exist_ok=True)
    trades_path = ledger_dir / "trades.csv"
    if not trades_path.exists():
        trades_path.write_text("ts,symbol,side,qty,price\n")
    return trades_path


def _append_trade(trades_path: Path, fill: Fill, *, ts: datetime) -> None:
    epoch = int(ts.timestamp())
    with trades_path.open("a") as handle:
        handle.write(f"{epoch},{fill.symbol},{fill.side},{fill.qty},{fill.price}\n")


def _load_strategy(strategy_name: str) -> type[Any]:
    if strategy_name == "rsi_mean_rev":
        mod = importlib.import_module("tal.strategies.rsi_mean_rev")
        return mod.RSIMeanReversion
    raise ValueError(f"Unknown strategy: {strategy_name}")


def _select_alpaca_urls(
    *, paper: bool, trading_env: str | None, data_env: str | None = None
) -> tuple[str, str]:
    """Decide trading and data base URLs for Alpaca clients."""

    trading_url = (
        trading_env
        or ("https://paper-api.alpaca.markets" if paper else "https://api.alpaca.markets")
    )
    data_url = data_env or "https://data.alpaca.markets"
    return trading_url, data_url



@dataclass
class _RuntimeContext:
    engine_cfg: dict[str, Any]
    live_cfg: LiveCfg
    symbols: list[str]
    trades_path: Path
    db_engine: Any | None
    agent_id: str
    mode: str


def _resolve_symbols(engine_cfg: dict[str, Any], live_cfg: LiveCfg) -> list[str]:
    universe = engine_cfg.get("universe", {})
    symbols: list[str] = []
    if isinstance(universe, Mapping):
        raw_symbols = universe.get("symbols", [])
        if isinstance(raw_symbols, (list, tuple)):
            symbols = [str(sym) for sym in raw_symbols]
    elif isinstance(universe, (list, tuple)):
        symbols = [str(sym) for sym in universe]
    if not symbols and live_cfg.symbol:
        symbols = [live_cfg.symbol]
    if not symbols:
        symbols = ["SPY"]
    return symbols


def _build_history_map(
    symbols: Sequence[str],
    bars: int,
    price_map: Mapping[str, Sequence[float] | Series] | None,
) -> dict[str, list[float]]:
    history_map: dict[str, list[float]] = {}
    for symbol in symbols:
        prices: Sequence[float] | Series | None = None
        if price_map is not None:
            prices = price_map.get(symbol)
        if prices is None:
            price_values = [100.0] * bars
        elif isinstance(prices, Series):
            price_values = [float(p) for p in prices.tolist()]
        else:
            price_values = [float(p) for p in list(prices)[:bars]]
            if len(price_values) < bars:
                price_values = (
                    price_values + [price_values[-1]] * (bars - len(price_values))
                    if price_values
                    else [100.0] * bars
                )
        history_map[symbol] = price_values
    return history_map


def _prepare_runtime_context(engine_cfg: dict[str, Any]) -> _RuntimeContext:
    live_cfg = LiveCfg(**engine_cfg.get("live", {}))
    ledger_dir = Path(live_cfg.ledger_dir)
    trades_path = _ensure_ledger(ledger_dir)
    symbols = _resolve_symbols(engine_cfg, live_cfg)
    storage_cfg = engine_cfg.get("storage", {})
    db_url = storage_cfg.get("db_url")
    db_engine = get_engine(db_url) if db_url else None
    agent_cfg_obj = engine_cfg.get("agent")
    agent_cfg: Mapping[str, Any] = (
        agent_cfg_obj if isinstance(agent_cfg_obj, Mapping) else {}
    )
    agent_id = (
        agent_cfg.get("id")
        or engine_cfg.get("agent_id")
        or agent_cfg.get("agent_id")
        or "unknown"
    )
    mode = engine_cfg.get("mode", "live")
    return _RuntimeContext(engine_cfg, live_cfg, symbols, trades_path, db_engine, agent_id, mode)


def _build_broker_for_context(
    context: _RuntimeContext,
    *,
    alpaca_client: AlpacaClient | None,
) -> tuple[Broker, AlpacaClient | None]:
    live_cfg = context.live_cfg
    ledger_dir = Path(live_cfg.ledger_dir)
    broker_kwargs: dict[str, Any]
    if live_cfg.adapter == "alpaca":
        if not live_cfg.paper:
            _require_real_trading_unlock()
        broker_kwargs = {
            "slippage_bps": live_cfg.slippage_bps,
            "max_order_usd": live_cfg.max_order_usd,
            "max_position_pct": live_cfg.max_position_pct,
            "max_daily_loss_pct": live_cfg.max_daily_loss_pct,
            "allow_after_hours": live_cfg.allow_after_hours,
            "paper": live_cfg.paper,
        }
        client = alpaca_client or _build_alpaca_client_from_env(
            paper=live_cfg.paper,
            base_url=live_cfg.base_url,
        )
        broker = build_broker("alpaca", client=client, **broker_kwargs)
        return broker, client
    broker_kwargs = {
        "cash": live_cfg.cash,
        "ledger_dir": ledger_dir,
        "commission": live_cfg.commission,
        "slippage_bps": live_cfg.slippage_bps,
    }
    broker = build_broker("sim", client=None, **broker_kwargs)
    return broker, None


def _achievement_mode(live_cfg: LiveCfg) -> Literal["paper", "real"]:
    execute_flag = os.getenv("LIVE_EXECUTE", "0").lower()
    execute_enabled = execute_flag in {"1", "true", "yes"}
    broker_name = live_cfg.adapter
    return "real" if broker_name == "alpaca" and execute_enabled else "paper"


def _record_fill(
    context: _RuntimeContext,
    fill: Fill,
    trades_path: Path,
    run_id: str,
) -> None:
    event_ts = datetime.now(timezone.utc)
    _append_trade(trades_path, fill, ts=event_ts)
    if context.db_engine is not None:
        broker_order_id = getattr(fill, "broker_order_id", None)
        record_order(
            context.db_engine,
            {
                "id": broker_order_id or f"{run_id}:{uuid.uuid4()}",
                "ts": event_ts.isoformat(),
                "agent_id": context.agent_id,
                "symbol": fill.symbol,
                "side": fill.side,
                "qty": fill.qty,
                "price": fill.price,
                "broker": context.live_cfg.adapter,
                "broker_order_id": broker_order_id,
                "status": getattr(fill, "status", "filled"),
            },
        )

    try:
        notional = abs(float(fill.price) * float(fill.qty))
        achievement_mode = _achievement_mode(context.live_cfg)
        unlocked = record_trade_notional(notional, achievement_mode)
        if unlocked:
            print(f"[achievements] unlocked: {', '.join(unlocked)}")
    except Exception as exc:  # pragma: no cover - best effort logging
        print(f"[achievements] error: {exc}", file=sys.stderr)


def _compute_open_position_from_ledger(
    trades_path: Path,
    symbol: str,
) -> tuple[float, float]:
    if not trades_path.exists():
        return 0.0, 0.0
    qty = 0.0
    avg_cost = 0.0
    try:
        with trades_path.open("r", encoding="utf-8") as handle:
            next(handle, None)
            for line in handle:
                parts = line.strip().split(",")
                if len(parts) < 5:
                    continue
                _, line_symbol, side, qty_raw, price_raw = parts[:5]
                if line_symbol != symbol:
                    continue
                try:
                    trade_qty = float(qty_raw)
                    trade_price = float(price_raw)
                except (TypeError, ValueError):
                    continue
                signed_qty = trade_qty if side.lower() == "buy" else -trade_qty
                new_qty = qty + signed_qty
                if qty == 0 or (qty > 0 and new_qty > 0 and signed_qty > 0) or (
                    qty < 0 and new_qty < 0 and signed_qty < 0
                ):
                    if new_qty != 0:
                        avg_cost = (
                            (avg_cost * abs(qty)) + (trade_price * abs(signed_qty))
                        ) / abs(new_qty)
                elif new_qty == 0:
                    avg_cost = 0.0
                elif (qty > 0 and new_qty > 0) or (qty < 0 and new_qty < 0):
                    pass
                else:
                    avg_cost = trade_price if new_qty != 0 else 0.0
                qty = new_qty
    except OSError:
        return 0.0, 0.0
    return qty, avg_cost


def _make_price_fn(
    broker: Broker,
    context: _RuntimeContext,
    last_prices: Mapping[str, float],
) -> Callable[[str], float]:
    def _price(symbol: str) -> float:
        if symbol in last_prices:
            return float(last_prices[symbol])
        price_attr = getattr(broker, "price", None)
        if callable(price_attr):
            price_callable = cast(Callable[[str], float], price_attr)
            try:
                return float(price_callable(symbol))
            except Exception:
                pass
        bars = max(1, int(context.live_cfg.bars))
        history = _build_history_map([symbol], bars, None)
        values = history.get(symbol, [])
        return float(values[-1]) if values else 100.0

    return _price


def build_broker_and_price_fn(
    engine_cfg: dict[str, Any],
    *,
    price_map: Mapping[str, Sequence[float] | Series] | None = None,
    alpaca_client: AlpacaClient | None = None,
) -> tuple[Broker, Callable[[str], float], _RuntimeContext]:
    """Construct a broker and price function for the given engine config."""

    context = _prepare_runtime_context(engine_cfg)
    broker, _ = _build_broker_for_context(context, alpaca_client=alpaca_client)
    last_prices: dict[str, float] = {}
    if price_map is not None:
        for symbol, values in price_map.items():
            if isinstance(values, Series) and not values.empty:
                last_prices[str(symbol)] = float(values.iloc[-1])
            elif isinstance(values, Sequence) and not isinstance(values, (str, bytes)) and values:
                last_prices[str(symbol)] = float(values[-1])
    price_fn = _make_price_fn(broker, context, last_prices)
    return broker, price_fn, context


def _execute_step(
    context: _RuntimeContext,
    broker: Broker,
    *,
    price_map: Mapping[str, Sequence[float] | Series] | None,
    run_id: str,
    ts_start: datetime | None = None,
) -> tuple[dict[str, Any], datetime, dict[str, float]]:
    ts_start = ts_start or datetime.now(timezone.utc)
    live_cfg = context.live_cfg
    bars = max(1, int(live_cfg.bars))
    history_map = _build_history_map(context.symbols, bars, price_map)
    md = SimMarketData(history_map)

    strat_cfg = context.engine_cfg.get("strategy", {})
    strat_name = strat_cfg.get("name", "rsi_mean_rev")
    params = strat_cfg.get("params", {})
    StratCls = _load_strategy(strat_name)
    allowed_params = {
        k: params[k]
        for k in ("rsi_len", "oversold", "overbought")
        if k in params
    }
    strat = StratCls(**allowed_params)

    sym = context.symbols[0]
    df = md.history(sym, bars)
    sig_series = strat.generate_signals(df)
    last_sig = int(sig_series.iloc[-1]) if not sig_series.empty else 0

    px = float(md.latest_price(sym))
    last_prices: dict[str, float] = {sym: px}
    price_attr = getattr(broker, "price", None)
    if live_cfg.adapter == "alpaca" and callable(price_attr):
        price_callable = cast(Callable[[str], float], price_attr)
        try:
            px = float(price_callable(sym))
            last_prices[sym] = px
        except Exception:
            pass

    current_pos = float(broker.position(sym))
    equity = broker.cash() + current_pos * px
    cap = equity * (live_cfg.max_position_pct / 100.0)
    target_qty = 0.0
    if last_sig > 0:
        live_size_pct = (
            live_cfg.size_pct if live_cfg.size_pct is not None else params.get("size_pct")
        )
        size_pct = float(live_size_pct if live_size_pct is not None else 10.0) / 100.0
        dollars = min(cap, equity * size_pct)
        target_qty = float(max(0, math.floor(dollars / max(px, 1e-6))))

    delta = target_qty - current_pos
    fill: Fill | None = None
    if delta > 0:
        fill = broker.submit(Order(sym, "buy", qty=float(delta), ref_price=px))
    elif delta < 0:
        fill = broker.submit(Order(sym, "sell", qty=float(-delta), ref_price=px))

    ts_end = datetime.now(timezone.utc)
    result = {
        "symbol": sym,
        "signal": last_sig,
        "target_qty": float(target_qty),
        "delta": float(delta),
        "price": float(px),
        "cash_after": broker.cash(),
        "fill": fill.__dict__ if fill else None,
    }

    if fill:
        _record_fill(context, fill, context.trades_path, run_id)

    if context.db_engine is not None:
        record_run(
            context.db_engine,
            {
                "id": run_id,
                "agent_id": context.agent_id,
                "mode": context.mode,
                "ts_start": ts_start.isoformat(),
                "ts_end": ts_end.isoformat(),
                "commit_sha": context.engine_cfg.get("commit_sha"),
                "config_hash": context.engine_cfg.get("config_hash"),
            },
            [],
            engine_cfg=context.engine_cfg,
        )

    return result, ts_end, last_prices


def run_live_once(
    engine_cfg: dict[str, Any],
    price_map: Mapping[str, Sequence[float] | Series] | None = None,
    *,
    alpaca_client: AlpacaClient | None = None,
) -> dict[str, Any]:
    """Execute a single deterministic live trading step."""

    context = _prepare_runtime_context(engine_cfg)
    broker, _ = _build_broker_for_context(context, alpaca_client=alpaca_client)
    run_id = context.engine_cfg.get("run_id") or str(uuid.uuid4())
    result, _, _ = _execute_step(
        context,
        broker,
        price_map=price_map,
        run_id=run_id,
    )
    return result


def run_live_loop(
    engine_cfg: dict[str, Any],
    max_steps: int,
    interval: float,
    flat_at_end: bool,
    price_map: Mapping[str, Sequence[float] | Series] | None = None,
    *,
    alpaca_client: AlpacaClient | None = None,
) -> dict[str, Any]:
    """Run multiple live steps with optional terminal flatten."""

    context = _prepare_runtime_context(engine_cfg)
    broker, _ = _build_broker_for_context(context, alpaca_client=alpaca_client)
    steps: list[dict[str, Any]] = []
    last_prices: dict[str, float] = {}
    base_run_id = context.engine_cfg.get("run_id") or str(uuid.uuid4())
    total_steps = max(0, int(max_steps))
    for idx in range(total_steps):
        step_run_id = f"{base_run_id}:{idx + 1}" if total_steps > 1 else base_run_id
        result, _, price_snapshot = _execute_step(
            context,
            broker,
            price_map=price_map,
            run_id=step_run_id,
        )
        steps.append(result)
        last_prices.update(price_snapshot)
        if idx < total_steps - 1 and interval > 0:
            time.sleep(interval)

    flatten_result: dict[str, Any] | None = None
    if flat_at_end:
        flatten_run_id = f"{base_run_id}:flatten"
        price_fn = _make_price_fn(broker, context, last_prices)
        symbol = context.symbols[0]
        flatten_result = flatten_symbol(
            broker,
            symbol,
            price_fn,
            context=context,
            trades_path=context.trades_path,
            run_id=flatten_run_id,
        )

    loop_result: dict[str, Any] = {"steps": steps}
    if flatten_result is not None:
        loop_result["flatten"] = flatten_result
    return loop_result


def flatten_symbol(
    br: Broker,
    symbol: str,
    price_fn: Callable[[str], float],
    *,
    context: _RuntimeContext | None = None,
    trades_path: Path | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Flatten a symbol position for the provided broker."""

    current_pos = float(br.position(symbol))
    exec_hint = float(price_fn(symbol))

    if (
        abs(current_pos) <= 1e-9
        and context is not None
        and trades_path is not None
    ):
        ledger_qty, _ = _compute_open_position_from_ledger(trades_path, symbol)
        if abs(ledger_qty) > 1e-9:
            current_pos = ledger_qty
            pos_attr = getattr(br, "_pos", None)
            if isinstance(pos_attr, dict):
                pos_attr[str(symbol)] = float(ledger_qty)

    if abs(current_pos) <= 1e-9:
        return {
            "symbol": symbol,
            "qty": 0.0,
            "exec_px": exec_hint,
            "realized_pnl": 0.0,
            "status": "flat",
        }

    side = "sell" if current_pos > 0 else "buy"
    order_qty = float(abs(current_pos))
    fill = br.submit(Order(symbol, side, qty=order_qty, ref_price=exec_hint))
    exec_px = float(getattr(fill, "price", exec_hint))
    status = getattr(fill, "status", "filled")

    realized: float | None = None
    if (
        context is not None
        and trades_path is not None
        and context.live_cfg.adapter == "sim"
    ):
        realized = _compute_sim_flatten_pnl(
            trades_path,
            symbol,
            exit_px=exec_px,
            qty=current_pos,
        )

    if context is not None and trades_path is not None:
        record_run_id = run_id or context.engine_cfg.get("run_id") or str(uuid.uuid4())
        _record_fill(context, fill, trades_path, record_run_id)

    return {
        "symbol": symbol,
        "qty": float(fill.qty),
        "side": fill.side,
        "exec_px": exec_px,
        "realized_pnl": realized,
        "status": status,
    }


def _compute_sim_flatten_pnl(
    trades_path: Path,
    symbol: str,
    *,
    exit_px: float,
    qty: float,
) -> float:
    if not trades_path.exists():
        return 0.0

    open_qty, avg_cost = _compute_open_position_from_ledger(trades_path, symbol)
    if abs(open_qty) <= 1e-9:
        return 0.0

    effective_qty = min(abs(open_qty), abs(qty))
    if effective_qty <= 0:
        return 0.0

    if open_qty > 0:
        return (exit_px - avg_cost) * effective_qty
    return (avg_cost - exit_px) * effective_qty



def _build_alpaca_client_from_env(*, paper: bool, base_url: str | None) -> AlpacaClient:
    api_key = os.environ.get("ALPACA_API_KEY_ID")
    api_secret = os.environ.get("ALPACA_API_SECRET_KEY")
    if not api_key or not api_secret:
        raise RuntimeError("Missing Alpaca API credentials in environment")
    trading_env = base_url or os.environ.get("ALPACA_BASE_URL")
    data_env = os.environ.get("ALPACA_DATA_URL")
    trading_url, data_url = _select_alpaca_urls(
        paper=paper,
        trading_env=trading_env,
        data_env=data_env,
    )
    try:
        from alpaca.common.exceptions import APIError
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockLatestTradeRequest
        from alpaca.trading.client import TradingClient
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest
    except Exception as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("alpaca extra not installed. Install with `pip install -e '.[alpaca]'`") from exc

    class _RuntimeAlpacaClient:
        def __init__(self) -> None:
            trading_kwargs: dict[str, Any] = {"paper": paper}
            if trading_env:
                trading_kwargs["url_override"] = trading_url
            self._trading = TradingClient(api_key, api_secret, **trading_kwargs)

            data_kwargs: dict[str, Any] = {}
            if data_env:
                # Market data lives under data.alpaca.markets; only override if explicitly set.
                data_kwargs["base_url"] = data_url
            self._data = StockHistoricalDataClient(api_key, api_secret, **data_kwargs)

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

        def submit_order(
            self,
            *,
            symbol: str,
            side: str,
            qty: float,
            type: str = "market",
            time_in_force: str = "day",
            extended_hours: Optional[bool] = None,
        ) -> dict:
            if type.lower() != "market":
                raise ValueError("Only market orders are supported in AlpacaBroker")
            order_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL
            tif_enum = TimeInForce.DAY if time_in_force.lower() == "day" else TimeInForce.DAY
            request_kwargs = {
                "symbol": symbol,
                "qty": qty,
                "side": order_side,
                "time_in_force": tif_enum,
            }
            if extended_hours:
                try:
                    request = MarketOrderRequest(**request_kwargs, extended_hours=True)
                except TypeError:
                    request = MarketOrderRequest(**request_kwargs)
            else:
                request = MarketOrderRequest(**request_kwargs)
            order = self._trading.submit_order(order_data=request)
            if hasattr(order, "model_dump") and callable(order.model_dump):
                return order.model_dump()
            if hasattr(order, "dict") and callable(order.dict):
                return order.dict()
            return {"symbol": symbol, "side": side, "qty": qty, "type": type}

    return _RuntimeAlpacaClient()
