from __future__ import annotations

import json
from glob import glob
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel

from tal.agents.registry import load_agent_config, to_engine_config
from tal.live.adapters import AlpacaClient
from tal.live.wrapper import run_live_once
from tal.storage.db import Engine


class LeagueCfg(BaseModel):
    agents_dir: str = "config/agents"
    artifacts_dir: str = "artifacts/league"
    top_k: int = 3
    retire_k: int = 1
    since_days: int = 30


def list_agent_files(agents_dir: str) -> list[str]:
    return sorted(glob(str(Path(agents_dir) / "*.yaml")))


def _force_db_url(cfg: dict[str, Any], db_url: str | None) -> None:
    if not db_url:
        return
    storage = cfg.setdefault("storage", {})
    storage["db_url"] = db_url


def live_step_all(
    engine_db_url: str,
    agents_dir: str,
    artifacts_dir: str,
    *,
    alpaca_client_factory: Callable[[dict[str, Any]], AlpacaClient | None] | None = None,
) -> list[dict]:
    """Run one live step for each configured agent."""

    base_artifacts = Path(artifacts_dir)
    base_artifacts.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    for file_path in list_agent_files(agents_dir):
        spec = load_agent_config(file_path)
        cfg = to_engine_config(spec)
        _force_db_url(cfg, engine_db_url)
        agent_info = cfg.get("agent", {})
        agent_id = agent_info.get("id") or cfg.get("agent_id", "unnamed")
        live_cfg = cfg.setdefault("live", {})
        live_cfg["ledger_dir"] = str(base_artifacts / "live" / agent_id)
        adapter_name = live_cfg.get("adapter") or live_cfg.get("broker", "sim")
        injected_client = None
        if adapter_name == "alpaca" and alpaca_client_factory is not None:
            injected_client = alpaca_client_factory(cfg)
        res = run_live_once(cfg, alpaca_client=injected_client)
        results.append({"agent_id": agent_id, **res})
    (base_artifacts / "last_live.json").write_text(json.dumps(results, indent=2))
    return results


def nightly_eval(
    engine_db_url: str,
    artifacts_dir: str,
    since_days: int,
    top_k: int,
    retire_k: int,
) -> dict:
    """Compute leaderboard summary and allocation recommendations."""

    db = Engine(engine_db_url)
    from tal.evaluation.leaderboard import summarize

    rows = summarize(db, since_days=since_days, group="agent")
    rows_sorted = sorted(
        rows,
        key=lambda r: (
            r.get("sharpe") if r.get("sharpe") is not None else float("-inf"),
            r.get("profit_factor")
            if r.get("profit_factor") is not None
            else float("-inf"),
        ),
        reverse=True,
    )
    promote = [row["agent_id"] for row in rows_sorted[:top_k]] if rows_sorted else []
    retire = [row["agent_id"] for row in rows_sorted[-retire_k:]] if retire_k and rows_sorted else []
    allocations = (
        {aid: round(1.0 / len(promote), 4) for aid in promote}
        if promote
        else {}
    )
    out = {
        "since_days": since_days,
        "promote": promote,
        "retire": retire,
        "allocations": allocations,
        "rows": rows_sorted,
    }
    target_dir = Path(artifacts_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "allocations.json").write_text(json.dumps(out, indent=2))
    return out


__all__ = [
    "LeagueCfg",
    "list_agent_files",
    "live_step_all",
    "nightly_eval",
]
