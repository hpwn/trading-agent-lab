from __future__ import annotations

from typer.testing import CliRunner

from tal.cli import app


class _StubAlpacaClient:
    def __init__(self) -> None:
        self.orders: list[dict[str, object]] = []

    def get_last_price(self, symbol: str) -> float:
        return 5.0

    def is_market_open(self) -> bool:
        return False

    def submit_order(
        self,
        *,
        symbol: str,
        side: str,
        qty: float,
        type: str = "market",
        time_in_force: str = "day",
        limit_price: float | None = None,
        extended_hours: bool | None = None,
    ) -> dict[str, object]:
        self.orders.append(
            {
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "type": type,
                "time_in_force": time_in_force,
                "limit_price": limit_price,
                "extended_hours": extended_hours,
            }
        )
        return {"id": "order-1", "status": "accepted"}

    def get_account(self) -> dict[str, float]:
        return {"cash": 100.0, "equity": 100.0, "buying_power": 100.0}

    def get_position(self, symbol: str) -> float:
        return 0.0


def test_after_hours_env_flag_is_honored(tmp_path, monkeypatch):
    monkeypatch.setenv("ACHIEVEMENTS_DIR", str(tmp_path / "achievements"))
    monkeypatch.setenv("ALLOW_AFTER_HOURS", "1")
    monkeypatch.setenv("ALPACA_API_KEY_ID", "key")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "secret")

    client = _StubAlpacaClient()
    monkeypatch.setattr("tal.cli._build_alpaca_client_from_env", lambda **_: client)
    monkeypatch.setattr("tal.live.wrapper._build_alpaca_client_from_env", lambda **_: client)

    ledger_dir = tmp_path / "artifacts" / "live"
    cfg_path = tmp_path / "alpaca.yaml"
    cfg_path.write_text(
        "\n".join(
            [
                "live:",
                '  adapter: "alpaca"',
                "  paper: true",
                '  symbol: "SPY"',
                "  size_pct: 5",
                "  slippage_bps: 5",
                "  max_order_usd: 5",
                "  max_position_pct: 10",
                "  max_daily_loss_pct: 2",
                f'  ledger_dir: "{ledger_dir.as_posix()}"',
                "storage:",
                f'  db_url: "sqlite:///{(tmp_path / "lab.db").as_posix()}"',
            ]
        )
        + "\n"
    )

    runner = CliRunner()
    result = runner.invoke(app, ["live", "--config", str(cfg_path)])

    assert result.exit_code == 0, result.stdout
    assert client.orders, "expected at least one order submission"
    assert client.orders[0]["extended_hours"] is True
    assert client.orders[0]["type"] == "limit"
    assert client.orders[0]["limit_price"] is not None
