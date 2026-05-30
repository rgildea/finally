"""Unit tests for the SSE price streaming generator.

Tests call the generator directly (not via HTTP) to avoid the infinite-stream
hang documented in research Pitfall 1.
"""

import pytest

from app.market.cache import PriceCache, price_cache
from app.market.interface import PriceUpdate


@pytest.fixture(autouse=True)
async def clear_cache():
    """Reset the global price_cache before each test."""
    async with price_cache._lock:
        price_cache._data.clear()
    yield
    async with price_cache._lock:
        price_cache._data.clear()


def _make_update(ticker: str, price: float, prev_price: float) -> PriceUpdate:
    return PriceUpdate(
        ticker=ticker,
        price=price,
        prev_price=prev_price,
        timestamp="2024-01-15T14:30:00.000Z",
    )


async def test_sse_event_fields():
    """SSE event data contains all five required keys."""
    from app.routers.market import price_event_stream

    await price_cache.update("AAPL", _make_update("AAPL", 190.0, 189.0))
    gen = price_event_stream()
    event = await gen.__anext__()
    await gen.aclose()

    assert isinstance(event.data, dict)
    for key in ("ticker", "price", "prev_price", "change_pct", "timestamp"):
        assert key in event.data, f"Missing key: {key}"


async def test_sse_event_value():
    """SSE event data values match the cached PriceUpdate."""
    from app.routers.market import price_event_stream

    await price_cache.update("AAPL", _make_update("AAPL", 190.0, 189.0))
    gen = price_event_stream()
    event = await gen.__anext__()
    await gen.aclose()

    assert event.data["ticker"] == "AAPL"
    assert event.data["price"] == 190.0


async def test_sse_reads_cache():
    """With an empty cache, the generator yields no events in its first cycle.

    Verifies the generator reads from price_cache.get_all() rather than any
    external data source. We drive it through one cycle by replacing asyncio.sleep
    with a coroutine that raises CancelledError to terminate the loop.
    """
    import asyncio
    from unittest.mock import patch

    from app.routers.market import price_event_stream

    events_collected = []

    async def mock_sleep(_delay):
        raise asyncio.CancelledError

    with patch("app.routers.market.asyncio.sleep", side_effect=mock_sleep):
        g = price_event_stream()
        try:
            async for event in g:
                events_collected.append(event)
        except asyncio.CancelledError:
            pass
        finally:
            await g.aclose()

    # Empty cache → no events yielded before the sleep (which was the first cycle)
    assert len(events_collected) == 0
