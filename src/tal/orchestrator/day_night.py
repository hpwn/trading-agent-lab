from __future__ import annotations

import datetime as dt
import os
import time
from pathlib import Path
from typing import Any
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


def market_open_now(cfg, now: dt.datetime | None = None) -> bool:
    hours = cfg["orchestrator"]["market_hours"]
    tz = zoneinfo.ZoneInfo(hours["timezone"])
    ts = now or dt.datetime.now(tz)
    open_t = dt.datetime.combine(ts.date(), dt.time.fromisoformat(hours["open"]), tz)
    close_t = dt.datetime.combine(ts.date(), dt.time.fromisoformat(hours["close"]), tz)
    return open_t <= ts < close_t and ts.weekday() <= 4


def _summarize(result) -> str:
    if isinstance(result, list):
        return f"{len(result)} agents"
    if isinstance(result, dict):
        items = list(result.items())[:3]
        if not items:
            return "empty"
        return ", ".join(f"{k}={v}" for k, v in items)
    return str(result)


def run_loop(config_path: str):
    cfg = _load_cfg(config_path)
    storage_cfg = cfg.get("storage", {})
    db_url = storage_cfg.get("db_url", "sqlite:///./lab.db")
    league_cfg = LeagueCfg(**cfg.get("league", {}))
    orch_cfg = cfg.get("orchestrator", {})
    hours = orch_cfg.get("market_hours", {})
    tz_name = hours.get("timezone", "America/New_York")
    open_window = hours.get("open", "09:30")
    close_window = hours.get("close", "16:00")
    cycle_minutes = float(orch_cfg.get("cycle_minutes", 5))
    cycle_seconds = max(1, int(cycle_minutes * 60))
    print(
        f"[ORCH] boot tz={tz_name} open={open_window} close={close_window} cycle={cycle_minutes}m",
        flush=True,
    )
    tz = zoneinfo.ZoneInfo(tz_name)
    try:
        while True:
            now = dt.datetime.now(tz)
            is_open = market_open_now(cfg, now=now)
            mode = "live" if is_open else "nightly"
            try:
                result: Any
                if is_open:
                    result = live_step_all(db_url, league_cfg.agents_dir, league_cfg.artifacts_dir)
                else:
                    result = nightly_eval(
                        db_url,
                        league_cfg.artifacts_dir,
                        league_cfg.since_days,
                        league_cfg.top_k,
                        league_cfg.retire_k,
                    )
                summary = _summarize(result)
                print(
                    f"[ORCH] cycle[{mode}] {now.isoformat()} {summary}",
                    flush=True,
                )
            except Exception as exc:  # pragma: no cover - runtime guardrail
                print(f"[ORCH] cycle[{mode}] error: {exc}", flush=True)
            time.sleep(cycle_seconds)
    except KeyboardInterrupt:  # pragma: no cover - manual shutdown
        print("[ORCH] shutdown requested", flush=True)
