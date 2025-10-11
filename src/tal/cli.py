import json
from pathlib import Path
import tempfile

import typer
import yaml  # type: ignore[import-untyped]

from tal.agents.registry import load_agent_config, to_engine_config
from tal.backtest.engine import _load_config
from tal.live.wrapper import run_live_once
from tal.league.manager import LeagueCfg, live_step_all, nightly_eval
from tal.orchestrator.day_night import run_loop

app = typer.Typer(help="Trading Agent Lab (CLI only)")
agent_app = typer.Typer(help="Agent-specific commands")
league_app = typer.Typer(help="League manager: multi-agent live & nightly eval")
app.add_typer(agent_app, name="agent")
app.add_typer(league_app, name="league")


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
