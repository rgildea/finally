"""Watchlist service.

Owns the in-memory set of watched tickers that feeds the market polling loop.
``get_watched_tickers`` is synchronous because the polling loop calls it on
every cycle. The DB remains the source of truth; memory is a fast mirror loaded
at startup and kept in sync on add/remove.
"""

from app.db import queries
from app.market.cache import price_cache

# Order-preserving mirror of the DB watchlist. Loaded at startup.
_watched: list[str] = []


def _normalize(ticker: str) -> str:
    return ticker.strip().upper()


async def load_watchlist() -> None:
    """Populate the in-memory watchlist from the database. Called at startup."""
    global _watched
    _watched = await queries.list_watchlist()


def get_watched_tickers() -> list[str]:
    """Return the current watched tickers. Sync — used by the polling loop."""
    return list(_watched)


async def add_ticker(ticker: str) -> list[str]:
    """Add a ticker to the watchlist (DB + memory). Returns the updated list."""
    ticker = _normalize(ticker)
    if not ticker:
        raise ValueError("Ticker must not be empty")
    await queries.add_watchlist(ticker)
    if ticker not in _watched:
        _watched.append(ticker)
    return list(_watched)


async def remove_ticker(ticker: str) -> list[str]:
    """Remove a ticker from the watchlist (DB + memory). Returns updated list."""
    ticker = _normalize(ticker)
    await queries.remove_watchlist(ticker)
    if ticker in _watched:
        _watched.remove(ticker)
    await price_cache.remove(ticker)
    return list(_watched)
