from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import text
from typer.testing import CliRunner

from tal.cli import app
from tal.storage.db import get_engine


def _insert_order(conn, **kwargs):
    conn.execute(
        text(
            """
            INSERT INTO orders (id, ts, agent_id, symbol, side, qty, price, broker, broker_order_id, status)
            VALUES (:id, :ts, :agent_id, :symbol, :side, :qty, :price, :broker, :broker_order_id, :status)
            """
        ),
        kwargs,
    )


def test_orders_and_ledger_tail(tmp_path):
    db_path = tmp_path / "lab.db"
    db_url = f"sqlite:///{db_path}"
    engine = get_engine(db_url)
    ts = datetime.now(timezone.utc).isoformat()
    with engine.begin() as conn:
        _insert_order(
            conn,
            id="o1",
            ts=ts,
            agent_id="agent-a",
            symbol="SPY",
            side="buy",
            qty=1.0,
            price=5.5,
            broker="alpaca",
            broker_order_id="b1",
            status="filled",
        )
        _insert_order(
            conn,
            id="o2",
            ts=ts,
            agent_id="agent-b",
            symbol="QQQ",
            side="sell",
            qty=2.0,
            price=7.5,
            broker="alpaca",
            broker_order_id="b2",
            status="accepted",
        )

    ledger_path = tmp_path / "trades.csv"
    epoch = int(datetime.now(timezone.utc).timestamp())
    ledger_path.write_text(
        "ts,symbol,side,qty,price\n"
        f"{epoch - 10},SPY,buy,1,5.0\n"
        f"{epoch},QQQ,sell,2,7.0\n"
    )

    runner = CliRunner()
    orders_result = runner.invoke(
        app, ["orders", "tail", "--db", db_url, "--limit", "1"]
    )
    assert orders_result.exit_code == 0
    assert "rowid" in orders_result.stdout
    assert "QQQ" in orders_result.stdout

    ledger_result = runner.invoke(
        app,
        ["ledger", "tail", "--path", str(ledger_path), "--limit", "2"],
    )
    assert ledger_result.exit_code == 0
    assert "epoch" in ledger_result.stdout
    assert "QQQ" in ledger_result.stdout
