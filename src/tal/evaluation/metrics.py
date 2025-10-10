"""Key performance indicator utilities."""

from __future__ import annotations

import math
from typing import Dict

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def profit_factor(returns: pd.Series) -> float:
    """Return the ratio of gross gains to gross losses."""

    gains = returns.clip(lower=0).sum()
    losses = -returns.clip(upper=0).sum()
    if np.isclose(losses, 0.0):
        return float("inf") if gains > 0 else 0.0
    return float(gains / losses)


def max_drawdown(equity: pd.Series) -> float:
    """Return the maximum peak-to-trough drawdown as a negative number."""

    if equity.empty:
        return 0.0
    roll_max = equity.cummax()
    dd = equity / roll_max - 1.0
    return float(dd.min())


def sharpe_ratio(returns: pd.Series) -> float:
    """Return the annualised Sharpe ratio using daily returns."""

    if returns.empty:
        return 0.0
    mean = returns.mean()
    std = returns.std(ddof=0)
    if np.isclose(std, 0.0):
        return 0.0
    return float((mean / std) * math.sqrt(TRADING_DAYS))


def win_rate(returns: pd.Series) -> float:
    """Return the percentage of winning periods."""

    if returns.empty:
        return 0.0
    wins = (returns > 0).sum()
    losses = (returns < 0).sum()
    total = wins + losses
    if total == 0:
        return 0.0
    return float(wins / total)


def compute_kpis(returns: pd.Series, equity: pd.Series) -> Dict[str, float]:
    """Compute the canonical Trading Agent Lab KPI set."""

    pnl = float(equity.iloc[-1] - 1.0) if not equity.empty else 0.0
    return {
        "pnl": pnl,
        "profit_factor": profit_factor(returns),
        "sharpe": sharpe_ratio(returns),
        "max_dd": max_drawdown(equity),
        "win_rate": win_rate(returns),
    }
