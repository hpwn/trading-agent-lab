from __future__ import annotations

from tal.achievements import (
    list_achievements,
    record_trade_notional,
    reset_achievements,
)


def test_trade_notional_unlock(monkeypatch, tmp_path):
    achievements_dir = tmp_path / "achievements"
    monkeypatch.setenv("ACHIEVEMENTS_DIR", str(achievements_dir))
    monkeypatch.setenv("ACHIEVEMENTS_ENABLED", "1")
    reset_achievements()

    assert record_trade_notional(0.99, "paper") == []

    unlocked = record_trade_notional(1.01, "paper")
    assert "paper_first_$1_trade" in unlocked

    state = list_achievements()
    assert "paper_first_$1_trade" in state.get("achievements", {})
