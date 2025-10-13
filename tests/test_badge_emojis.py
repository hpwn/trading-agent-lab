from __future__ import annotations

from tal import achievements, achievements_badges


def test_badge_labels_include_emojis(monkeypatch, tmp_path):
    monkeypatch.setenv("ACHIEVEMENTS_DIR", str(tmp_path / "achievements"))
    achievements.reset_achievements()
    achievements.record_trade_notional(5.0, "paper")

    badges_line = achievements_badges.render_badges_line()

    assert "🔓" in badges_line
    assert "🔒" in badges_line
