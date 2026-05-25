from datetime import datetime, timezone

import pytest

from app.market.cache import PriceCache
from app.market.interface import PriceUpdate


def make_update(ticker: str, price: float, prev: float | None = None) -> PriceUpdate:
    return PriceUpdate(
        ticker=ticker,
        price=price,
        prev_price=prev if prev is not None else price,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@pytest.mark.asyncio
async def test_update_and_get():
    cache = PriceCache()
    u = make_update("AAPL", 190.0)
    await cache.update("AAPL", u)
    result = await cache.get("AAPL")
    assert result is not None
    assert result.price == 190.0


@pytest.mark.asyncio
async def test_get_missing_ticker_returns_none():
    cache = PriceCache()
    assert await cache.get("ZZZZ") is None


@pytest.mark.asyncio
async def test_update_many_atomic():
    cache = PriceCache()
    updates = {
        "AAPL": make_update("AAPL", 190.0),
        "MSFT": make_update("MSFT", 420.0),
    }
    await cache.update_many(updates)
    all_prices = await cache.get_all()
    assert set(all_prices.keys()) == {"AAPL", "MSFT"}


@pytest.mark.asyncio
async def test_get_many_returns_requested():
    cache = PriceCache()
    await cache.update("AAPL", make_update("AAPL", 190.0))
    await cache.update("MSFT", make_update("MSFT", 420.0))
    result = await cache.get_many(["AAPL", "MSFT"])
    assert set(result.keys()) == {"AAPL", "MSFT"}


@pytest.mark.asyncio
async def test_get_many_omits_missing():
    cache = PriceCache()
    await cache.update("AAPL", make_update("AAPL", 190.0))
    result = await cache.get_many(["AAPL", "ZZZZ"])
    assert "AAPL" in result
    assert "ZZZZ" not in result


@pytest.mark.asyncio
async def test_remove():
    cache = PriceCache()
    await cache.update("AAPL", make_update("AAPL", 190.0))
    await cache.remove("AAPL")
    assert await cache.get("AAPL") is None


@pytest.mark.asyncio
async def test_remove_nonexistent_is_safe():
    cache = PriceCache()
    await cache.remove("ZZZZ")  # should not raise


@pytest.mark.asyncio
async def test_get_all_returns_copy():
    """Mutating the returned dict should not affect the cache."""
    cache = PriceCache()
    await cache.update("AAPL", make_update("AAPL", 190.0))
    snapshot = await cache.get_all()
    snapshot["FAKE"] = make_update("FAKE", 1.0)
    assert "FAKE" not in (await cache.get_all())


@pytest.mark.asyncio
async def test_update_overwrites_previous():
    cache = PriceCache()
    await cache.update("AAPL", make_update("AAPL", 190.0))
    await cache.update("AAPL", make_update("AAPL", 195.0))
    result = await cache.get("AAPL")
    assert result is not None
    assert result.price == 195.0


@pytest.mark.asyncio
async def test_get_all_empty_cache():
    cache = PriceCache()
    result = await cache.get_all()
    assert result == {}
