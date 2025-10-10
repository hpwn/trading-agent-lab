"""Risk guardrails for position sizing and drawdown control."""

from __future__ import annotations

import pandas as pd

def enforce_drawdown_limit(equity: pd.Series, max_dd_pct: float) -> bool:
    peak = equity.cummax()
    dd = (equity / peak - 1.0).min() * 100
    return dd >= -abs(max_dd_pct)
