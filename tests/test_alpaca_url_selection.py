from tal.live.wrapper import _select_alpaca_urls


def test_default_paper_urls():
    trade, data = _select_alpaca_urls(paper=True, trading_env=None, data_env=None)
    assert trade == "https://paper-api.alpaca.markets"
    assert data == "https://data.alpaca.markets"


def test_default_live_urls():
    trade, data = _select_alpaca_urls(paper=False, trading_env=None, data_env=None)
    assert trade == "https://api.alpaca.markets"
    assert data == "https://data.alpaca.markets"


def test_env_overrides_trading_only():
    trade, data = _select_alpaca_urls(
        paper=True,
        trading_env="https://custom-trade",
        data_env=None,
    )
    assert trade == "https://custom-trade"
    assert data == "https://data.alpaca.markets"


def test_env_overrides_data_when_requested():
    trade, data = _select_alpaca_urls(
        paper=True,
        trading_env=None,
        data_env="https://custom-data",
    )
    assert trade == "https://paper-api.alpaca.markets"
    assert data == "https://custom-data"
