"""Data ingestion stubs for future extension (e.g., yfinance batch jobs)."""

from __future__ import annotations

import pandas as pd

def fetch_daily_bars(symbol: str, lookback: int) -> pd.DataFrame:
    """Placeholder for scheduled ingestion jobs."""
    raise NotImplementedError("Ingestion pipeline not yet implemented")
