import types
from pathlib import Path

import tal.backtest.engine as engine

from tal.backtest.engine import run_backtest
from tal.league.manager import nightly_eval
from tests.conftest import make_price_df


def test_nightly_eval_allocates(monkeypatch, tmp_path):
    def fake_download(symbol, period="max", interval="1d", auto_adjust=True):
        return make_price_df(n=180)

    monkeypatch.setattr(engine, "yf", types.SimpleNamespace(download=fake_download))

    base = Path("config/base.yaml").read_text()
    base = base.replace("./artifacts", str(tmp_path / "artifacts"))
    base = base.replace(
        "sqlite:///./lab.db", f"sqlite:///{(tmp_path / 'lab.db').as_posix()}"
    )
    base_path = tmp_path / "base.yaml"
    base_path.write_text(base)

    run_backtest(str(base_path))
    run_backtest(str(base_path))

    result = nightly_eval(
        f"sqlite:///{(tmp_path / 'lab.db').as_posix()}",
        str(tmp_path / "artifacts/league"),
        since_days=30,
        top_k=1,
        retire_k=0,
    )

    assert result["promote"]
    assert isinstance(result["allocations"], dict)
    assert (tmp_path / "artifacts/league/allocations.json").exists()
