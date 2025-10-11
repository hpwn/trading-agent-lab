from pathlib import Path
import tempfile

import typer
import yaml

from tal.agents.registry import load_agent_config, to_engine_config
from tal.orchestrator.day_night import run_loop

app = typer.Typer(help="Trading Agent Lab (CLI only)")
agent_app = typer.Typer(help="Agent-specific commands")
app.add_typer(agent_app, name="agent")


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
    config: str = typer.Option(
        "config/base.yaml",
        "--config",
        help="Path to config for storage settings.",
        show_default=True,
    ),
):
    """Evaluate the latest backtests for each agent."""

    from tal.backtest.engine import load_config
    from tal.evaluation.leaderboard import (
        build_leaderboard,
        format_json,
        format_table,
        resolve_window,
    )
    from tal.storage.db import get_engine

    since_key = since.lower()
    try:
        _, since_iso = resolve_window(since_key)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc

    cfg, _ = load_config(config)
    storage_cfg = cfg.get("storage", {})
    db_url = storage_cfg.get("db_url", "sqlite:///./lab.db")

    engine = get_engine(db_url)
    leaderboard = build_leaderboard(engine, since_iso)

    fmt = output_format.lower()
    if fmt not in {"table", "json"}:
        raise typer.BadParameter("Format must be 'table' or 'json'.")
    if fmt == "json":
        typer.echo(format_json(leaderboard))
    else:
        typer.echo(format_table(leaderboard))


if __name__ == "__main__":
    app()
