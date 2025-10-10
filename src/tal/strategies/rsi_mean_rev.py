import pandas as pd
import numpy as np
from tal.strategies.base import Strategy

def _rsi(close: pd.Series, n: int) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    rs = up.rolling(n).mean() / down.rolling(n).mean().replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.bfill().fillna(50)

class RSIMeanReversion(Strategy):
    def __init__(self, rsi_len=14, oversold=30, overbought=70):
        self.rsi_len = rsi_len
        self.oversold = oversold
        self.overbought = overbought

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        rsi = _rsi(df["Close"], self.rsi_len)
        long_sig = (rsi <= self.overbought).astype(int)
        short_sig = (rsi > self.overbought).astype(int) * -1
        sig = long_sig + short_sig
        return sig.reindex(df.index).fillna(0)
