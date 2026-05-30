"""SSE price streaming router.

GET /api/stream/prices — streams price_update events from the price_cache singleton
at ~500ms cadence. Each event contains ticker, price, prev_price, change_pct, timestamp.
"""

import asyncio
from collections.abc import AsyncIterable

from fastapi import APIRouter
from fastapi.sse import EventSourceResponse, ServerSentEvent

from app.market.cache import price_cache

router = APIRouter(prefix="/api", tags=["market"])


async def price_event_stream() -> AsyncIterable[ServerSentEvent]:
    """Async generator yielding ServerSentEvent per ticker per cycle.

    Reads exclusively from price_cache.get_all(); never touches the data source.
    Exposed as a named module-level function for direct unit testing.
    """
    while True:
        updates = await price_cache.get_all()
        for ticker, update in updates.items():
            yield ServerSentEvent(data=update.model_dump(), event="price_update")
        await asyncio.sleep(0.5)


@router.get("/stream/prices", response_class=EventSourceResponse)
async def stream_prices() -> AsyncIterable[ServerSentEvent]:
    """Stream live price updates as SSE events."""
    return price_event_stream()
