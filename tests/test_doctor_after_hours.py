from __future__ import annotations

from typer.testing import CliRunner

from tal.cli import app


class _StubClient:
    def is_market_open(self) -> bool:
        return False

    def get_account(self) -> dict:
        return {"cash": 0.0, "equity": 0.0, "buying_power": 0.0}

    def get_last_price(self, symbol: str) -> float:
        return 0.0


def test_doctor_reports_after_hours_flag(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY_ID", "key")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "secret")
    monkeypatch.setenv("ALLOW_AFTER_HOURS", "1")

    monkeypatch.setattr(
        "tal.cli._build_alpaca_client_from_env",
        lambda **_: _StubClient(),
    )

    runner = CliRunner()
    result = runner.invoke(app, ["doctor", "alpaca"])

    assert result.exit_code == 0, result.stdout
    assert "allow_after_hours: True" in result.stdout
