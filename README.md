# Trading Agent Lab (CLI-only)

- v0: RSI mean reversion baseline with daily bars on a single symbol.
- Day/Night loop: paper/backtest behavior during market, self-tune after hours.
- Next: metrics persistence, Optuna tuner, multi-agent league & capital allocation.

## Quickstart
```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env
tal backtest --config config/base.yaml
tal orchestrate --config config/base.yaml
```

## Docker Quickstart

```bash
docker compose build --no-cache
docker compose up
# Logs stream immediately (unbuffered). Ctrl+C to stop.
docker compose down
```

**Troubleshooting**

* No logs? Ensure your image includes `ENV PYTHONUNBUFFERED=1` (see Dockerfile).
* Force a single backtest in a one-off container:

```bash
docker compose run --rm lab tal backtest --config config/base.yaml
```

* To force “market open” path quickly, copy config then widen hours:

```bash
cp config/base.yaml config/dev.yaml
# set orchestrator.cycle_minutes: 1
# set open: "00:01"  and close: "23:59"
docker compose run --rm lab tal orchestrate --config config/dev.yaml
```
