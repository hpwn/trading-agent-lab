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
