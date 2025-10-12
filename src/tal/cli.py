import json
import os
from pathlib import Path
import tempfile
from typing import Any

# Autoload .env if present (do not override variables already exported)
try:
    from dotenv import find_dotenv, load_dotenv  # type: ignore

    load_dotenv(find_dotenv(usecwd=True), override=False)
except Exception:
    # Optional dependency; continue silently if unavailable or misconfigured
    pass

import typer
import yaml  # type: ignore[import-untyped]

from tal.agents.registry import load_agent_config, to_engine_config
from tal.backtest.engine import _load_config
from tal.live.wrapper import run_live_once, _build_alpaca_client_from_env
from tal.league.manager import LeagueCfg, live_step_all, nightly_eval
from tal.orchestrator.day_night import run_loop

app = typer.Typer(help="Trading Agent Lab (CLI only)")
agent_app = typer.Typer(help="Agent-specific commands")
league_app = typer.Typer(help="League manager: multi-agent live & nightly eval")
doctor_app = typer.Typer(help="Runtime diagnostics")
app.add_typer(agent_app, name="agent")
app.add_typer(league_app, name="league")
app.add_typer(doctor_app, name="doctor")


def _fmt_float(value: Any) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


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
):
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


@agent_app.command("backtest")
def agent_backtest(
    config: str = typer.Option(..., "--config", help="Path to agent config YAML.")
):
    """Backtest for a specific agent YAML."""
    config_path = Path(config)
    spec = load_agent_config(str(config_path))
    engine_cfg = to_engine_config(spec)
    tmp_path = _dump_temp_engine_cfg(engine_cfg)
    from tal.backtest.engine import run_backtest

    run_backtest(tmp_path)


@agent_app.command("run")
def agent_run(config: str = typer.Option(..., "--config", help="Path to agent config YAML.")):
    """Run orchestrator loop for a specific agent YAML."""
    config_path = Path(config)
    spec = load_agent_config(str(config_path))
    engine_cfg = to_engine_config(spec)
    tmp_path = _dump_temp_engine_cfg(engine_cfg)
    from tal.orchestrator.day_night import run_loop as loop

    loop(tmp_path)


def _dump_temp_engine_cfg(engine_cfg: dict) -> str:
    tmp = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
    try:
        yaml.safe_dump(engine_cfg, tmp)
        tmp.flush()
    finally:
        tmp.close()
    return tmp.name


@league_app.command("live-once")
def league_live_once(config: str = "config/base.yaml"):
    """Run one live step for every league agent."""

    cfg = _load_config(config)
    lc = LeagueCfg(**cfg.get("league", {}))
    db_url = cfg.get("storage", {}).get("db_url", "sqlite:///./lab.db")
    res = live_step_all(db_url, lc.agents_dir, lc.artifacts_dir)
    print(json.dumps(res, indent=2))


@league_app.command("nightly")
def league_nightly(config: str = "config/base.yaml"):
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
def orchestrate(config: str = "config/base.yaml"):
    """Run the day/night loop (paper during market; tune after hours)."""
    run_loop(config_path=config)


@app.command()
def backtest(config: str = "config/base.yaml"):
    """Run a single backtest with current strategy + params."""
    # import lazily to keep startup snappy
    from tal.backtest.engine import run_backtest

    run_backtest(config)


@app.command(name="live")
def live_once(config: str = typer.Option(..., "--config", help="Path to engine config YAML.")):
    """Execute one live step using the configured broker (paper by default)."""

    from tal.backtest.engine import load_config

    cfg, _ = load_config(config)
    if isinstance(cfg.get("universe"), list) or "components" in cfg:
        spec = load_agent_config(config)
        cfg = to_engine_config(spec)
    res = run_live_once(cfg)
    print(json.dumps(res, indent=2))


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
):
    """Evaluate the latest runs with optional grouping."""

    from tal.backtest.engine import load_config
    from tal.evaluation.leaderboard import format_json, format_table, resolve_window, summarize
    from tal.storage.db import get_engine

    since_key = since.lower()
    try:
        _, _ = resolve_window(since_key)
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

    fmt = output_format.lower()
    if fmt not in {"table", "json"}:
        raise typer.BadParameter("Format must be 'table' or 'json'.")
    if fmt == "json":
        typer.echo(format_json(rows))
    else:
        typer.echo(format_table(rows, group=group_key))


@agent_app.command("live")
def agent_live(config: str = typer.Option(..., "--config", help="Path to agent config YAML.")):
    """Run one live step for a specific AgentSpec YAML."""

    spec = load_agent_config(config)
    engine_cfg = to_engine_config(spec)
    res = run_live_once(engine_cfg)
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    app()
