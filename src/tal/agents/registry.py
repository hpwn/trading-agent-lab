from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Match

import yaml

from .spec import AgentSpec

_VAR = re.compile(r"\$\{([^}]+)\}")


def _expand_env(text: str) -> str:
    def repl(match: Match[str]) -> str:
        return os.environ.get(match.group(1), "")

    return _VAR.sub(repl, text)


def short_name_from(dotted_or_short: str) -> str:
    """Return the shorthand strategy name from a dotted path."""
    if "." in dotted_or_short:
        parts = dotted_or_short.split(".")
        return parts[-2]
    return dotted_or_short


def load_agent_config(path: str) -> AgentSpec:
    txt = Path(path).read_text()
    raw = yaml.safe_load(_expand_env(txt)) or {}
    if isinstance(raw, dict) and "agent" in raw:
        agent_meta = raw.pop("agent") or {}
        for key in ("id", "version", "capital"):
            if key in agent_meta and key not in raw:
                raw[key] = agent_meta[key]
    spec = AgentSpec.model_validate(raw)
    return spec


def to_engine_config(spec: AgentSpec) -> dict:
    metadata = spec.metadata.model_dump() if spec.metadata else {}
    return {
        "env": "dev",
        "agent_id": spec.id,
        "agent": {
            "id": spec.id,
            "metadata": metadata,
        },
        "universe": {"symbols": spec.universe},
        "data": {
            "timeframe": spec.data.timeframe,
            "lookback_bars": spec.data.lookback_bars,
        },
        "strategy": {
            "name": short_name_from(spec.components.strategy),
            "params": spec.strategy.get("params", {}),
        },
        "risk": {
            "max_drawdown_pct": spec.risk.max_drawdown_pct,
            "max_position_pct": spec.risk.max_position_pct,
        },
        "evaluation": {"kpis": spec.evaluation.kpis},
        "orchestrator": {
            "market_hours": spec.orchestrator.market_hours.model_dump(),
            "cycle_minutes": spec.orchestrator.cycle_minutes,
        },
        "storage": {
            "db_url": spec.storage.db_url,
            "artifacts_dir": spec.storage.artifacts_dir,
        },
        "live": spec.live.model_dump(),
    }
