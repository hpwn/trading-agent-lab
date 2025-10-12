from __future__ import annotations

import pytest
from typer.testing import CliRunner

from tal import achievements_badges
from tal.cli import app


@pytest.fixture(name="badge_setup")
def fixture_badge_setup(monkeypatch):
    thresholds = {"notional": [1, 10], "profit": [5]}

    def fake_get_thresholds() -> dict[str, list[float]]:
        return thresholds

    def fake_all_planned() -> list[str]:
        planned: list[str] = []
        data = fake_get_thresholds()
        def fmt(value: float) -> str:
            if float(value).is_integer():
                return str(int(value))
            return f"{value}".rstrip("0").rstrip(".")
        for mode in ("paper", "real"):
            for value in data["notional"]:
                planned.append(f"{mode}_first_${fmt(value)}_trade")
            for value in data["profit"]:
                planned.append(f"{mode}_first_${fmt(value)}_profit")
        return planned

    monkeypatch.setattr(achievements_badges.achievements, "get_thresholds", fake_get_thresholds)
    monkeypatch.setattr(achievements_badges.achievements, "all_planned_badge_keys", fake_all_planned)
    return thresholds


def test_render_badges_line_reflects_unlocks(monkeypatch, badge_setup):
    unlocked_key = "paper_first_$1_trade"
    monkeypatch.setattr(
        achievements_badges.achievements,
        "is_unlocked",
        lambda key: key == unlocked_key,
    )

    line = achievements_badges.render_badges_line(style="flat", label_case="title")
    assert "![Paper $1 Trade]" in line
    assert "-unlocked-success?style=flat" in line
    assert "-locked-lightgrey?style=flat" in line


def test_update_readme_between_markers(tmp_path, badge_setup, monkeypatch):
    monkeypatch.setattr(
        achievements_badges.achievements,
        "is_unlocked",
        lambda key: False,
    )
    badges_line = achievements_badges.render_badges_line()
    readme = tmp_path / "README.md"
    readme.write_text(
        "Intro\n<!-- ACHIEVEMENTS:START -->\nold badges\n<!-- ACHIEVEMENTS:END -->\nOutro\n",
        encoding="utf-8",
    )

    updated = achievements_badges.update_readme(readme, badges_line)

    assert updated is True
    content = readme.read_text(encoding="utf-8")
    assert badges_line in content
    assert "old badges" not in content


def test_cli_badges_stdout(monkeypatch, badge_setup):
    monkeypatch.setattr(
        achievements_badges.achievements,
        "is_unlocked",
        lambda key: False,
    )
    expected_line = achievements_badges.render_badges_line()

    runner = CliRunner()
    result = runner.invoke(app, ["achievements", "badges", "--stdout"])

    assert result.exit_code == 0
    assert result.output.strip() == expected_line
    for token in expected_line.split():
        assert token in result.output
