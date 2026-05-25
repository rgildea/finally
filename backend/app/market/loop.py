import asyncio
import logging
from collections.abc import Callable

import httpx

from .cache import price_cache
from .interface import MarketDataSource, PriceUpdate

logger = logging.getLogger(__name__)


async def polling_loop(
    source: MarketDataSource,
    get_tickers: Callable[[], list[str]],
    interval_seconds: float,
) -> None:
    """
    Continuously poll the market data source and update the price cache.

    Args:
        source:           The active MarketDataSource (simulator or Massive client).
        get_tickers:      Callable returning the current watchlist tickers.
                          Called on every cycle so newly added tickers are picked up
                          without restarting the loop or touching the data source.
        interval_seconds: Seconds between polls.
                          Simulator: 0.5  (matches simulation tick rate)
                          Massive free: 15.0  (Starter+: 5.0, Advanced+: 1.0)
    """
    while True:
        try:
            tickers = get_tickers()
            if tickers:
                updates = await source.get_prices(tickers)
                merged = await _merge_with_prev(updates)
                await price_cache.update_many(merged)
        except asyncio.CancelledError:
            raise
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                logger.warning("Massive API rate limited — backing off 60s")
                await asyncio.sleep(60)
                continue
            logger.error(
                "Massive API HTTP %d in polling loop — will retry",
                e.response.status_code,
            )
        except Exception:
            logger.exception("Error in polling loop — will retry next cycle")
        await asyncio.sleep(interval_seconds)


async def _merge_with_prev(
    updates: dict[str, PriceUpdate],
) -> dict[str, PriceUpdate]:
    """
    Attach the previously cached price to each new update so change_pct is
    accurate on the next SSE push.

    If a ticker has no prior cache entry (first poll), prev_price equals the
    current price — change_pct will be 0.0, which is correct.
    """
    cached = await price_cache.get_all()
    result: dict[str, PriceUpdate] = {}
    for ticker, update in updates.items():
        prev = cached.get(ticker)
        result[ticker] = PriceUpdate(
            ticker=ticker,
            price=update.price,
            prev_price=prev.price if prev else update.price,
            timestamp=update.timestamp,
        )
    return result
