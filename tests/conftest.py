import pandas as pd
import numpy as np


def make_price_df(n=60, start=100.0, step=0.5, up_only=False):
    idx = pd.date_range("2020-01-01", periods=n, freq="D")
    if up_only:
        prices = start * (1 + 0.001) ** np.arange(n)
    else:
        # small random-ish walk but deterministic
        rng = np.linspace(-step, step, num=n)
        prices = start + np.cumsum(rng)
    df = pd.DataFrame({
        "Open": prices,
        "High": prices,
        "Low": prices,
        "Close": prices,
        "Adj Close": prices,
        "Volume": 1,
    }, index=idx)
    return df
