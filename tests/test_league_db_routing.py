import sqlite3

from tal.league.manager import live_step_all


def test_league_live_respects_orchestrator_db(tmp_path):
    db_path = tmp_path / "orchestrator.db"
    db_url = f"sqlite:///{db_path}"
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    res = live_step_all(db_url, "config/agents", str(artifacts_dir))
    assert isinstance(res, list) and len(res) >= 1

    con = sqlite3.connect(db_path)
    try:
        cur = con.execute("SELECT COUNT(*) FROM runs")
        count = cur.fetchone()[0]
    finally:
        con.close()

    assert count >= 1
