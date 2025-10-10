import pandas as pd, numpy as np, yfinance as yf
import os
from pathlib import Path
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
    df = yf.download(symbol, period="max", interval="1d")  # simple daily
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(-1)
    return df.tail(lookback_bars).dropna()


def _pnl_from_signals(df: pd.DataFrame, sig: pd.Series, size_pct: float = 10.0) -> pd.DataFrame:
    ret = df["Close"].pct_change().fillna(0.0)
    pos = sig.shift(1).fillna(0.0)  # enter on next bar open (simplified)
    strat_ret = pos * (size_pct/100.0) * ret
    eq = (1.0 + strat_ret).cumprod()
    return pd.DataFrame({"ret": strat_ret, "eq": eq})


def run_backtest(config_path: str):
    import yaml

    _load_env()
    with open(config_path, "r") as f:
        raw = f.read()
    for k,v in os.environ.items():
        raw = raw.replace("${"+k+"}", v)
    cfg = yaml.safe_load(raw)
    sym = cfg["universe"]["symbols"][0]
    df = _load_data(sym, cfg["data"]["lookback_bars"], cfg["data"]["timeframe"])
    params = dict(cfg["strategy"]["params"])
    size_pct = float(params.pop("size_pct", 10))
    strat = RSIMeanReversion(**params)
    sig = strat.generate_signals(df)
    res = _pnl_from_signals(df, sig, size_pct=size_pct)
    print(f"[BACKTEST] {sym} | bars={len(df)} | eq_end={res['eq'].iloc[-1]:.3f}")
