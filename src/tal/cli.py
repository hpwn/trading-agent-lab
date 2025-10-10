import typer
from tal.orchestrator.day_night import run_loop

app = typer.Typer(help="Trading Agent Lab (CLI only)")

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

if __name__ == "__main__":
    app()
