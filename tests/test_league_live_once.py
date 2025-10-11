from pathlib import Path

from tal.league.manager import live_step_all


def test_league_live_writes_per_agent_ledgers(tmp_path):
    base = Path("config/base.yaml").read_text()
    base = base.replace("./artifacts", str(tmp_path / "artifacts"))
    base = base.replace(
        "sqlite:///./lab.db", f"sqlite:///{(tmp_path / 'lab.db').as_posix()}"
    )
    config_path = tmp_path / "base.yaml"
    config_path.write_text(base)

    results = live_step_all(
        f"sqlite:///{(tmp_path / 'lab.db').as_posix()}",
        "config/agents",
        str(tmp_path / "artifacts/league"),
    )
    assert isinstance(results, list)
    assert results
    for row in results:
        ledger = tmp_path / "artifacts/league/live" / row["agent_id"] / "trades.csv"
        assert ledger.exists()
    assert (tmp_path / "artifacts/league/last_live.json").exists()
