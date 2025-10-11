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

## Running multiple agents

The CLI exposes agent-aware commands that load an `AgentSpec` and run the
existing backtest/orchestrator tooling with the derived engine config.

```bash
tal agent backtest --config config/agents/codex_seed.yaml
tal agent run --config config/agents/codex_seed.yaml
```

To run multiple agents simultaneously with Docker Compose, uncomment and
adapt the example services in `docker-compose.yml`:

```yaml
  # agent_codex_seed:
  #   build: .
  #   env_file: .env
  #   command: ["agent","run","--config","config/agents/codex_seed.yaml"]
  #   volumes: ["./artifacts:/app/artifacts", "./lab.db:/app/lab.db"]

  # agent_rsi_v2:
  #   image: trading-agent-lab-lab
  #   command: ["agent","run","--config","config/agents/rsi_v2.yaml"]
  #   volumes: ["./artifacts:/app/artifacts", "./lab.db:/app/lab.db"]
```

For a one-off backtest inside Docker without editing the compose file:

```bash
docker compose run --rm lab tal agent backtest --config config/agents/codex_seed.yaml
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

## Tests & CI

Local:
```bash
python -m pip install -U pip
pip install -e .[test]
pytest
```

CI runs on PRs (Python 3.11/3.12) and also builds the Docker image. Lint/type checks use Ruff & mypy:

```bash
pip install -e .[lint]
ruff check .
mypy --ignore-missing-imports src
```
