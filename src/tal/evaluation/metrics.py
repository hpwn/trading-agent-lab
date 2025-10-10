import numpy as np, pandas as pd

def profit_factor(returns: pd.Series) -> float:
    gains = returns.clip(lower=0).sum()
    losses = -returns.clip(upper=0).sum()
    return np.inf if losses == 0 else gains / losses

def max_drawdown(equity: pd.Series) -> float:
    roll_max = equity.cummax()
    dd = equity/roll_max - 1.0
    return dd.min()
