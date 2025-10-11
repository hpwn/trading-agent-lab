from pathlib import Path

from tal.agents.registry import load_agent_config, to_engine_config
from tal.live.wrapper import run_live_once
from tal.storage.db import Engine


def test_agent_provenance_upsert(tmp_path):
    cfg_text = Path("config/agents/codex_seed.yaml").read_text()
    cfg_text = cfg_text.replace("./artifacts", str(tmp_path / "artifacts"))
    cfg_text = cfg_text.replace(
        "sqlite:///./lab.db", f"sqlite:///{(tmp_path / 'lab.db').as_posix()}"
    )
    cfg_path = tmp_path / "agent.yaml"
    cfg_path.write_text(cfg_text)

    spec = load_agent_config(str(cfg_path))
    engine_cfg = to_engine_config(spec)

    run_live_once(engine_cfg, {"SPY": [100.0] * 200})

    db = Engine(f"sqlite:///{(tmp_path / 'lab.db').as_posix()}")
    rows = db.query("SELECT agent_id, builder_name FROM agents")
    assert rows, "Expected agent provenance row"
    assert rows[0][0] == engine_cfg["agent"]["id"]
