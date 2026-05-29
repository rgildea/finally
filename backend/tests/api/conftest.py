"""Fixtures for API tests.

Runs the app against a temporary SQLite database and the in-process simulator
(no network). The lifespan starts real background tasks; tests seed prices
directly into the cache so trade and watchlist endpoints behave deterministically.
"""

import importlib

import pytest
from fastapi.testclient import TestClient

from app.market.interface import PriceUpdate


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Yield a TestClient backed by a fresh temp DB and the simulator."""
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("FINALLY_DB_PATH", str(db_file))
    monkeypatch.setenv("MASSIVE_API_KEY", "")
    monkeypatch.setenv("LLM_MOCK", "true")

    # Re-import config and modules that captured config values at import time.
    import app.config

    importlib.reload(app.config)
    import app.db.connection

    importlib.reload(app.db.connection)
    import app.db

    importlib.reload(app.db)

    from app.market.cache import price_cache

    price_cache._data.clear()

    import app.main

    importlib.reload(app.main)

    with TestClient(app.main.app) as c:
        yield c

    price_cache._data.clear()


@pytest.fixture
def seed_price():
    """Return a helper that writes a price into the shared cache synchronously."""
    from app.market.cache import price_cache

    def _seed(ticker: str, value: float, prev: float | None = None) -> None:
        price_cache._data[ticker] = PriceUpdate(
            ticker=ticker,
            price=value,
            prev_price=prev if prev is not None else value,
            timestamp="2026-05-28T00:00:00.000Z",
        )

    return _seed
