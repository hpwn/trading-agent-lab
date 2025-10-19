from tal.live.base import Fill
from tal.live.wrapper import LiveCfg, _RuntimeContext, _record_fill


def test_record_fill_skips_db_when_execute_disabled(tmp_path, monkeypatch):
    trades_path = tmp_path / "trades.csv"
    trades_path.write_text("ts,symbol,side,qty,price\n", encoding="utf-8")

    live_cfg = LiveCfg(**{"adapter": "sim", "ledger_dir": str(tmp_path), "execute": False})
    context = _RuntimeContext(
        engine_cfg={},
        live_cfg=live_cfg,
        symbols=["SPY"],
        trades_path=trades_path,
        db_engine=object(),
        agent_id="agent-1",
        mode="live",
    )

    def _fail(*_args, **_kwargs):  # pragma: no cover - ensures guard works
        raise AssertionError("record_order should not be called when execute is disabled")

    monkeypatch.setattr("tal.live.wrapper.record_order", _fail)
    monkeypatch.setattr("tal.live.wrapper.record_trade_notional", lambda *args, **kwargs: [])

    fill = Fill(symbol="SPY", side="buy", qty=1.0, price=100.0, status="accepted", broker_order_id="abc")
    _record_fill(context, fill, trades_path, run_id="run-1")

    contents = trades_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(contents) == 2
    fields = contents[-1].split(",")
    assert fields[1] == "SPY"
