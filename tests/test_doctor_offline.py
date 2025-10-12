from typer.testing import CliRunner

from tal.cli import app


class _FakeClient:
    def is_market_open(self) -> bool:
        return True

    def get_account(self) -> dict:
        return {"cash": 1000.0, "equity": 1500.0, "buying_power": 1200.0}

    def get_last_price(self, symbol: str) -> float:
        assert symbol == "SPY"
        return 123.45


def test_doctor_alpaca_happy_path(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY_ID", "key")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "secret")

    monkeypatch.setattr(
        "tal.cli._build_alpaca_client_from_env",
        lambda **_: _FakeClient(),
    )

    runner = CliRunner()
    result = runner.invoke(app, ["doctor", "alpaca", "--symbol", "SPY"])

    assert result.exit_code == 0, result.stdout
    stdout = result.stdout
    assert "market_open: True" in stdout
    assert "account: cash=1000.00 equity=1500.00 buying_power=1200.00" in stdout
    assert "latest_price[SPY]: 123.45" in stdout
