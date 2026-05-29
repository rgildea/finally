"""SSE price stream endpoint.

Pushes the latest cached price for every watched ticker on a fixed cadence.
The frontend consumes this with the native ``EventSource`` API.
"""

import asyncio
import json

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from app.config import POLL_INTERVAL_SECONDS
from app.market.cache import price_cache
from app.services.watchlist import get_watched_tickers

router = APIRouter()


async def _price_events(request: Request):
    """Yield an SSE event per watched ticker each cycle until the client leaves."""
    while True:
        if await request.is_disconnected():
            break
        prices = await price_cache.get_many(get_watched_tickers())
        for ticker, update in prices.items():
            yield {
                "event": "price",
                "data": json.dumps(
                    {
                        "ticker": ticker,
                        "price": update.price,
                        "prev_price": update.prev_price,
                        "change_pct": update.change_pct,
                        "timestamp": update.timestamp,
                    }
                ),
            }
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


@router.get("/api/stream/prices")
async def stream_prices(request: Request) -> EventSourceResponse:
    """Open a long-lived SSE connection streaming live price updates."""
    return EventSourceResponse(_price_events(request))
