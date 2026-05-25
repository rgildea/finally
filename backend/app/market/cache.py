import asyncio

from .interface import PriceUpdate


class PriceCache:
    """
    Thread-safe in-memory store for the latest PriceUpdate per ticker.
    Uses asyncio.Lock since all callers are async.
    """

    def __init__(self) -> None:
        self._data: dict[str, PriceUpdate] = {}
        self._lock = asyncio.Lock()

    async def update(self, ticker: str, update: PriceUpdate) -> None:
        """Store the latest PriceUpdate for a ticker."""
        async with self._lock:
            self._data[ticker] = update

    async def update_many(self, updates: dict[str, PriceUpdate]) -> None:
        """Store multiple updates atomically under a single lock acquisition."""
        async with self._lock:
            self._data.update(updates)

    async def get(self, ticker: str) -> PriceUpdate | None:
        """Return the latest PriceUpdate for a ticker, or None if not cached."""
        async with self._lock:
            return self._data.get(ticker)

    async def get_many(self, tickers: list[str]) -> dict[str, PriceUpdate]:
        """Return prices for the requested tickers. Missing tickers are omitted."""
        async with self._lock:
            return {t: self._data[t] for t in tickers if t in self._data}

    async def get_all(self) -> dict[str, PriceUpdate]:
        """Return a shallow copy of all cached prices."""
        async with self._lock:
            return dict(self._data)

    async def remove(self, ticker: str) -> None:
        """Remove a ticker from the cache (called when removed from watchlist)."""
        async with self._lock:
            self._data.pop(ticker, None)


# Module-level singleton — imported by loop.py and the SSE endpoint
price_cache = PriceCache()
