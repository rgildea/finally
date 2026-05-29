"""Tests for the watchlist service: in-memory mirror and DB sync."""

import pytest

import app.services.watchlist as watchlist


async def test_load_watchlist_mirrors_db(fake_db, price):
    fake_db.watchlist = ["AAPL", "MSFT"]

    await watchlist.load_watchlist()

    assert watchlist.get_watched_tickers() == ["AAPL", "MSFT"]


async def test_add_ticker_normalizes_and_appends(fake_db, price):
    await watchlist.load_watchlist()

    result = await watchlist.add_ticker(" pypl ")

    assert result == ["PYPL"]
    assert "PYPL" in fake_db.watchlist


async def test_add_duplicate_is_idempotent(fake_db, price):
    fake_db.watchlist = ["AAPL"]
    await watchlist.load_watchlist()

    result = await watchlist.add_ticker("AAPL")

    assert result == ["AAPL"]


async def test_add_empty_raises(fake_db, price):
    await watchlist.load_watchlist()
    with pytest.raises(ValueError):
        await watchlist.add_ticker("   ")


async def test_remove_ticker_drops_from_memory_and_cache(fake_db, price):
    from app.market.cache import price_cache

    fake_db.watchlist = ["AAPL", "MSFT"]
    await watchlist.load_watchlist()
    await price("AAPL", 100.0)

    result = await watchlist.remove_ticker("AAPL")

    assert result == ["MSFT"]
    assert "AAPL" not in fake_db.watchlist
    assert await price_cache.get("AAPL") is None
