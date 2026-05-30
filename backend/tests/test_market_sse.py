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
    """With an empty cache, the generator yields no events in its first cycle."""
    from app.routers.market import price_event_stream

    # Cache is empty (cleared by fixture)
    gen = price_event_stream()

    # Patch asyncio.sleep to avoid waiting; inject an exception after first sleep
    # to break the infinite loop. We use a sentinel approach:
    # wrap the generator to collect events from the first cycle only.
    import asyncio
    from unittest.mock import patch, AsyncMock

    events_collected = []

    async def run_one_cycle():
        """Drive the generator through exactly one sleep cycle."""
        sleep_called = False

        original_sleep = asyncio.sleep

        async def mock_sleep(delay):
            nonlocal sleep_called
            sleep_called = True
            raise StopAsyncIteration

        with patch("app.routers.market.asyncio") as mock_asyncio:
            mock_asyncio.sleep = mock_sleep
            # Recreate generator with mocked asyncio
            from app.routers.market import price_event_stream as pes
            g = pes()
            try:
                while True:
                    event = await g.__anext__()
                    events_collected.append(event)
            except StopAsyncIteration:
                pass
            finally:
                await g.aclose()

    await run_one_cycle()
    # Empty cache → no events before the sleep
    assert len(events_collected) == 0
