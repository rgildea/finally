# Market Data Interface

This document defines the unified Python interface for market data in FinAlly. All downstream code — the SSE endpoint, portfolio calculations, and trade execution — is completely agnostic to whether prices come from the Massive API or the built-in simulator.

**Related docs:**
- `MASSIVE_API.md` — Massive REST API reference and response schemas
- `MARKET_SIMULATOR.md` — GBM simulator design and code structure

---

## Module Layout

```
backend/app/market/
├── __init__.py       # Re-exports: MarketDataSource, PriceUpdate, PriceCache, create_market_data_source
├── interface.py      # Abstract base class + PriceUpdate model
├── cache.py          # PriceCache singleton
├── loop.py           # Background polling task
├── simulator.py      # MarketSimulator implementation
└── massive.py        # MassiveAPIClient implementation
```

---

## Data Model

### `PriceUpdate`

The canonical price event passed between all components.

```python
# market/interface.py
from pydantic import BaseModel, computed_field

class PriceUpdate(BaseModel):
    ticker: str
    price: float
    prev_price: float
    timestamp: str       # ISO 8601 UTC, e.g. "2024-01-15T14:30:00.000Z"

    @computed_field
    @property
    def change_pct(self) -> float:
        """Percentage change from prev_price to price."""
        if self.prev_price == 0:
            return 0.0
        return (self.price - self.prev_price) / self.prev_price * 100
```

`prev_price` is the price from the previous poll cycle, stored in `PriceCache`. Each new poll computes the delta against the cached value — so `change_pct` is the per-tick move, not the daily change.

---

## Abstract Interface

### `MarketDataSource`

Both `MarketSimulator` and `MassiveAPIClient` implement this protocol.

```python
# market/interface.py
from abc import ABC, abstractmethod

class MarketDataSource(ABC):
    @abstractmethod
    async def start(self) -> None:
        """
        Start the data source. Called once at application startup.
        For the simulator: launches the background GBM loop.
        For Massive: validates the API key with a test request.
        """

    @abstractmethod
    async def stop(self) -> None:
        """
        Stop the data source. Called at application shutdown.
        Must be safe to call even if start() was never called.
        """

    @abstractmethod
    async def get_prices(self, tickers: list[str]) -> dict[str, PriceUpdate]:
        """
        Return the latest price for each requested ticker.

        Args:
            tickers: List of uppercase ticker symbols (e.g. ["AAPL", "MSFT"]).

        Returns:
            Dict mapping ticker to PriceUpdate. Tickers with no data are omitted
            (not raised as errors — the caller handles missing tickers gracefully).

        Raises:
            httpx.HTTPStatusError: On Massive API errors (non-2xx response).
            asyncio.TimeoutError: If the request exceeds the configured timeout.
        """
```

---

## Price Cache

A singleton in-memory store for the latest price of each ticker. Written by the polling loop; read by the SSE endpoint.

```python
# market/cache.py
import asyncio
from .interface import PriceUpdate


class PriceCache:
    """
    Thread-safe in-memory store for the latest PriceUpdate per ticker.
    Uses an asyncio.Lock since all access is from async code.
    """

    def __init__(self) -> None:
        self._data: dict[str, PriceUpdate] = {}
        self._lock = asyncio.Lock()

    async def update(self, ticker: str, update: PriceUpdate) -> None:
        """Store the latest price for a ticker."""
        async with self._lock:
            self._data[ticker] = update

    async def update_many(self, updates: dict[str, PriceUpdate]) -> None:
        """Store multiple updates atomically."""
        async with self._lock:
            self._data.update(updates)

    async def get(self, ticker: str) -> PriceUpdate | None:
        """Return the latest price for a ticker, or None if not cached."""
        async with self._lock:
            return self._data.get(ticker)

    async def get_many(self, tickers: list[str]) -> dict[str, PriceUpdate]:
        """Return prices for the requested tickers. Missing tickers are omitted."""
        async with self._lock:
            return {t: self._data[t] for t in tickers if t in self._data}

    async def get_all(self) -> dict[str, PriceUpdate]:
        """Return all cached prices."""
        async with self._lock:
            return dict(self._data)


# Module-level singleton — imported directly by the polling loop and SSE endpoint
price_cache = PriceCache()
```

