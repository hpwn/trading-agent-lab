from pathlib import Path
import json

from tal.agents.registry import load_agent_config, to_engine_config
from tal.live.wrapper import run_live_once


def test_live_pricing_consistency(tmp_path):
    # copy agent config to tmp and redirect artifacts/DB
    cfg_txt = Path("config/agents/codex_seed.yaml").read_text()
    cfg = tmp_path / "agent.yaml"
    cfg_txt = cfg_txt.replace("./artifacts", str(tmp_path / "artifacts")) \
                     .replace("sqlite:///./lab.db", f"sqlite:///{tmp_path/'lab.db'}")
    cfg.write_text(cfg_txt)

    # load, then force slippage 0 for exact arithmetic
    spec = load_agent_config(str(cfg))
    engine_cfg = to_engine_config(spec)
    engine_cfg.setdefault("live", {})["slippage_bps"] = 0.0
    engine_cfg["live"]["cash"] = 10_000
    engine_cfg.setdefault("strategy", {}).setdefault("params", {})["size_pct"] = 10.0

    # constant price series at 50 → target $1k / $50 = 20 shares
    res = run_live_once(engine_cfg, {"SPY": [50.0] * 200})
    assert res["price"] == 50.0
    assert res["fill"] is not None
    assert res["fill"]["price"] == 50.0     # fill uses the same price used for sizing
    assert res["delta"] == 20.0             # buy 20 shares
    assert res["cash_after"] == 9000.0      # 10k - 20*50 at zero slippage/commission

    # ensure result can serialize cleanly for logging/debugging
    json.dumps(res)
