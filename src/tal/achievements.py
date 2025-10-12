"""File-backed achievements tracker for fun trading milestones."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

Mode = Literal["paper", "real"]


def _is_enabled() -> bool:
    value = os.getenv("ACHIEVEMENTS_ENABLED", "1")
    return value not in {"0", "false", "False"}


def _dir() -> Path:
    base = os.getenv("ACHIEVEMENTS_DIR", "./artifacts/achievements")
    return Path(base)


def _state_path() -> Path:
    return _dir() / "state.json"


def _log_path() -> Path:
    return _dir() / "log.ndjson"


def _badges_dir() -> Path:
    return _dir() / "badges"


def _ensure_dirs() -> None:
    directory = _dir()
    directory.mkdir(parents=True, exist_ok=True)
    _badges_dir().mkdir(parents=True, exist_ok=True)


def _load_state() -> dict[str, Any]:
    path = _state_path()
    if not path.exists():
        return {"achievements": {}}
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {"achievements": {}}
    if not isinstance(data, dict):
        return {"achievements": {}}
    data.setdefault("achievements", {})
    achievements = data["achievements"]
    if not isinstance(achievements, dict):
        data["achievements"] = {}
    return data


def _save_state(state: dict[str, Any]) -> None:
    _ensure_dirs()
    path = _state_path()
    path.write_text(json.dumps(state, indent=2, sort_keys=True))


def _append_log(entry: dict[str, Any]) -> None:
    _ensure_dirs()
    log_path = _log_path()
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True))
        handle.write("\n")


def _write_badge(entry: dict[str, Any]) -> None:
    _ensure_dirs()
    badge_path = _badges_dir() / f"{entry['key']}.json"
    badge_path.write_text(json.dumps(entry, indent=2, sort_keys=True))


def _fmt_threshold(value: float) -> str:
    if float(value).is_integer():
        return f"{int(value)}"
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _achievement_key(kind: str, threshold: float, mode: Mode) -> str:
    pretty = _fmt_threshold(threshold)
    if kind == "trade":
        return f"{mode}_first_${pretty}_trade"
    return f"{mode}_first_${pretty}_profit"


def _record(kind: str, threshold: float, *, mode: Mode, meta: dict[str, Any]) -> str | None:
    state = _load_state()
    achievements = state.setdefault("achievements", {})
    key = _achievement_key(kind, threshold, mode)
    if key in achievements:
        return None
    ts = datetime.now(timezone.utc).isoformat()
    entry = {"key": key, "ts": ts, "meta": meta}
    achievements[key] = entry
    try:
        _append_log(entry)
        _write_badge(entry)
        _save_state(state)
    except OSError:
        # Best-effort: on filesystem issues, drop unlock and keep state consistent.
        achievements.pop(key, None)
        return None
    return key


_NOTIONAL_THRESHOLDS = [1, 10, 69, 100, 420, 1000]
_PROFIT_THRESHOLDS = [1, 10, 69, 100, 420, 1000]


def get_thresholds() -> dict[str, list[float]]:
    """Return the configured thresholds for achievements."""

    return {
        "notional": list(_NOTIONAL_THRESHOLDS),
        "profit": list(_PROFIT_THRESHOLDS),
    }


def record_trade_notional(notional: float, mode: Mode) -> list[str]:
    """Record trade notional and return unlocked achievements."""

    if not _is_enabled():
        return []
    try:
        value = abs(float(notional))
    except (TypeError, ValueError):
        return []
    unlocked: list[str] = []
    for threshold in _NOTIONAL_THRESHOLDS:
        if value >= threshold:
            key = _record("trade", threshold, mode=mode, meta={"notional": value})
            if key:
                unlocked.append(key)
    return unlocked


def record_profit_dollars(pnl_dollars: float, mode: Mode) -> list[str]:
    """Record realized dollars of profit and return unlocked achievements."""

    if not _is_enabled():
        return []
    try:
        value = float(pnl_dollars)
    except (TypeError, ValueError):
        return []
    if value <= 0:
        return []
    unlocked: list[str] = []
    for threshold in _PROFIT_THRESHOLDS:
        if value >= threshold:
            key = _record("profit", threshold, mode=mode, meta={"profit": value})
            if key:
                unlocked.append(key)
    return unlocked


def list_achievements() -> dict[str, Any]:
    """Return the persisted achievements state."""

    return _load_state()


def is_unlocked(key: str) -> bool:
    """Check if a badge key has already been unlocked."""

    state = _load_state()
    achievements = state.get("achievements", {})
    if not isinstance(achievements, dict):
        return False
    return key in achievements


def reset_achievements() -> None:
    """Wipe all tracked achievements and artifacts."""

    directory = _dir()
    state_path = _state_path()
    log_path = _log_path()
    badges_dir = _badges_dir()
    try:
        if state_path.exists():
            state_path.unlink()
        if log_path.exists():
            log_path.unlink()
        if badges_dir.exists():
            for badge in badges_dir.glob("*.json"):
                badge.unlink()
            try:
                badges_dir.rmdir()
            except OSError:
                pass
    finally:
        if directory.exists() and not any(directory.iterdir()):
            directory.rmdir()


def all_planned_badge_keys() -> list[str]:
    """Return the canonical list of badge keys across modes."""

    keys: list[str] = []
    for mode in ("paper", "real"):
        for threshold in _NOTIONAL_THRESHOLDS:
            keys.append(_achievement_key("trade", threshold, mode))
        for threshold in _PROFIT_THRESHOLDS:
            keys.append(_achievement_key("profit", threshold, mode))
    return keys


__all__ = [
    "all_planned_badge_keys",
    "get_thresholds",
    "is_unlocked",
    "list_achievements",
    "record_profit_dollars",
    "record_trade_notional",
    "reset_achievements",
]
