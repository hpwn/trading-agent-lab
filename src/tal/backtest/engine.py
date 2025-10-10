import hashlib
import json
import math
import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

from tal.evaluation.metrics import compute_kpis
from tal.storage.db import get_engine, record_run
from tal.strategies.rsi_mean_rev import RSIMeanReversion

DEFAULT_ENV = {
    "ENV": "dev",
    "TZ": "America/New_York",
    "DATA_SYMBOL": "SPY",
    "CAPITAL": "1000",
    "MAX_DRAWDOWN_PCT": "20",
}


def _load_env(env_file: str | None = None) -> None:
    env_path = Path(env_file or os.environ.get("TAL_ENV_FILE", ".env"))
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())
    for key, value in DEFAULT_ENV.items():
        os.environ.setdefault(key, value)


def _load_data(symbol: str, lookback_bars: int, tf: str) -> pd.DataFrame:
    df = yf.download(symbol, period="max", interval="1d", auto_adjust=True)  # simple daily
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(-1)
    return df.tail(lookback_bars).dropna()


def _pnl_from_signals(df: pd.DataFrame, sig: pd.Series, size_pct: float = 10.0) -> pd.DataFrame:
    ret = df["Close"].pct_change().fillna(0.0)
    pos = sig.shift(1).fillna(0.0)  # enter on next bar open (simplified)
    strat_ret = pos * (size_pct/100.0) * ret
    eq = (1.0 + strat_ret).cumprod()
    return pd.DataFrame({"ret": strat_ret, "eq": eq})


def _safe_metric_value(value: object) -> float | None:
    if isinstance(value, (int, float)):
        numeric = float(value)
        if math.isfinite(numeric):
            return numeric
    return None


def load_config(config_path: str):
    import yaml

    _load_env()
    raw = Path(config_path).read_text()
    expanded = raw
    for k, v in os.environ.items():
        expanded = expanded.replace("${" + k + "}", v)
    cfg = yaml.safe_load(expanded)
    return cfg, expanded


def _current_commit_sha() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except FileNotFoundError:
        return None
    return None


def run_backtest(config_path: str):
    cfg, expanded_config = load_config(config_path)
    run_id = os.environ.get("RUN_ID", str(uuid.uuid4()))
    agent_id = cfg.get("agent", {}).get("id") or cfg.get("strategy", {}).get("name", "unknown")
    ts_start = datetime.now(timezone.utc)

    sym = cfg["universe"]["symbols"][0]
    df = _load_data(sym, cfg["data"]["lookback_bars"], cfg["data"]["timeframe"])
    params = dict(cfg["strategy"]["params"])
    size_pct = float(params.pop("size_pct", 10))
    strat = RSIMeanReversion(**params)
    sig = strat.generate_signals(df)
    res = _pnl_from_signals(df, sig, size_pct=size_pct)
    kpis = compute_kpis(res["ret"], res["eq"])
    safe_metrics = {name: _safe_metric_value(value) for name, value in kpis.items()}

    storage_cfg = cfg.get("storage", {})
    db_url = storage_cfg.get("db_url", "sqlite:///./lab.db")
    artifacts_dir = Path(storage_cfg.get("artifacts_dir", "./artifacts")).expanduser()

    commit_sha = _current_commit_sha()
    config_hash = hashlib.sha256(expanded_config.encode()).hexdigest()

    ts_end = datetime.now(timezone.utc)

    engine = get_engine(db_url)
    record_run(
        engine,
        {
            "id": run_id,
            "agent_id": agent_id,
            "mode": "backtest",
            "ts_start": ts_start.isoformat(),
            "ts_end": ts_end.isoformat(),
            "commit_sha": commit_sha,
            "config_hash": config_hash,
        },
        [
            {"run_id": run_id, "name": name, "value": safe_metrics[name]}
            for name in kpis
        ],
    )

    run_artifacts = artifacts_dir / "runs" / run_id
    run_artifacts.mkdir(parents=True, exist_ok=True)
    (run_artifacts / "metrics.json").write_text(json.dumps(safe_metrics, indent=2))
    (run_artifacts / "config.snapshot.yaml").write_text(expanded_config)

    if storage_cfg.get("write_signals_parquet", False):
        try:
            signal_df = pd.DataFrame({"signal": sig})
            signal_df.to_parquet(run_artifacts / "signals.parquet")
        except Exception as exc:  # pragma: no cover - optional dependency
            print(f"[WARN] Failed to write signals parquet: {exc}")

    print(
        "[BACKTEST] run=%s agent=%s symbol=%s bars=%s eq_end=%.3f" % (
            run_id,
            agent_id,
            sym,
            len(df),
            res["eq"].iloc[-1],
        )
    )
