from __future__ import annotations

import datetime as dt
import os
from pathlib import Path
import zoneinfo
import yaml  # type: ignore[import-untyped]

from tal.league.manager import LeagueCfg, live_step_all, nightly_eval

DEFAULT_ENV = {
    "ENV": "dev",
    "TZ": "America/New_York",
    "DATA_SYMBOL": "SPY",
    "CAPITAL": "1000",
    "MAX_DRAWDOWN_PCT": "20",
}


def _load_env(env_file: str | None = None) -> None:
    """Load environment variables from a .env-style file with defaults."""

    env_candidate = env_file if env_file is not None else os.environ.get("TAL_ENV_FILE")
    if env_candidate is None:
        env_candidate = ".env"
    env_path = Path(env_candidate)
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
    for k, v in os.environ.items():
        raw = raw.replace("${" + k + "}", v)
    return yaml.safe_load(raw)


def market_open_now(cfg) -> bool:
    tz = zoneinfo.ZoneInfo(cfg["orchestrator"]["market_hours"]["timezone"])
    now = dt.datetime.now(tz)
    hours = cfg["orchestrator"]["market_hours"]
    open_t = dt.datetime.combine(now.date(), dt.time.fromisoformat(hours["open"]), tz)
    close_t = dt.datetime.combine(now.date(), dt.time.fromisoformat(hours["close"]), tz)
    return open_t <= now <= close_t and now.weekday() <= 4


def run_loop(config_path: str):
    cfg = _load_cfg(config_path)
    storage_cfg = cfg.get("storage", {})
    db_url = storage_cfg.get("db_url", "sqlite:///./lab.db")
    league_cfg = LeagueCfg(**cfg.get("league", {}))
    if market_open_now(cfg):
        print("[ORCH] Market hours detected; running league live step", flush=True)
        return live_step_all(db_url, league_cfg.agents_dir, league_cfg.artifacts_dir)
    print("[ORCH] Off hours detected; running nightly evaluation", flush=True)
    return nightly_eval(
        db_url,
        league_cfg.artifacts_dir,
        league_cfg.since_days,
        league_cfg.top_k,
        league_cfg.retire_k,
    )