---

## Background Polling Loop

A single asyncio task that drives the data source and writes to the cache. Runs from FastAPI startup to shutdown.

```python
# market/loop.py
import asyncio
import logging
from .interface import MarketDataSource, PriceUpdate
from .cache import price_cache

logger = logging.getLogger(__name__)


async def polling_loop(
    source: MarketDataSource,
    get_tickers: Callable[[], list[str]],
    interval_seconds: float,
) -> None:
    """
    Continuously poll the market data source and update the price cache.

    Args:
        source: The active MarketDataSource (simulator or Massive client).
        get_tickers: Callable that returns the current watchlist tickers.
                     Called each cycle so newly added tickers are picked up.
        interval_seconds: Seconds between polls (0.5 for simulator, 15 for free Massive tier).
    """
    while True:
        try:
            tickers = get_tickers()
            if tickers:
                updates = await source.get_prices(tickers)
                # Merge with cached prev_price so change_pct reflects tick delta
                merged = _merge_with_prev(updates, await price_cache.get_all())
                await price_cache.update_many(merged)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Error in polling loop")
        await asyncio.sleep(interval_seconds)


def _merge_with_prev(
    updates: dict[str, PriceUpdate],
    cached: dict[str, PriceUpdate],
) -> dict[str, PriceUpdate]:
    """
    Attach the previous cached price to each new update so change_pct is accurate.
    If a ticker has no previous cache entry, prev_price equals the current price.
    """
    result = {}
    for ticker, update in updates.items():
        prev = cached.get(ticker)
        result[ticker] = PriceUpdate(
            ticker=ticker,
            price=update.price,
            prev_price=prev.price if prev else update.price,
            timestamp=update.timestamp,
        )
    return result
```

---

## Massive API Client

Wraps the Massive REST snapshot endpoint into the `MarketDataSource` interface.

```python
# market/massive.py
import httpx
import logging
from datetime import datetime, timezone
from .interface import MarketDataSource, PriceUpdate

logger = logging.getLogger(__name__)

MASSIVE_BASE_URL = "https://api.massive.com"


class MassiveAPIClient(MarketDataSource):
    """
    Fetches real stock prices from the Massive REST API.
    Uses the /v2/snapshot endpoint for bulk multi-ticker fetching.
    See MASSIVE_API.md for endpoint details and response schema.
    """

    def __init__(self, api_key: str, base_url: str = MASSIVE_BASE_URL) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        self._client = httpx.AsyncClient(timeout=10.0)
        logger.info("Massive API client started (base_url=%s)", self._base_url)

    async def stop(self) -> None:
        if self._client:
            await self._client.aclose()
        logger.info("Massive API client stopped")

    async def get_prices(self, tickers: list[str]) -> dict[str, PriceUpdate]:
        if not self._client:
            raise RuntimeError("MassiveAPIClient.start() not called")

        params = {
            "tickers": ",".join(tickers),
            "apiKey": self._api_key,
        }
        response = await self._client.get(
            f"{self._base_url}/v2/snapshot/locale/us/markets/stocks/tickers",
            params=params,
        )
        response.raise_for_status()
        data = response.json()

        now = datetime.now(timezone.utc).isoformat()
        result = {}
        for item in data.get("tickers", []):
            ticker = item["ticker"]
            # lastTrade.p is the most current price; fall back to day.c
            price = (
                item.get("lastTrade", {}).get("p")
                or item.get("day", {}).get("c")
                or 0.0
            )
            result[ticker] = PriceUpdate(
                ticker=ticker,
                price=price,
                prev_price=price,   # polling loop replaces this with cached prev
                timestamp=now,
            )
        return result
```

---

## Factory Function

Reads the environment variable and returns the appropriate source. Called once at startup.

