import pandas as pd
import numpy as np
from tal.evaluation.metrics import profit_factor, max_drawdown


def test_profit_factor_basic():
    # +1%, -0.5%, +2%
    r = pd.Series([0.01, -0.005, 0.02])
    pf = profit_factor(r)
    assert pf > 1.0


def test_profit_factor_infinite():
    # all gains => infinite PF
    r = pd.Series([0.01, 0.02, 0.005])
    pf = profit_factor(r)
    assert np.isinf(pf)


def test_max_drawdown():
    eq = pd.Series([1.0, 1.1, 1.05, 1.2, 1.0])
    dd = max_drawdown(eq)
    assert dd <= 0.0
    assert dd <= -0.1  # at least -10%
