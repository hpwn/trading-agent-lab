from __future__ import annotations

from tal.achievements import record_profit_dollars, reset_achievements


def test_profit_unlock(monkeypatch, tmp_path):
    achievements_dir = tmp_path / "achievements"
    monkeypatch.setenv("ACHIEVEMENTS_DIR", str(achievements_dir))
    monkeypatch.setenv("ACHIEVEMENTS_ENABLED", "1")
    reset_achievements()

    unlocked = record_profit_dollars(2.2, "paper")
    assert "paper_first_$1_profit" in unlocked
