from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Mapping, Optional, SupportsFloat

# Autoload .env if present (do not override variables already exported)
try:
    from dotenv import find_dotenv, load_dotenv

    load_dotenv(find_dotenv(usecwd=True), override=False)
except Exception:
    # Optional dependency; continue silently if unavailable or misconfigured
    pass

import typer
import yaml

from tal import achievements, achievements_badges
from tal.agents.registry import load_agent_config, to_engine_config
from tal.backtest.engine import _load_config
from tal.live.wrapper import (
    LiveCfg,
    _build_alpaca_client_from_env,
    _truthy,
    build_broker_and_price_fn,
    flatten_symbol,
    run_live_loop,
    run_live_once,
)
from tal.league.manager import LeagueCfg, live_step_all, nightly_eval
from tal.orchestrator.day_night import run_loop
from sqlalchemy import text

from typer import BadParameter, Context, Option, Typer

from tal.storage.db import fetch_metrics_for_runs, fetch_runs_since, get_engine

app = Typer(help="Trading Agent Lab (CLI only)")
agent_app = Typer(help="Agent-specific commands")
league_app = Typer(help="League manager: multi-agent live & nightly eval")
doctor_app = Typer(help="Runtime diagnostics")
achievements_app = Typer(help="Fun, optional trading achievements")
orders_app = Typer(help="Inspect recent orders")
ledger_app = Typer(help="Inspect live trade ledger entries")
live_app = Typer(
    help="Live trading helpers",
    invoke_without_command=True,
    no_args_is_help=False,
)
app.add_typer(agent_app, name="agent")
app.add_typer(league_app, name="league")
app.add_typer(doctor_app, name="doctor")
app.add_typer(achievements_app, name="achievements")
app.add_typer(orders_app, name="orders")
app.add_typer(ledger_app, name="ledger")
app.add_typer(live_app, name="live")


def _fmt_float(value: Any) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def _load_engine_config(config_path: str) -> dict[str, Any]:
    from tal.backtest.engine import load_config

    cfg, _ = load_config(config_path)
    if isinstance(cfg.get("universe"), list) or "components" in cfg:
        spec = load_agent_config(config_path)
        return to_engine_config(spec)
    return cfg


def _resolve_live_achievement_mode(live_cfg: LiveCfg) -> Literal["paper", "real"]:
    execute_flag = os.getenv("LIVE_EXECUTE", "0").lower()
    execute_enabled = execute_flag in {"1", "true", "yes"}
    broker_name = live_cfg.adapter
    return "real" if broker_name == "alpaca" and execute_enabled else "paper"


def _maybe_record_live_profit(result: Mapping[str, Any] | None, live_cfg: LiveCfg) -> None:
    if not result:
        return
    value = result.get("realized_pnl")
    if value is None:
        return
    profit_source = achievements.get_profit_source()
    if profit_source not in {"live", "both"}:
        return
    try:
        profit = float(value)
    except (TypeError, ValueError):
        return
    if profit <= 0:
        return
    mode = _resolve_live_achievement_mode(live_cfg)
    try:
        unlocked = achievements.record_live_profit(mode, profit)
    except Exception as exc:  # pragma: no cover - best effort logging
        typer.echo(f"[achievements] error: {exc}", err=True)
        return
    if unlocked:
        typer.echo(f"[achievements] unlocked: {', '.join(unlocked)}")