```python
# market/__init__.py
import os
from .interface import MarketDataSource
from .simulator import MarketSimulator
from .massive import MassiveAPIClient


def create_market_data_source() -> MarketDataSource:
    """
    Return a MarketDataSource based on environment configuration.
    Uses MassiveAPIClient if MASSIVE_API_KEY is set, otherwise MarketSimulator.
    """
    api_key = os.getenv("MASSIVE_API_KEY", "").strip()
    if api_key:
        return MassiveAPIClient(api_key=api_key)
    return MarketSimulator()
```

---

## FastAPI Integration

The market data source is managed via FastAPI's lifespan context manager.

```python
# app/main.py
from contextlib import asynccontextmanager
import asyncio
from fastapi import FastAPI
from .market import create_market_data_source, price_cache
from .market.loop import polling_loop
from .database import get_watchlist_tickers   # returns list[str] from DB

_polling_task: asyncio.Task | None = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _polling_task
    source = create_market_data_source()
    await source.start()

    # Simulator polls every 500ms; Massive polls based on tier
    import os
    interval = 0.5 if not os.getenv("MASSIVE_API_KEY") else 15.0

    _polling_task = asyncio.create_task(
        polling_loop(source, get_watchlist_tickers, interval),
        name="price-polling",
    )
    yield
    # Shutdown
    if _polling_task:
        _polling_task.cancel()
        try:
            await _polling_task
        except asyncio.CancelledError:
            pass
    await source.stop()

app = FastAPI(lifespan=lifespan)
```

---

## SSE Endpoint

The SSE endpoint reads from `price_cache` and streams JSON events to clients. It does not call the market data source directly.

```python
# app/routes/stream.py
import asyncio
import json
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from ..market.cache import price_cache

router = APIRouter()

@router.get("/api/stream/prices")
async def stream_prices():
    """
    SSE endpoint. Pushes all cached prices to the client every 500ms.
    The client uses the native EventSource API; reconnection is automatic.
    """
    async def event_generator():
        while True:
            try:
                prices = await price_cache.get_all()
                if prices:
                    payload = {
                        ticker: update.model_dump()
                        for ticker, update in prices.items()
                    }
                    yield f"data: {json.dumps(payload)}\n\n"
                await asyncio.sleep(0.5)
            except asyncio.CancelledError:
                break

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # Disable nginx buffering
        },
    )
```

**SSE event format:**

Each `data:` event is a JSON object mapping ticker to `PriceUpdate`:

```json
{
  "AAPL": {"ticker": "AAPL", "price": 190.85, "prev_price": 190.60, "timestamp": "2024-01-15T14:30:00.500Z", "change_pct": 0.13},
  "MSFT": {"ticker": "MSFT", "price": 421.10, "prev_price": 420.90, "timestamp": "2024-01-15T14:30:00.500Z", "change_pct": 0.05}
}
```

The frontend connects with:

```typescript
const es = new EventSource("/api/stream/prices");
es.onmessage = (event) => {
  const prices = JSON.parse(event.data);
  // Update UI for each ticker in prices
};
```

---

## Data Flow Summary

```
MarketSimulator (500ms GBM)    MassiveAPIClient (15s REST poll)
        |                               |
        └──────────┬────────────────────┘
                   │  get_prices(tickers)
                   ▼
             polling_loop
                   │  update_many(PriceUpdate)
                   ▼
              PriceCache (in-memory)
                   │  get_all() every 500ms
                   ▼
            SSE /api/stream/prices
                   │  data: {...}
                   ▼
             Browser EventSource
```

With the simulator, the polling loop interval matches the simulation tick (500ms). With Massive, the polling loop runs every 15s (free tier) or faster on paid tiers, but the SSE endpoint still pushes to clients every 500ms — it just repeats the same prices until a new poll updates the cache.

---

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Massive API returns 429 | `polling_loop` logs the error and sleeps `interval_seconds` before retrying |
| Massive API returns 5xx | Same — log and retry next cycle |
| Ticker not in API response | Omitted from cache update; SSE continues sending last known price |
| Simulator exception in tick | Logged; simulator continues with next tick |
| SSE client disconnects | `asyncio.CancelledError` propagates; generator exits cleanly |
| No tickers in watchlist | Polling loop skips the `get_prices` call; cache stays at last known state |
