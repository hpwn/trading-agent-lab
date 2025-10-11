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

## Live (paper)

The new live wrapper provides a deterministic “paper” execution path that reuses
the engine configuration. It defaults to the in-repo simulator so tests remain
offline and reproducible.

- `tal live --config config/agents/codex_seed.yaml`
- `tal agent live --config config/agents/codex_seed.yaml`

The broker is selected via the `live` block in your engine or agent config
(`sim` for the offline simulator, `alpaca` for Alpaca's paper trading API).
Real broker connectivity remains behind an optional extra:

```bash
pip install -e ".[alpaca]"
```

Tests and CI only exercise the simulator—no network calls are made.

### Alpaca (paper) quickstart

Install the optional runtime extra and export credentials before running any
paper trades:

```bash
pip install -e ".[alpaca]"
export ALPACA_API_KEY_ID=...
export ALPACA_API_SECRET_KEY=...
# optional overrides
export ALPACA_BASE_URL=...
```

The runtime adapter reads credentials from the environment. A `.env` file with
these keys is sufficient for local testing.

- `ALPACA_BASE_URL` (optional) overrides the *trading* endpoint. The market data
  client uses Alpaca's default data host and is not overridden.

Point the live CLI to the bundled paper config to try the integration:

```bash
tal live --config config/live/alpaca_paper.yaml
```

The config enables guardrails—max order notional, position sizing caps, and
daily loss protection—all enforced locally before the request is sent to Alpaca.

### Live signal routing & sizing

- Signals are produced by the configured strategy (defaults to `rsi_mean_rev`) using
  the most recent `live.bars` closes for the first universe symbol.
- Current routing maps signals to targets as: `+1` → long position sized by
  `strategy.params.size_pct`, `0/-1` → flat (no shorts yet). The live position is
  additionally capped by `live.max_position_pct` of current equity.
- Simulated fills are routed through the in-memory broker to reach the target.
- Tests can provide deterministic price history by passing a price map directly to
  `tal.live.wrapper.run_live_once` (see `tests/test_live_signal_routing.py`).

## League manager

Coordinate multiple agents with the new league controller. By default the league
operates entirely offline—`tal live` and the league runner both use the
simulated broker, so CI and local development remain deterministic.

```bash
tal league live-once --config config/base.yaml
tal league nightly --config config/base.yaml
```

`league live-once` runs a single live step for every agent YAML under
`league.agents_dir`, redirecting each agent to its own ledger directory under
`league.artifacts_dir`. The nightly command loads recent performance from the
shared SQLite database, aggregates metrics, and writes promotion/retirement
recommendations to `artifacts/league/allocations.json`.

Each agent specification now captures provenance metadata (`builder` and
`lineage` blocks). This information is persisted in the `agents` table whenever
live or backtest runs are recorded. The leaderboard CLI supports grouping by
agent or builder to compare strategies from the same model family:

```bash
tal eval --group builder --since 30d --format table
```

The builder view collapses agents by `builder_name`, averaging KPIs across the
latest runs. Use this to compare parameter mutations from the same base model or
prompt lineage.
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
