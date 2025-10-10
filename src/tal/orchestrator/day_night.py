import os
import time
import datetime as dt
import zoneinfo
import yaml
from pathlib import Path
from tal.backtest.engine import run_backtest
# from tal.execution.paper import run_paper_tick
from tal.evolution.tuner import nightly_tune

DEFAULT_ENV = {
    "ENV": "dev",
    "TZ": "America/New_York",
    "DATA_SYMBOL": "SPY",
    "CAPITAL": "1000",
    "MAX_DRAWDOWN_PCT": "20",
}


def _load_env(env_file: str | None = None) -> None:
    """Load environment variables from a .env-style file with defaults."""
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


def _load_cfg(path: str):
    _load_env()
    with open(path, "r") as f:
        raw = f.read()
    # naive ${ENV_VAR} expansion
    for k,v in os.environ.items():
        raw = raw.replace("${"+k+"}", v)
    return yaml.safe_load(raw)


def market_open_now(cfg) -> bool:
    tz = zoneinfo.ZoneInfo(cfg["orchestrator"]["market_hours"]["timezone"])
    now = dt.datetime.now(tz)
    o = cfg["orchestrator"]["market_hours"]["open"]
    c = cfg["orchestrator"]["market_hours"]["close"]
    open_t = dt.datetime.combine(now.date(), dt.time.fromisoformat(o), tz)
    close_t = dt.datetime.combine(now.date(), dt.time.fromisoformat(c), tz)
    return open_t <= now <= close_t and now.weekday() <= 4


def run_loop(config_path: str):
    cfg = _load_cfg(config_path)
    print("[BOOT] Orchestrator started; cycle_minutes="
          f"{cfg['orchestrator']['cycle_minutes']}", flush=True)
    interval = int(cfg["orchestrator"]["cycle_minutes"])
    while True:
        if market_open_now(cfg):
            # Minimal placeholder: backtest-on-the-fly (paper exec stubbed)
            run_backtest(config_path)  # replace with paper broker polling
        else:
            nightly_tune(config_path)  # hyperparam search / mutations
        time.sleep(60 * interval)
