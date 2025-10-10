"""Utility helpers for working with OHLCV bars."""

from __future__ import annotations

import pandas as pd

def validate_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    required = {"Open", "High", "Low", "Close", "Volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")
    return df
