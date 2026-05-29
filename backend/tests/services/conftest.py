"""Shared fixtures for service tests.

Services depend on ``app.db.queries`` and the market price cache. These fixtures
provide an in-memory fake of the queries module and a populated price cache so
service logic can be tested without a real database or live market feed.
"""

import pytest

from app.market.interface import PriceUpdate


class FakeQueries:
    """In-memory stand-in for ``app.db.queries`` with matching async signatures."""

    def __init__(self) -> None:
        self.cash = 10000.0
        self.positions: dict[str, dict] = {}
        self.watchlist: list[str] = []
        self.trades: list[dict] = []
        self.snapshots: list[dict] = []

    async def get_profile(self) -> dict:
        return {"cash_balance": self.cash}

    async def set_cash_balance(self, balance: float) -> None:
        self.cash = balance

    async def list_watchlist(self) -> list[str]:
        return list(self.watchlist)

    async def add_watchlist(self, ticker: str) -> None:
        if ticker not in self.watchlist:
            self.watchlist.append(ticker)

    async def remove_watchlist(self, ticker: str) -> None:
        if ticker in self.watchlist:
            self.watchlist.remove(ticker)

    async def list_positions(self) -> list[dict]:
        return [dict(p) for p in self.positions.values()]

    async def get_position(self, ticker: str) -> dict | None:
        pos = self.positions.get(ticker)
        return dict(pos) if pos else None

    async def upsert_position(
        self, ticker: str, quantity: float, avg_cost: float
    ) -> None:
        self.positions[ticker] = {
            "ticker": ticker,
            "quantity": quantity,
            "avg_cost": avg_cost,
        }

    async def delete_position(self, ticker: str) -> None:
        self.positions.pop(ticker, None)

    async def insert_trade(self, ticker, side, quantity, price) -> dict:
        row = {
            "ticker": ticker,
            "side": side,
            "quantity": quantity,
            "price": price,
        }
        self.trades.append(row)
        return row

    async def insert_snapshot(self, total_value: float) -> None:
        self.snapshots.append({"total_value": total_value})


@pytest.fixture
def fake_db(monkeypatch):
    """Patch every service module's ``queries`` reference to a shared fake."""
    fake = FakeQueries()
    import app.services.portfolio as portfolio
    import app.services.trading as trading
    import app.services.watchlist as watchlist

    monkeypatch.setattr(trading, "queries", fake)
    monkeypatch.setattr(portfolio, "queries", fake)
    monkeypatch.setattr(watchlist, "queries", fake)
    return fake


@pytest.fixture
async def price(monkeypatch):
    """Reset the shared price cache and return a helper to seed prices."""
    from app.market.cache import price_cache

    price_cache._data.clear()

    async def set_price(ticker: str, value: float, prev: float | None = None) -> None:
        await price_cache.update(
            ticker,
            PriceUpdate(
                ticker=ticker,
                price=value,
                prev_price=prev if prev is not None else value,
                timestamp="2026-05-28T00:00:00.000Z",
            ),
        )

    yield set_price
    price_cache._data.clear()
