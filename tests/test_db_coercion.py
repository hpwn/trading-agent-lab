import uuid
from enum import Enum

from sqlalchemy import text

from tal.storage.db import get_engine, record_order, record_run


class OrderStatus(Enum):
    ACCEPTED = "accepted"


class RunMode(Enum):
    LIVE = "live"


def _build_engine(tmp_path):
    db_path = tmp_path / "lab.db"
    return get_engine(f"sqlite:///{db_path}")


def test_record_order_coerces_uuid_and_enum(tmp_path):
    engine = _build_engine(tmp_path)
    order_id = uuid.uuid4()
    broker_order_id = uuid.uuid4()
    record_order(
        engine,
        {
            "id": order_id,
            "ts": "2024-01-01T00:00:00Z",
            "agent_id": "agent-1",
            "symbol": "SPY",
            "side": "buy",
            "qty": 1,
            "price": 100.0,
            "broker": "alpaca",
            "broker_order_id": broker_order_id,
            "status": OrderStatus.ACCEPTED,
        },
    )

    with engine.connect() as conn:
        row = conn.execute(text("SELECT broker_order_id, status FROM orders"))
        stored = row.fetchone()

    assert stored is not None
    assert stored[0] == str(broker_order_id)
    assert stored[1] == OrderStatus.ACCEPTED.value


def test_record_run_coerces_enum(tmp_path):
    engine = _build_engine(tmp_path)
    run_id = str(uuid.uuid4())
    record_run(
        engine,
        {
            "id": run_id,
            "agent_id": "agent-1",
            "mode": RunMode.LIVE,
            "ts_start": "2024-01-01T00:00:00Z",
            "ts_end": "2024-01-01T00:01:00Z",
            "commit_sha": "deadbeef",
            "config_hash": "cafebabe",
        },
        [],
    )

    with engine.connect() as conn:
        row = conn.execute(text("SELECT mode FROM runs WHERE id = :id"), {"id": run_id})
        stored = row.fetchone()

    assert stored is not None
    assert stored[0] == RunMode.LIVE.value
