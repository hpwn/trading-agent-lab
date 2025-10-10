"""SQLite helper stubs."""

from __future__ import annotations

from sqlalchemy import create_engine

def get_engine(db_url: str):
    return create_engine(db_url, echo=False, future=True)
