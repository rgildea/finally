import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.market import cache as cache_module
from app.market.interface import PriceUpdate
from app.market.loop import _merge_with_prev, polling_loop


def make_update(ticker: str, price: float) -> PriceUpdate:
    return PriceUpdate(
        ticker=ticker,
        price=price,
        prev_price=price,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@pytest.fixture(autouse=True)
def clear_global_cache():
    """Reset the module-level price_cache before each test."""
    cache_module.price_cache._data.clear()
    yield
    cache_module.price_cache._data.clear()


@pytest.mark.asyncio
async def test_merge_with_prev_first_poll():
    """On first poll there is no prev — prev_price should equal current price."""
    updates = {"AAPL": make_update("AAPL", 190.0)}
    merged = await _merge_with_prev(updates)
    assert merged["AAPL"].prev_price == 190.0
    assert merged["AAPL"].change_pct == 0.0


@pytest.mark.asyncio
async def test_merge_with_prev_subsequent_poll():
    """Second poll should attach the previous cached price."""
    await cache_module.price_cache.update("AAPL", make_update("AAPL", 190.0))

    updates = {"AAPL": make_update("AAPL", 191.0)}
    merged = await _merge_with_prev(updates)
    assert merged["AAPL"].prev_price == 190.0
    assert merged["AAPL"].price == 191.0
    assert abs(merged["AAPL"].change_pct - (1.0 / 190.0 * 100)) < 0.001


@pytest.mark.asyncio
async def test_merge_with_prev_multiple_tickers():
    """prev_price is attached independently per ticker."""
    await cache_module.price_cache.update("AAPL", make_update("AAPL", 190.0))
    await cache_module.price_cache.update("MSFT", make_update("MSFT", 420.0))

    updates = {
        "AAPL": make_update("AAPL", 192.0),
        "MSFT": make_update("MSFT", 418.0),
        "NVDA": make_update("NVDA", 875.0),  # no prior cache entry
    }
    merged = await _merge_with_prev(updates)

    assert merged["AAPL"].prev_price == 190.0
    assert merged["MSFT"].prev_price == 420.0
    assert merged["NVDA"].prev_price == 875.0  # equals current price — first poll


@pytest.mark.asyncio
async def test_polling_loop_calls_source_and_updates_cache():
    """polling_loop should call get_prices and write results to the cache."""
    mock_source = MagicMock()
    mock_source.get_prices = AsyncMock(return_value={
        "AAPL": make_update("AAPL", 191.0),
    })

    call_count = 0

    def get_tickers():
        nonlocal call_count
        call_count += 1
        return ["AAPL"]

    task = asyncio.create_task(
        polling_loop(mock_source, get_tickers, interval_seconds=0.05)
    )
    await asyncio.sleep(0.12)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert call_count >= 2
    assert mock_source.get_prices.call_count >= 2
    cached = await cache_module.price_cache.get("AAPL")
    assert cached is not None
    assert cached.price == 191.0


@pytest.mark.asyncio
async def test_polling_loop_skips_empty_ticker_list():
    """When get_tickers returns [], get_prices should not be called."""
    mock_source = MagicMock()
    mock_source.get_prices = AsyncMock()

    task = asyncio.create_task(
        polling_loop(mock_source, lambda: [], interval_seconds=0.05)
    )
    await asyncio.sleep(0.12)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    mock_source.get_prices.assert_not_called()


@pytest.mark.asyncio
async def test_polling_loop_survives_source_exception():
    """An exception from get_prices should not crash the loop."""
    call_count = 0
    mock_source = MagicMock()

    async def flaky_get_prices(tickers):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("transient error")
        return {"AAPL": make_update("AAPL", 190.0)}

    mock_source.get_prices = flaky_get_prices

    task = asyncio.create_task(
        polling_loop(mock_source, lambda: ["AAPL"], interval_seconds=0.05)
    )
    await asyncio.sleep(0.15)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert call_count >= 2
    cached = await cache_module.price_cache.get("AAPL")
    assert cached is not None


@pytest.mark.asyncio
async def test_polling_loop_backs_off_60s_on_429():
    """A 429 response should trigger a 60-second back-off, not the normal interval."""
    sleep_calls: list[float] = []
    real_sleep = asyncio.sleep

    async def capturing_sleep(delay: float) -> None:
        sleep_calls.append(delay)
        # Use a tiny real sleep so the loop actually yields
        await real_sleep(0)

    mock_source = MagicMock()

    async def rate_limited_get_prices(tickers):
        request = httpx.Request("GET", "https://api.massive.com/v2/snapshot")
        response = httpx.Response(429, request=request)
        raise httpx.HTTPStatusError("429 Too Many Requests", request=request, response=response)

    mock_source.get_prices = rate_limited_get_prices

    task = asyncio.create_task(
        polling_loop(mock_source, lambda: ["AAPL"], interval_seconds=0.05)
    )

    # Monkeypatch asyncio.sleep inside the loop module for the duration of this test
    import app.market.loop as loop_module
    original_sleep = asyncio.sleep
    loop_module_sleep_target = loop_module

    # We run the loop briefly; the first 429 should trigger a 60s back-off sleep call.
    # We cancel before the actual 60s elapses — we only check what value was passed.
    import unittest.mock
    with unittest.mock.patch("asyncio.sleep", side_effect=capturing_sleep):
        task = asyncio.create_task(
            polling_loop(mock_source, lambda: ["AAPL"], interval_seconds=0.05)
        )
        await real_sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    # The 429 back-off sleep should have been called with 60 seconds
    assert 60 in sleep_calls, f"Expected 60s back-off sleep, got: {sleep_calls}"