@achievements_app.command("ls")
def achievements_ls() -> None:
    """List unlocked achievements."""

    try:
        state = achievements.list_achievements()
    except Exception as exc:  # pragma: no cover - unexpected filesystem issues
        typer.echo(f"[achievements] failed to load state: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    raw_entries = state.get("achievements", {})
    entries: list[dict[str, Any]] = []
    if isinstance(raw_entries, dict):
        for entry in raw_entries.values():
            if isinstance(entry, dict):
                entries.append(entry)
    entries.sort(key=lambda item: str(item.get("ts", "")))
    typer.echo(json.dumps(entries, indent=2, sort_keys=True))


@achievements_app.command("status")
def achievements_status() -> None:
    """Summarize unlocked achievements and upcoming milestones."""

    try:
        state = achievements.list_achievements()
    except Exception as exc:  # pragma: no cover - unexpected filesystem issues
        typer.echo(f"[achievements] failed to load state: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    raw_entries = state.get("achievements", {})
    entries: list[dict[str, Any]] = []
    if isinstance(raw_entries, dict):
        for entry in raw_entries.values():
            if isinstance(entry, dict):
                entries.append(entry)
    entries.sort(key=lambda item: str(item.get("ts", "")))

    if entries:
        typer.echo("Unlocked achievements:")
        for entry in entries:
            key = entry.get("key", "?")
            ts = entry.get("ts", "?")
            typer.echo(f"- {key} @ {ts}")
    else:
        typer.echo("Unlocked achievements: none yet.")

    next_map = achievements.next_thresholds(state)
    profit_source = achievements.get_profit_source()
    profit_label = {"eval": "eval", "live": "live", "both": "eval+live"}.get(
        profit_source,
        "eval",
    )
    source_labels = {"notional": "live", "profit": profit_label}
    typer.echo("Next thresholds:")
    for track in ("notional", "profit"):
        track_info = next_map.get(track, {})
        paper_val = achievements.format_threshold(track_info.get("paper"))
        real_val = achievements.format_threshold(track_info.get("real"))
        source = source_labels.get(track, "?")
        typer.echo(f"- {track} [{source}]: paper -> {paper_val}, real -> {real_val}")


@achievements_app.command("reset")
def achievements_reset(
    yes: bool = typer.Option(
        False,
        "--yes",
        help="Confirm the reset; all achievements and badges will be removed.",
    ),
) -> None:
    """Reset all tracked achievements."""

    if not yes:
        typer.echo("Refusing to reset achievements without --yes", err=True)
        raise typer.Exit(code=1)
    try:
        achievements.reset_achievements()
    except Exception as exc:  # pragma: no cover - filesystem issues
        typer.echo(f"[achievements] failed to reset: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo("Achievements reset.")


@achievements_app.command("badges")
def achievements_badges_cmd(
    stdout: bool = typer.Option(
        False,
        "--stdout",
        help="Print the achievements badge markdown line to stdout.",
    ),
    readme: Path | None = typer.Option(
        None,
        "--readme",
        help="Path to a README to update between badge markers.",
    ),
    style: achievements_badges.Style = typer.Option(
        "flat-square",
        "--style",
        help="Shields.io badge style (flat, flat-square, for-the-badge).",
    ),
    label_case: achievements_badges.LabelCase = typer.Option(
        "lower",
        "--label-case",
        help="Label casing: lower or title.",
    ),
    emojis: bool = Option(
        False,
        "--emojis/--no-emojis",
        help="Append 🔓/🔒 markers to badge labels.",
    ),
) -> None:
    """Generate achievements badge markdown or update a README."""

    try:
        badges_line = achievements_badges.render_badges_line(
            style=style,
            label_case=label_case,
            emojis=emojis,
        )
    except ValueError as exc:
        typer.echo(f"[achievements] {exc}", err=True)
        raise typer.Exit(code=1) from exc

    emit_stdout = stdout or readme is None
    if emit_stdout:
        typer.echo(badges_line)

    if readme is not None:
        updated = achievements_badges.update_readme(readme, badges_line)
        if updated:
            typer.echo(f"[achievements] updated badges in {readme}")
        else:
            typer.echo(f"[achievements] README '{readme}' not found; skipped update.")


@orders_app.command("tail")
def orders_tail(
    limit: int = typer.Option(20, "--limit", min=1, help="Number of rows to show."),
    db: str = typer.Option(
        "sqlite:///./lab.db",
        "--db",
        help="SQLite database URL (defaults to ./lab.db).",
    ),
) -> None:
    """Show the most recent recorded orders."""

    try:
        engine = get_engine(db)
    except Exception as exc:  # pragma: no cover - depends on runtime environment
        typer.echo(f"[orders] failed to open database: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    query = (
        "SELECT rowid AS rowid, ts, broker, symbol, side, qty, price, status "
        "FROM orders ORDER BY rowid DESC LIMIT :limit"
    )
    try:
        with engine.connect() as conn:
            rows = list(conn.execute(text(query), {"limit": int(limit)}).mappings())
    except Exception as exc:  # pragma: no cover - DB runtime issues
        typer.echo(f"[orders] query failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if not rows:
        typer.echo("No orders recorded yet.")
        return

    header = "rowid  ts                        broker   symbol side qty    price   status"
    typer.echo(header)
    for row in rows:
        ts = str(row.get("ts", ""))[:24]
        broker = str(row.get("broker", ""))
        symbol = str(row.get("symbol", ""))
        side = str(row.get("side", ""))
        qty = _fmt_float(row.get("qty"))
        price = _fmt_float(row.get("price"))
        status = str(row.get("status", ""))
        typer.echo(
            f"{row.get('rowid', ''):>5}  {ts:<24} {broker:<7} {symbol:<6} {side:<4} {qty:<6} {price:<7} {status}"
        )


@ledger_app.command("tail")
def ledger_tail(
    limit: int = typer.Option(20, "--limit", min=1, help="Number of rows to show."),
    path: Path = typer.Option(
        Path("./artifacts/live/trades.csv"),
        "--path",
        exists=False,
        file_okay=True,
        dir_okay=False,
        resolve_path=False,
        help="Path to the live trades CSV.",
    ),
) -> None:
    """Tail the live trades ledger (CSV)."""

    if not path.exists():
        typer.echo(f"[ledger] no trades recorded yet at {path}")
        return

    try:
        lines = path.read_text().strip().splitlines()
    except Exception as exc:  # pragma: no cover - filesystem issues
        typer.echo(f"[ledger] failed to read {path}: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if not lines:
        typer.echo("[ledger] trades file is empty.")
        return

    header, *rows = lines
    if not rows:
        typer.echo("[ledger] no trade rows yet.")
        return

    tail_rows = rows[-int(limit) :][::-1]
    typer.echo("epoch                iso_ts                   symbol side qty    price")
    for line in tail_rows:
        parts = line.split(",")
        if len(parts) < 5:
            continue
        ts_raw, symbol, side, qty_raw, price_raw = parts[:5]
        try:
            epoch = int(float(ts_raw))
        except ValueError:
            epoch = 0
        iso_ts = datetime.fromtimestamp(epoch).isoformat() if epoch else "?"
        qty = _fmt_float(qty_raw)
        price = _fmt_float(price_raw)
        typer.echo(
            f"{epoch:<20} {iso_ts:<24} {symbol:<6} {side:<4} {qty:<6} {price:<6}"
        )
@doctor_app.command("alpaca")
def doctor_alpaca(
    symbol: str = typer.Option(
        "SPY",
        "--symbol",
        help="Ticker symbol to fetch the latest price for.",
        show_default=True,
    ),
    paper: bool = typer.Option(
        True,
        "--paper/--live",
        help="Target the paper (default) or live trading environment.",
        show_default=True,
    ),
    base_url: str | None = typer.Option(
        None,
        "--base-url",
        help="Override the Alpaca trading API base URL.",
    ),
) -> None:
    """Validate Alpaca credentials and basic account connectivity."""

    required = ["ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY"]
    missing = [key for key in required if not os.environ.get(key)]
    if missing:
        for key in missing:
            typer.echo(f"[doctor] missing environment variable: {key}", err=True)
        raise typer.Exit(code=1)

    try:
        client = _build_alpaca_client_from_env(paper=paper, base_url=base_url)
    except Exception as exc:  # pragma: no cover - exercised via tests with stubs
        typer.echo(f"[doctor] failed to initialize Alpaca client: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    feed_hint = os.environ.get("ALPACA_FEED")

    try:
        market_open = bool(client.is_market_open())
        account = client.get_account() or {}
        cash = _fmt_float(account.get("cash", 0.0))
        equity = _fmt_float(account.get("equity", account.get("portfolio_value", 0.0)))
        buying_power_val = (
            account.get("buying_power")
            or account.get("cash_available")
            or account.get("cash")
            or account.get("equity")
        )
        buying_power = _fmt_float(buying_power_val) if buying_power_val is not None else "n/a"
        price = _fmt_float(client.get_last_price(symbol))
    except Exception as exc:  # pragma: no cover - depends on runtime client
        typer.echo(f"[doctor] runtime check failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    symbol_upper = symbol.upper()
    typer.echo(f"market_open: {market_open}")
    typer.echo(f"account: cash={cash} equity={equity} buying_power={buying_power}")
    typer.echo(f"latest_price[{symbol_upper}]: {price}")
    if feed_hint:
        typer.echo(f"feed_hint: {feed_hint.lower()}")

    gate_enabled = _truthy(os.environ.get("REAL_TRADING_ENABLED"))
    typer.echo(f"real_trading_enabled: {gate_enabled}")
    live_broker = os.environ.get("LIVE_BROKER", "alpaca_paper")
    typer.echo(f"live_broker: {live_broker}")
    allow_env = os.environ.get("ALLOW_AFTER_HOURS")
    allow_after_hours = _truthy(allow_env) if allow_env is not None else False
    typer.echo(f"allow_after_hours: {allow_after_hours}")
    broker_key = live_broker.strip().lower()
    if broker_key == "alpaca_real" and not gate_enabled:
        typer.secho(
            "WARNING: real broker selected but REAL_TRADING_ENABLED is false/absent.",
            fg="red",
        )


@agent_app.command("backtest")
def agent_backtest(
    config: str = typer.Option(..., "--config", help="Path to agent config YAML.")
) -> None:
    """Backtest for a specific agent YAML."""
    config_path = Path(config)
    spec = load_agent_config(str(config_path))
    engine_cfg = to_engine_config(spec)
    tmp_path = _dump_temp_engine_cfg(engine_cfg)
    from tal.backtest.engine import run_backtest

    run_backtest(tmp_path)


@agent_app.command("run")
def agent_run(
    config: str = typer.Option(..., "--config", help="Path to agent config YAML.")
) -> None:
    """Run orchestrator loop for a specific agent YAML."""
    config_path = Path(config)
    spec = load_agent_config(str(config_path))
    engine_cfg = to_engine_config(spec)
    tmp_path = _dump_temp_engine_cfg(engine_cfg)
    from tal.orchestrator.day_night import run_loop as loop

    loop(tmp_path)


def _dump_temp_engine_cfg(engine_cfg: dict[str, Any]) -> str:
    tmp = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
    try:
        yaml.safe_dump(engine_cfg, tmp)
        tmp.flush()
    finally:
        tmp.close()
    return tmp.name


@league_app.command("live-once")
def league_live_once(config: str = "config/base.yaml") -> None:
    """Run one live step for every league agent."""

    cfg = _load_config(config)
    lc = LeagueCfg(**cfg.get("league", {}))
    db_url = cfg.get("storage", {}).get("db_url", "sqlite:///./lab.db")
    res = live_step_all(db_url, lc.agents_dir, lc.artifacts_dir)
    print(json.dumps(res, indent=2))


@league_app.command("nightly")
def league_nightly(config: str = "config/base.yaml") -> None:
    """Evaluate recent runs and compute allocations."""

    cfg = _load_config(config)
    lc = LeagueCfg(**cfg.get("league", {}))
    db_url = cfg.get("storage", {}).get("db_url", "sqlite:///./lab.db")
    res = nightly_eval(
        db_url,
        lc.artifacts_dir,
        lc.since_days,
        lc.top_k,
        lc.retire_k,
    )
    print(json.dumps(res, indent=2))


@app.command()
def orchestrate(config: str = "config/base.yaml") -> None:
    """Run the day/night loop (paper during market; tune after hours)."""
    run_loop(config_path=config)


@app.command()
def backtest(config: str = "config/base.yaml") -> None:
    """Run a single backtest with current strategy + params."""
    # import lazily to keep startup snappy
    from tal.backtest.engine import run_backtest

    run_backtest(config)



@live_app.callback()
def live_entrypoint(
    ctx: Context,
    config: Optional[str] = Option(
        None,
        "--config",
        help="Path to engine config YAML.",
    ),
    loop: bool = Option(
        False,
        "--loop/--no-loop",
        help="Run repeated live steps until max-steps is reached.",
        show_default=True,
    ),
    interval: float = Option(
        5.0,
        "--interval",
        help="Seconds to sleep between live steps when looping.",
        show_default=True,
    ),
    max_steps: int = Option(
        60,
        "--max-steps",
        help="Maximum live steps to run when looping.",
        show_default=True,
    ),
    flat_at_end: bool = Option(
        False,
        "--flat-at-end/--no-flat-at-end",
        help="Flatten any open position after the loop completes.",
        show_default=True,
    ),
) -> None:
    """Run live trading once or as a loop, optionally flattening at the end."""

    if ctx.invoked_subcommand is not None:
        return

    if not config:
        raise BadParameter("Missing --config for live run")

    cfg = _load_engine_config(config)
    live_cfg = LiveCfg(**cfg.get("live", {}))

    if loop:
        res = run_live_loop(
            cfg,
            max_steps=max_steps,
            interval=interval,
            flat_at_end=flat_at_end,
        )
        typer.echo(json.dumps(res, indent=2))
        flatten = res.get("flatten")
        if isinstance(flatten, Mapping):
            _maybe_record_live_profit(flatten, live_cfg)
    else:
        res = run_live_once(cfg)
        typer.echo(json.dumps(res, indent=2))


@live_app.command("close")
def live_close(
    config: str = Option(..., "--config", help="Path to engine config YAML."),
) -> None:
    """Flatten the configured symbol position for the target broker."""

    cfg = _load_engine_config(config)
    broker, price_fn, context = build_broker_and_price_fn(cfg)
    symbol = context.symbols[0] if context.symbols else (context.live_cfg.symbol or "SPY")
    flatten = flatten_symbol(
        broker,
        symbol,
        price_fn,
        context=context,
        trades_path=context.trades_path,
    )
    typer.echo(json.dumps(flatten, indent=2))
    _maybe_record_live_profit(flatten, context.live_cfg)


@app.command(name="eval")
def evaluate(
    since: str = typer.Option(
        "7d",
        "--since",
        case_sensitive=False,
        help="Lookback window (1d, 7d, 30d).",
        show_default=True,
    ),
    output_format: str = typer.Option(
        "table",
        "--format",
        case_sensitive=False,
        help="Output format: table or json.",
        show_default=True,
    ),
    group: str = typer.Option(
        "agent",
        "--group",
        case_sensitive=False,
        help="Grouping for leaderboard (agent or builder).",
        show_default=True,
    ),
    config: str = typer.Option(
        "config/base.yaml",
        "--config",
        help="Path to config for storage settings.",
        show_default=True,
    ),
) -> None:
    """Evaluate the latest runs with optional grouping."""

    from tal.backtest.engine import load_config
    from tal.evaluation.leaderboard import format_json, format_table, resolve_window, summarize

    since_key = since.lower()
    try:
        _, since_iso = resolve_window(since_key)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc

    window_days = {"1d": 1, "7d": 7, "30d": 30}.get(since_key)
    if window_days is None:
        raise typer.BadParameter("Unsupported window; choose 1d, 7d, or 30d.")

    group_key = group.lower()
    if group_key not in {"agent", "builder"}:
        raise typer.BadParameter("Group must be 'agent' or 'builder'.")

    cfg, _ = load_config(config)
    storage_cfg = cfg.get("storage", {})
    db_url = storage_cfg.get("db_url", "sqlite:///./lab.db")

    engine = get_engine(db_url)
    rows = summarize(engine, since_days=window_days, group=group_key)

    pnl_pct_total = 0.0
    try:
        runs = fetch_runs_since(engine, since_iso)
        if runs:
            run_ids = [str(row.get("id")) for row in runs if row.get("id") is not None]
            metrics = fetch_metrics_for_runs(engine, run_ids)
            for metric in metrics:
                if metric.get("name") != "pnl":
                    continue
                value_obj = metric.get("value")
                if isinstance(value_obj, (int, float)):
                    pnl_pct_total += float(value_obj)
                    continue
                if isinstance(value_obj, SupportsFloat):
                    pnl_pct_total += float(value_obj)
                    continue
                if isinstance(value_obj, str):
                    try:
                        pnl_pct_total += float(value_obj)
                        continue
                    except ValueError:
                        continue
    except Exception:
        pnl_pct_total = 0.0

    capital_raw = os.getenv("CAPITAL")
    try:
        capital = float(capital_raw) if capital_raw is not None else 10_000.0
    except (TypeError, ValueError):
        capital = 10_000.0
    pnl_dollars = max(0.0, pnl_pct_total * capital)
    execute_flag = os.getenv("LIVE_EXECUTE", "0").lower()
    execute_enabled = execute_flag in {"1", "true", "yes"}
    broker_mode_raw = os.getenv("LIVE_BROKER", "")
    broker_mode = broker_mode_raw.strip().lower()
    is_real_broker = broker_mode in {"alpaca_real", "alpaca", "alpaca-live"}
    achievement_mode: Literal["paper", "real"] = (
        "real" if is_real_broker and execute_enabled else "paper"
    )

    fmt = output_format.lower()
    if fmt not in {"table", "json"}:
        raise typer.BadParameter("Format must be 'table' or 'json'.")
    if fmt == "json":
        typer.echo(format_json(rows))
    else:
        typer.echo(format_table(rows, group=group_key))

    profit_source = achievements.get_profit_source()
    if pnl_dollars > 0 and profit_source in {"eval", "both"}:
        try:
            unlocked = achievements.record_profit_dollars(pnl_dollars, achievement_mode)
        except Exception as exc:  # pragma: no cover - best effort logging
            typer.echo(f"[achievements] error: {exc}", err=True)
        else:
            if unlocked:
                typer.echo(f"[achievements] unlocked: {', '.join(unlocked)}")


@agent_app.command("live")
def agent_live(
    config: str = typer.Option(..., "--config", help="Path to agent config YAML.")
) -> None:
    """Run one live step for a specific AgentSpec YAML."""

    spec = load_agent_config(config)
    engine_cfg = to_engine_config(spec)
    res = run_live_once(engine_cfg)
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    app()
