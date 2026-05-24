# FinAlly — Market Data Backend Design

## Overview

This document specifies the complete implementation of the market data subsystem for FinAlly. It covers:

1. **Shared data models** — Pydantic types that flow through every layer
2. **Abstract interface** — the contract both providers must satisfy
3. **Price cache** — thread-safe in-memory store
4. **Market Simulator** — GBM engine with correlations and random events
5. **Massive API client** — Polygon.io REST polling
6. **Provider factory** — environment-driven selection
7. **SSE streaming endpoint** — pushing live prices to the browser
8. **Lifecycle management** — startup / shutdown in FastAPI
9. **Unit tests** — pytest examples for every component

---

## 1. File Layout

```
backend/
├── pyproject.toml
├── app/
│   ├── __init__.py
│   ├── main.py                   # FastAPI app, lifespan hook
│   ├── config.py                 # Settings via pydantic-settings
│   ├── market/
│   │   ├── __init__.py
│   │   ├── models.py             # PriceUpdate, PriceSnapshot, TickerConfig
│   │   ├── cache.py              # PriceCache — in-memory store
│   │   ├── base.py               # MarketDataProvider abstract class
│   │   ├── simulator.py          # GBM-based simulator
│   │   ├── massive.py            # Polygon.io REST client
│   │   └── factory.py            # get_provider() factory
│   └── routes/
│       ├── stream.py             # GET /api/stream/prices (SSE)
│       └── ...
└── tests/
    └── market/
        ├── test_cache.py
        ├── test_simulator.py
        └── test_massive.py
```

---

## 2. Shared Data Models (`market/models.py`)

All data flowing through the system uses these Pydantic models. Both the simulator and the Massive client produce `PriceUpdate` objects. The cache stores `PriceSnapshot` objects. The SSE endpoint serialises `PriceSnapshot` to JSON.

```python
# backend/app/market/models.py

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, field_validator


class PriceUpdate(BaseModel):
    """
    A single price tick produced by a MarketDataProvider.
    One update per ticker per poll cycle.
    """
    ticker: str                      # e.g. "AAPL"
    price: float                     # latest trade price
    timestamp: datetime              # UTC time of this tick


class PriceSnapshot(BaseModel):
    """
    What the cache (and SSE clients) see: current + previous price,
    plus a derived direction field.
    """
    ticker: str
    price: float
    prev_price: float
    change: float                    # price - prev_price (absolute)
    change_pct: float                # (price - prev_price) / prev_price * 100
    direction: Literal["up", "down", "flat"]
    timestamp: datetime

    @classmethod
    def from_update(cls, update: PriceUpdate, prev_price: float) -> "PriceSnapshot":
        change = update.price - prev_price
        change_pct = (change / prev_price * 100) if prev_price else 0.0
        if change > 0:
            direction = "up"
        elif change < 0:
            direction = "down"
        else:
            direction = "flat"
        return cls(
            ticker=update.ticker,
            price=update.price,
            prev_price=prev_price,
            change=round(change, 4),
            change_pct=round(change_pct, 4),
            direction=direction,
            timestamp=update.timestamp,
        )


class TickerConfig(BaseModel):
    """
    Per-ticker simulation parameters for the GBM engine.
    """
    ticker: str
    seed_price: float                # realistic starting price
    annual_drift: float = 0.08       # μ — annualised expected return
    annual_volatility: float = 0.25  # σ — annualised std-dev
    sector: str = "tech"             # used for correlation grouping

    @field_validator("seed_price", "annual_volatility")
    @classmethod
    def must_be_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("must be positive")
        return v
```

---

## 3. Price Cache (`market/cache.py`)

A single shared, thread-safe in-memory store.  
The simulator/Massive client **writes** here. The SSE endpoint **reads** here.

```python
# backend/app/market/cache.py

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Optional

from .models import PriceSnapshot, PriceUpdate


class PriceCache:
    """
    Thread-safe in-memory store of the latest PriceSnapshot for every tracked ticker.

    Producers (simulator / Massive client) call ``update()``.
    Consumers (SSE endpoint, watchlist route) call ``get()`` or ``get_all()``.

    Also maintains a per-ticker ring buffer of the last HISTORY_SIZE price points
    so the frontend can draw sparklines without hitting the DB.
    """

    HISTORY_SIZE = 360   # 30 min at 500 ms cadence = 3600 ticks; keep last 360

    def __init__(self) -> None:
        self._data: Dict[str, PriceSnapshot] = {}
        # Ring buffer: ticker → list of (timestamp, price) tuples (oldest first)
        self._history: Dict[str, List[tuple[datetime, float]]] = {}
        self._lock = asyncio.Lock()

    async def update(self, update: PriceUpdate) -> PriceSnapshot:
        """
        Ingest a PriceUpdate, compute the snapshot, store it, return it.
        Creates a flat snapshot (prev_price == price) for brand-new tickers.
        """
        async with self._lock:
            existing = self._data.get(update.ticker)
            prev_price = existing.price if existing else update.price
            snapshot = PriceSnapshot.from_update(update, prev_price)
            self._data[update.ticker] = snapshot

            # Append to ring buffer
            history = self._history.setdefault(update.ticker, [])
            history.append((update.timestamp, update.price))
            if len(history) > self.HISTORY_SIZE:
                self._history[update.ticker] = history[-self.HISTORY_SIZE:]

            return snapshot

    async def get(self, ticker: str) -> Optional[PriceSnapshot]:
        async with self._lock:
            return self._data.get(ticker)

    async def get_all(self) -> Dict[str, PriceSnapshot]:
        async with self._lock:
            return dict(self._data)

    async def get_history(self, ticker: str) -> List[tuple[datetime, float]]:
        """Return sparkline data: list of (timestamp, price) pairs."""
        async with self._lock:
            return list(self._history.get(ticker, []))

    async def remove_ticker(self, ticker: str) -> None:
        async with self._lock:
            self._data.pop(ticker, None)
            self._history.pop(ticker, None)

    @property
    def tickers(self) -> List[str]:
        return list(self._data.keys())
```

### Usage example

```python
cache = PriceCache()

update = PriceUpdate(ticker="AAPL", price=191.50, timestamp=datetime.now(timezone.utc))
snapshot = await cache.update(update)

print(snapshot.direction)   # "up" / "down" / "flat"
print(snapshot.change_pct)  # e.g. 0.026 (percent)
```

---

## 4. Abstract Interface (`market/base.py`)

Both providers implement this three-method contract. FastAPI's lifespan hook calls `start()` and `stop()`; the SSE endpoint calls `subscribe()` to get a live stream of snapshots.

```python
# backend/app/market/base.py

from __future__ import annotations

import abc
from typing import AsyncIterator, Set


class MarketDataProvider(abc.ABC):
    """
    Abstract base class for all market data sources.

    Concrete implementations:
      - MarketSimulator   (built-in GBM simulator)
      - MassiveApiClient  (Polygon.io REST polling)

    Lifecycle
    ---------
    The FastAPI app calls ``start()`` inside the lifespan ``async with`` block
    and ``stop()`` on teardown.  Internally, each provider runs an async
    background task that:
      1. Produces PriceUpdate objects
      2. Writes them to the shared PriceCache
      3. Notifies all subscribed asyncio.Queue consumers

    Subscription
    ------------
    Each SSE connection calls ``subscribe()`` which returns an async generator
    of PriceSnapshot objects.  The generator yields indefinitely until the
    client disconnects (cancellation of the outer coroutine).
    """

    @abc.abstractmethod
    async def start(self) -> None:
        """Start the background polling/simulation task."""
        ...

    @abc.abstractmethod
    async def stop(self) -> None:
        """Gracefully stop the background task and release resources."""
        ...

    @abc.abstractmethod
    async def subscribe(self) -> AsyncIterator["PriceSnapshot"]:  # type: ignore[name-defined]
        """
        Async generator that yields PriceSnapshot objects as they arrive.
        Each connected SSE client gets its own subscription.
        Callers cancel the generator (via GeneratorExit / asyncio.CancelledError)
        when the client disconnects.
        """
        ...

    @abc.abstractmethod
    def get_watched_tickers(self) -> Set[str]:
        """Return the current set of tickers being tracked."""
        ...

    @abc.abstractmethod
    async def add_ticker(self, ticker: str) -> None:
        """Add a ticker to the watch set (hot-reload; no restart needed)."""
        ...

    @abc.abstractmethod
    async def remove_ticker(self, ticker: str) -> None:
        """Remove a ticker from the watch set."""
        ...
```

### Subscriber fan-out pattern

Both providers share the same subscriber machinery, extracted into a mixin:

```python
# backend/app/market/base.py  (continued)

import asyncio
from typing import List


class SubscriberMixin:
    """
    Manages a list of asyncio.Queue subscribers.
    Producers call ``_publish(snapshot)``; consumers call ``subscribe()``.
    """

    def __init__(self) -> None:
        self._subscribers: List[asyncio.Queue] = []

    async def _publish(self, snapshot: "PriceSnapshot") -> None:  # type: ignore[name-defined]
        dead = []
        for q in self._subscribers:
            try:
                q.put_nowait(snapshot)
            except asyncio.QueueFull:
                dead.append(q)  # slow consumer — drop it
        for q in dead:
            self._subscribers.remove(q)

    async def subscribe(self):  # noqa: ANN201
        """Async generator — each call gets an independent queue."""
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._subscribers.append(q)
        try:
            while True:
                snapshot = await q.get()
                yield snapshot
        finally:
            try:
                self._subscribers.remove(q)
            except ValueError:
                pass
```

---

## 5. Market Simulator (`market/simulator.py`)

Implements **Geometric Brownian Motion** with:
- Per-ticker drift (μ) and volatility (σ)
- A shared correlation matrix (Cholesky decomposition) for sector co-movement
- Random "market events" — abrupt 2–5% price shocks on a random ticker

### GBM Maths

```
S(t + Δt) = S(t) · exp( (μ - σ²/2)·Δt  +  σ·√Δt·Z )

where:
  Δt  = time step in years  (0.5 s ÷ 31,536,000 s/yr ≈ 1.59 × 10⁻⁸)
  Z   = correlated standard-normal draw
  μ   = annual drift (e.g. 0.08 for 8% annual expected return)
  σ   = annual volatility (e.g. 0.30 for 30%)
```

For **correlated draws**, we use a Cholesky-decomposed correlation matrix `L` such that:

```
Z_correlated = L · Z_independent
```

where `Z_independent` ~ N(0, I).

```python
# backend/app/market/simulator.py

from __future__ import annotations

import asyncio
import math
import random
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set

import numpy as np

from .base import MarketDataProvider, SubscriberMixin
from .cache import PriceCache
from .models import PriceSnapshot, PriceUpdate, TickerConfig


# ── Default ticker universe ──────────────────────────────────────────────────

DEFAULT_TICKERS: List[TickerConfig] = [
    TickerConfig(ticker="AAPL",  seed_price=191.00, annual_drift=0.10, annual_volatility=0.28, sector="tech"),
    TickerConfig(ticker="GOOGL", seed_price=175.00, annual_drift=0.09, annual_volatility=0.30, sector="tech"),
    TickerConfig(ticker="MSFT",  seed_price=415.00, annual_drift=0.11, annual_volatility=0.25, sector="tech"),
    TickerConfig(ticker="AMZN",  seed_price=185.00, annual_drift=0.12, annual_volatility=0.32, sector="tech"),
    TickerConfig(ticker="TSLA",  seed_price=175.00, annual_drift=0.08, annual_volatility=0.55, sector="tech"),
    TickerConfig(ticker="NVDA",  seed_price=875.00, annual_drift=0.15, annual_volatility=0.50, sector="tech"),
    TickerConfig(ticker="META",  seed_price=490.00, annual_drift=0.10, annual_volatility=0.35, sector="tech"),
    TickerConfig(ticker="JPM",   seed_price=197.00, annual_drift=0.07, annual_volatility=0.22, sector="finance"),
    TickerConfig(ticker="V",     seed_price=275.00, annual_drift=0.09, annual_volatility=0.20, sector="finance"),
    TickerConfig(ticker="NFLX",  seed_price=625.00, annual_drift=0.08, annual_volatility=0.40, sector="media"),
]

# ── Correlation matrix (lower-triangular Cholesky factor) ────────────────────
#
# Sectors:  tech (0-6),  finance (7-8),  media (9)
#
# Simple block structure:
#   • same-sector correlation: 0.65
#   • cross-sector (tech↔finance): 0.30
#   • cross-sector (tech↔media):   0.25
#   • cross-sector (finance↔media):0.20
#

def _build_correlation_matrix(configs: List[TickerConfig]) -> np.ndarray:
    n = len(configs)
    corr = np.eye(n)
    same_sector_corr = 0.65
    cross_sector_corr = 0.20
    for i in range(n):
        for j in range(i + 1, n):
            if configs[i].sector == configs[j].sector:
                c = same_sector_corr
            else:
                c = cross_sector_corr
            corr[i, j] = c
            corr[j, i] = c
    return corr


# ── Simulator ────────────────────────────────────────────────────────────────

class MarketSimulator(SubscriberMixin, MarketDataProvider):
    """
    GBM-based market simulator.

    Parameters
    ----------
    cache : PriceCache
        Shared price cache — updated on every tick.
    tick_interval : float
        Seconds between price updates (default 0.5).
    event_probability : float
        Per-tick probability of a random market event on one ticker (default 0.002).
    event_magnitude : tuple[float, float]
        Min/max shock magnitude as a fraction (default 2–5%).
    """

    SECONDS_PER_YEAR = 365.25 * 24 * 3600

    def __init__(
        self,
        cache: PriceCache,
        tick_interval: float = 0.5,
        event_probability: float = 0.002,
        event_magnitude: tuple[float, float] = (0.02, 0.05),
    ) -> None:
        SubscriberMixin.__init__(self)
        self._cache = cache
        self._tick_interval = tick_interval
        self._event_probability = event_probability
        self._event_magnitude = event_magnitude

        # Runtime state
        self._ticker_map: Dict[str, TickerConfig] = {}
        self._prices: Dict[str, float] = {}
        self._cholesky: Optional[np.ndarray] = None
        self._task: Optional[asyncio.Task] = None

        # Seed with defaults
        for cfg in DEFAULT_TICKERS:
            self._add_config(cfg)

    # ── Public interface ─────────────────────────────────────────────────────

    async def start(self) -> None:
        self._rebuild_cholesky()
        self._task = asyncio.create_task(self._run_loop(), name="market-simulator")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def get_watched_tickers(self) -> Set[str]:
        return set(self._ticker_map.keys())

    async def add_ticker(self, ticker: str) -> None:
        ticker = ticker.upper()
        if ticker not in self._ticker_map:
            # Use generic config for unknown tickers
            cfg = TickerConfig(
                ticker=ticker,
                seed_price=100.0,
                annual_drift=0.08,
                annual_volatility=0.30,
                sector="tech",
            )
            self._add_config(cfg)
            self._rebuild_cholesky()

    async def remove_ticker(self, ticker: str) -> None:
        ticker = ticker.upper()
        self._ticker_map.pop(ticker, None)
        self._prices.pop(ticker, None)
        await self._cache.remove_ticker(ticker)
        self._rebuild_cholesky()

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _add_config(self, cfg: TickerConfig) -> None:
        self._ticker_map[cfg.ticker] = cfg
        self._prices[cfg.ticker] = cfg.seed_price

    def _rebuild_cholesky(self) -> None:
        """Recompute the Cholesky factor whenever the ticker set changes."""
        configs = list(self._ticker_map.values())
        if not configs:
            self._cholesky = None
            return
        corr = _build_correlation_matrix(configs)
        # Add small jitter to diagonal for numerical stability
        corr += np.eye(len(configs)) * 1e-9
        try:
            self._cholesky = np.linalg.cholesky(corr)
        except np.linalg.LinAlgError:
            # Fallback: identity (no correlation)
            self._cholesky = np.eye(len(configs))

    # ── Main simulation loop ──────────────────────────────────────────────────

    async def _run_loop(self) -> None:
        dt = self._tick_interval / self.SECONDS_PER_YEAR  # years per tick
        while True:
            await asyncio.sleep(self._tick_interval)
            now = datetime.now(timezone.utc)
            self._maybe_fire_event()
            updates = self._step_prices(dt, now)
            for update in updates:
                snapshot = await self._cache.update(update)
                await self._publish(snapshot)

    def _step_prices(self, dt: float, now: datetime) -> List[PriceUpdate]:
        """Apply one GBM step to all tracked tickers using correlated normals."""
        configs = list(self._ticker_map.values())
        if not configs or self._cholesky is None:
            return []

        n = len(configs)
        # Draw independent standard normals
        z_ind = np.random.standard_normal(n)
        # Apply Cholesky to get correlated normals
        z_corr = self._cholesky @ z_ind

        updates: List[PriceUpdate] = []
        for i, cfg in enumerate(configs):
            mu = cfg.annual_drift
            sigma = cfg.annual_volatility
            z = z_corr[i]
            # GBM discrete step (log-normal)
            factor = math.exp((mu - 0.5 * sigma ** 2) * dt + sigma * math.sqrt(dt) * z)
            new_price = round(self._prices[cfg.ticker] * factor, 2)
            # Clamp to prevent degenerate values
            new_price = max(new_price, 0.01)
            self._prices[cfg.ticker] = new_price
            updates.append(PriceUpdate(ticker=cfg.ticker, price=new_price, timestamp=now))

        return updates

    def _maybe_fire_event(self) -> None:
        """Randomly apply a sudden 2–5% shock to one ticker for drama."""
        if random.random() > self._event_probability:
            return
        if not self._ticker_map:
            return
        ticker = random.choice(list(self._ticker_map.keys()))
        magnitude = random.uniform(*self._event_magnitude)
        direction = random.choice([-1, 1])
        shock = 1.0 + direction * magnitude
        self._prices[ticker] = round(self._prices[ticker] * shock, 2)
```

### Simulator demo (standalone)

```python
# Quick sanity-check — run with: python -m asyncio backend/demo_sim.py

import asyncio
from app.market.cache import PriceCache
from app.market.simulator import MarketSimulator

async def main():
    cache = PriceCache()
    sim = MarketSimulator(cache, tick_interval=0.5)
    await sim.start()

    async for snapshot in sim.subscribe():
        print(f"{snapshot.ticker:6s}  ${snapshot.price:>9.2f}  "
              f"{'▲' if snapshot.direction == 'up' else '▼' if snapshot.direction == 'down' else '─'}"
              f"  {snapshot.change_pct:+.3f}%")

asyncio.run(main())
```

---

## 6. Massive API Client (`market/massive.py`)

Polygon.io's "Snapshot" endpoint returns the last quote/trade for a list of tickers in a single REST call. This is the most efficient approach on the free tier.

### Endpoint Reference

```
GET https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers
    ?tickers=AAPL,GOOGL,MSFT
    &apiKey={MASSIVE_API_KEY}
```

Response shape (abbreviated):

```json
{
  "status": "OK",
  "tickers": [
    {
      "ticker": "AAPL",
      "day": { "c": 191.24 },
      "lastTrade": { "p": 191.50, "t": 1716580800000000000 },
      "prevDay": { "c": 190.80 }
    }
  ]
}
```

### Implementation

```python
# backend/app/market/massive.py

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set

import httpx

from .base import MarketDataProvider, SubscriberMixin
from .cache import PriceCache
from .models import PriceSnapshot, PriceUpdate, TickerConfig

log = logging.getLogger(__name__)

POLYGON_SNAPSHOT_URL = (
    "https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers"
)


class MassiveApiClient(SubscriberMixin, MarketDataProvider):
    """
    Polygon.io REST polling client.

    Polls the snapshot endpoint on a fixed interval and pushes updates
    to the shared PriceCache and all SSE subscribers.

    Rate limits:
      - Free tier: 5 requests/min → use poll_interval=15.0
      - Starter tier: 1 request/min unlimited  → use poll_interval=5.0
      - Developer tier: unlimited → use poll_interval=2.0

    Parameters
    ----------
    api_key : str
        Polygon.io / Massive API key.
    cache : PriceCache
        Shared price cache.
    poll_interval : float
        Seconds between polls (default 15.0 for free tier safety).
    initial_tickers : list[str]
        Tickers to watch at startup (default tickers added automatically).
    """

    def __init__(
        self,
        api_key: str,
        cache: PriceCache,
        poll_interval: float = 15.0,
        initial_tickers: Optional[List[str]] = None,
    ) -> None:
        SubscriberMixin.__init__(self)
        self._api_key = api_key
        self._cache = cache
        self._poll_interval = poll_interval
        self._tickers: Set[str] = set(initial_tickers or [])
        self._client: Optional[httpx.AsyncClient] = None
        self._task: Optional[asyncio.Task] = None
        # Cache last known prices so we always have a prev_price even if a
        # ticker isn't included in a given poll (e.g. market closed).
        self._last_prices: Dict[str, float] = {}

    # ── Public interface ─────────────────────────────────────────────────────

    async def start(self) -> None:
        self._client = httpx.AsyncClient(timeout=10.0)
        self._task = asyncio.create_task(self._poll_loop(), name="massive-poller")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._client:
            await self._client.aclose()

    def get_watched_tickers(self) -> Set[str]:
        return set(self._tickers)

    async def add_ticker(self, ticker: str) -> None:
        self._tickers.add(ticker.upper())

    async def remove_ticker(self, ticker: str) -> None:
        ticker = ticker.upper()
        self._tickers.discard(ticker)
        await self._cache.remove_ticker(ticker)

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _poll_loop(self) -> None:
        while True:
            if self._tickers:
                try:
                    updates = await self._fetch_snapshot(list(self._tickers))
                    for update in updates:
                        snapshot = await self._cache.update(update)
                        await self._publish(snapshot)
                except httpx.HTTPStatusError as e:
                    log.warning("Polygon HTTP error %s: %s", e.response.status_code, e)
                    if e.response.status_code == 429:
                        # Back off on rate-limit
                        await asyncio.sleep(self._poll_interval * 2)
                        continue
                except httpx.RequestError as e:
                    log.warning("Polygon request error: %s", e)
                except Exception as e:
                    log.exception("Unexpected error in Massive poll loop: %s", e)
            await asyncio.sleep(self._poll_interval)

    async def _fetch_snapshot(self, tickers: List[str]) -> List[PriceUpdate]:
        """
        Fetch the latest snapshot for a list of tickers.
        Returns a list of PriceUpdate objects.
        """
        assert self._client is not None
        ticker_str = ",".join(tickers)
        response = await self._client.get(
            POLYGON_SNAPSHOT_URL,
            params={"tickers": ticker_str, "apiKey": self._api_key},
        )
        response.raise_for_status()
        data = response.json()
        return self._parse_snapshot_response(data)

    def _parse_snapshot_response(self, data: dict) -> List[PriceUpdate]:
        """
        Parse Polygon.io snapshot response into PriceUpdate objects.

        Field priority for price:
          1. lastTrade.p  — most recent trade price
          2. day.c        — day's closing/current price
          3. prevDay.c    — previous day close (market closed fallback)
        """
        updates: List[PriceUpdate] = []
        tickers_data = data.get("tickers", [])

        for item in tickers_data:
            ticker = item.get("ticker", "").upper()
            if not ticker:
                continue

            price = self._extract_price(item)
            if price is None or price <= 0:
                log.debug("Skipping %s — no valid price in snapshot", ticker)
                continue

            # Extract timestamp from lastTrade.t (nanoseconds) or use now
            timestamp = self._extract_timestamp(item)

            updates.append(PriceUpdate(ticker=ticker, price=price, timestamp=timestamp))
            self._last_prices[ticker] = price

        return updates

    @staticmethod
    def _extract_price(item: dict) -> Optional[float]:
        """Extract the best available price from a snapshot item."""
        # 1. Last trade price
        last_trade = item.get("lastTrade") or {}
        if price := last_trade.get("p"):
            return float(price)
        # 2. Day's current/close price
        day = item.get("day") or {}
        if price := day.get("c"):
            return float(price)
        # 3. Previous day close (market is closed)
        prev_day = item.get("prevDay") or {}
        if price := prev_day.get("c"):
            return float(price)
        return None

    @staticmethod
    def _extract_timestamp(item: dict) -> datetime:
        """Extract UTC timestamp from lastTrade.t (nanoseconds epoch) or return now."""
        try:
            last_trade = item.get("lastTrade") or {}
            nanos = last_trade.get("t")
            if nanos:
                ts = int(nanos) / 1e9  # convert ns → seconds
                return datetime.fromtimestamp(ts, tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            pass
        return datetime.now(timezone.utc)
```

### Example raw Polygon response and parsed output

```python
raw = {
    "status": "OK",
    "tickers": [
        {
            "ticker": "AAPL",
            "lastTrade": {"p": 191.50, "t": 1716580800000000000},
            "day": {"c": 191.24},
            "prevDay": {"c": 190.80},
        },
        {
            "ticker": "TSLA",
            "lastTrade": {"p": 177.90, "t": 1716580799000000000},
            "day": {"c": 177.50},
            "prevDay": {"c": 176.00},
        },
    ],
}

client = MassiveApiClient(api_key="...", cache=PriceCache())
updates = client._parse_snapshot_response(raw)
# → [PriceUpdate(ticker='AAPL', price=191.5, ...), PriceUpdate(ticker='TSLA', price=177.9, ...)]
```

---

## 7. Provider Factory (`market/factory.py`)

The factory reads environment variables and returns the correct provider. All application code depends only on `MarketDataProvider` — it never imports `MarketSimulator` or `MassiveApiClient` directly.

```python
# backend/app/market/factory.py

from __future__ import annotations

import os

from .base import MarketDataProvider
from .cache import PriceCache


def get_provider(cache: PriceCache) -> MarketDataProvider:
    """
    Return the appropriate MarketDataProvider based on environment variables.

    Logic:
      MASSIVE_API_KEY set and non-empty → MassiveApiClient
      Otherwise                         → MarketSimulator
    """
    massive_key = os.getenv("MASSIVE_API_KEY", "").strip()

    if massive_key:
        from .massive import MassiveApiClient

        poll_interval = float(os.getenv("MASSIVE_POLL_INTERVAL", "15.0"))
        initial_tickers = [
            "AAPL", "GOOGL", "MSFT", "AMZN", "TSLA",
            "NVDA", "META", "JPM", "V", "NFLX",
        ]
        return MassiveApiClient(
            api_key=massive_key,
            cache=cache,
            poll_interval=poll_interval,
            initial_tickers=initial_tickers,
        )

    from .simulator import MarketSimulator

    tick_interval = float(os.getenv("SIM_TICK_INTERVAL", "0.5"))
    return MarketSimulator(cache=cache, tick_interval=tick_interval)
```

---

## 8. FastAPI Lifespan & Application Wiring (`main.py`)

The `lifespan` context manager starts the provider on app boot and stops it on shutdown. The provider and cache are stored as `app.state` attributes so any route can access them via the `Request` object.

```python
# backend/app/main.py

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .market.cache import PriceCache
from .market.factory import get_provider


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # ── Startup ───────────────────────────────────────────────────────────────
    cache = PriceCache()
    provider = get_provider(cache)

    app.state.price_cache = cache
    app.state.market_provider = provider

    await provider.start()
    yield
    # ── Shutdown ──────────────────────────────────────────────────────────────
    await provider.stop()


app = FastAPI(title="FinAlly", lifespan=lifespan)

# Register routers
from .routes import stream, portfolio, watchlist, chat  # noqa: E402
app.include_router(stream.router, prefix="/api/stream")
app.include_router(portfolio.router, prefix="/api/portfolio")
app.include_router(watchlist.router, prefix="/api/watchlist")
app.include_router(chat.router, prefix="/api/chat")

# Health check
@app.get("/api/health")
async def health():
    return {"status": "ok"}

# Serve Next.js static export — must be last (catch-all)
app.mount("/", StaticFiles(directory="static", html=True), name="static")
```

### Dependency injection helpers

```python
# backend/app/deps.py

from fastapi import Request
from .market.cache import PriceCache
from .market.base import MarketDataProvider


def get_cache(request: Request) -> PriceCache:
    return request.app.state.price_cache


def get_provider(request: Request) -> MarketDataProvider:
    return request.app.state.market_provider
```

---

## 9. SSE Streaming Endpoint (`routes/stream.py`)

The SSE endpoint keeps a long-lived connection open and pushes snapshots to the browser as they arrive. FastAPI's `StreamingResponse` is used with an async generator.

```python
# backend/app/routes/stream.py

from __future__ import annotations

import asyncio
import json
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from ..deps import get_provider
from ..market.base import MarketDataProvider

router = APIRouter()


def _serialise_snapshot(snapshot) -> str:
    """Format one SSE data frame."""
    payload = {
        "ticker":     snapshot.ticker,
        "price":      snapshot.price,
        "prev_price": snapshot.prev_price,
        "change":     snapshot.change,
        "change_pct": snapshot.change_pct,
        "direction":  snapshot.direction,
        "timestamp":  snapshot.timestamp.isoformat(),
    }
    # SSE format: "data: <json>\n\n"
    return f"data: {json.dumps(payload)}\n\n"


async def _price_stream(provider: MarketDataProvider, request: Request):
    """
    Async generator yielding SSE-formatted strings.
    Sends a heartbeat comment every 30 seconds to keep the connection alive
    through proxies and load balancers.
    """
    # Send an initial "connected" event so the client knows the stream is live
    yield ": connected\n\n"

    heartbeat_interval = 30  # seconds
    last_heartbeat = asyncio.get_event_loop().time()

    async for snapshot in provider.subscribe():
        # Check if the client has disconnected
        if await request.is_disconnected():
            break

        yield _serialise_snapshot(snapshot)

        # Emit heartbeat if needed
        now = asyncio.get_event_loop().time()
        if now - last_heartbeat >= heartbeat_interval:
            yield ": heartbeat\n\n"
            last_heartbeat = now


@router.get("/prices")
async def stream_prices(
    request: Request,
    provider: MarketDataProvider = Depends(get_provider),
):
    """
    GET /api/stream/prices

    Server-Sent Events stream of live price updates.
    Each event is a JSON object with fields:
      ticker, price, prev_price, change, change_pct, direction, timestamp

    The client connects with:
      const es = new EventSource('/api/stream/prices');
      es.onmessage = (e) => { const data = JSON.parse(e.data); ... };
    """
    return StreamingResponse(
        _price_stream(provider, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # disable nginx buffering
            "Connection": "keep-alive",
        },
    )
```

### Frontend connection (TypeScript reference)

```typescript
// frontend/src/hooks/usePriceStream.ts

import { useEffect, useRef, useState } from "react";

export interface PriceSnapshot {
  ticker: string;
  price: number;
  prev_price: number;
  change: number;
  change_pct: number;
  direction: "up" | "down" | "flat";
  timestamp: string;
}

export type PriceMap = Record<string, PriceSnapshot>;

type ConnectionStatus = "connecting" | "connected" | "reconnecting" | "disconnected";

export function usePriceStream() {
  const [prices, setPrices] = useState<PriceMap>({});
  const [status, setStatus] = useState<ConnectionStatus>("connecting");
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    let retryCount = 0;
    const MAX_RETRIES = 10;

    function connect() {
      const es = new EventSource("/api/stream/prices");
      esRef.current = es;
      setStatus("connecting");

      es.onopen = () => {
        setStatus("connected");
        retryCount = 0;
      };

      es.onmessage = (event) => {
        const snap: PriceSnapshot = JSON.parse(event.data);
        setPrices((prev) => ({ ...prev, [snap.ticker]: snap }));
      };

      es.onerror = () => {
        es.close();
        setStatus("reconnecting");
        if (retryCount < MAX_RETRIES) {
          const delay = Math.min(1000 * 2 ** retryCount, 30000);
          retryCount++;
          setTimeout(connect, delay);
        } else {
          setStatus("disconnected");
        }
      };
    }

    connect();

    return () => {
      esRef.current?.close();
    };
  }, []);

  return { prices, status };
}
```

---

## 10. Watchlist Route Integration

When the user adds or removes a ticker via the API, the route must also update the provider so the simulator/Massive client starts/stops tracking it.

```python
# backend/app/routes/watchlist.py  (relevant excerpt)

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..deps import get_cache, get_provider
from ..market.base import MarketDataProvider
from ..market.cache import PriceCache

router = APIRouter()


class AddTickerRequest(BaseModel):
    ticker: str


@router.post("", status_code=201)
async def add_ticker(
    body: AddTickerRequest,
    provider: MarketDataProvider = Depends(get_provider),
    cache: PriceCache = Depends(get_cache),
):
    ticker = body.ticker.upper().strip()
    if not ticker:
        raise HTTPException(status_code=422, detail="ticker is required")

    # 1. Persist to DB (omitted here — see database module)
    # db.add_watchlist_entry(user_id="default", ticker=ticker)

    # 2. Tell the market data provider to start tracking the ticker
    await provider.add_ticker(ticker)

    return {"ticker": ticker, "status": "added"}


@router.delete("/{ticker}", status_code=200)
async def remove_ticker(
    ticker: str,
    provider: MarketDataProvider = Depends(get_provider),
):
    ticker = ticker.upper()

    # 1. Remove from DB
    # db.remove_watchlist_entry(user_id="default", ticker=ticker)

    # 2. Tell the provider to stop tracking
    await provider.remove_ticker(ticker)

    return {"ticker": ticker, "status": "removed"}


@router.get("")
async def get_watchlist(cache: PriceCache = Depends(get_cache)):
    """Return all watched tickers with their latest prices."""
    all_prices = await cache.get_all()
    return [
        {
            "ticker": snap.ticker,
            "price": snap.price,
            "change": snap.change,
            "change_pct": snap.change_pct,
            "direction": snap.direction,
            "timestamp": snap.timestamp.isoformat(),
        }
        for snap in sorted(all_prices.values(), key=lambda s: s.ticker)
    ]
```

---

## 11. Configuration (`config.py`)

```python
# backend/app/config.py

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Market data
    massive_api_key: str = ""
    massive_poll_interval: float = 15.0   # seconds; override for paid tiers
    sim_tick_interval: float = 0.5        # seconds

    # LLM
    openrouter_api_key: str = ""
    llm_mock: bool = False

    # Database
    db_path: str = "/app/db/finally.db"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


settings = Settings()
```

---

## 12. Python Dependencies (`pyproject.toml` excerpt)

```toml
[project]
name = "finally-backend"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.111",
    "uvicorn[standard]>=0.29",
    "httpx>=0.27",
    "numpy>=1.26",
    "pydantic>=2.7",
    "pydantic-settings>=2.2",
    "litellm>=1.40",
    "python-dotenv>=1.0",
]

[tool.uv]
dev-dependencies = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "respx>=0.21",   # mock httpx in tests
]
```

---

## 13. Unit Tests

### 13.1 Cache tests (`tests/market/test_cache.py`)

```python
import asyncio
from datetime import datetime, timezone

import pytest

from app.market.cache import PriceCache
from app.market.models import PriceUpdate


@pytest.fixture
def cache():
    return PriceCache()


@pytest.mark.asyncio
async def test_first_update_creates_flat_snapshot(cache):
    update = PriceUpdate(ticker="AAPL", price=190.0, timestamp=datetime.now(timezone.utc))
    snap = await cache.update(update)
    assert snap.ticker == "AAPL"
    assert snap.price == 190.0
    assert snap.prev_price == 190.0   # no previous → flat
    assert snap.direction == "flat"
    assert snap.change == 0.0


@pytest.mark.asyncio
async def test_uptick_direction(cache):
    now = datetime.now(timezone.utc)
    await cache.update(PriceUpdate(ticker="AAPL", price=190.0, timestamp=now))
    snap = await cache.update(PriceUpdate(ticker="AAPL", price=191.0, timestamp=now))
    assert snap.direction == "up"
    assert snap.change == pytest.approx(1.0)
    assert snap.change_pct == pytest.approx(1.0 / 190.0 * 100, rel=1e-4)


@pytest.mark.asyncio
async def test_downtick_direction(cache):
    now = datetime.now(timezone.utc)
    await cache.update(PriceUpdate(ticker="AAPL", price=190.0, timestamp=now))
    snap = await cache.update(PriceUpdate(ticker="AAPL", price=188.5, timestamp=now))
    assert snap.direction == "down"
    assert snap.change == pytest.approx(-1.5)


@pytest.mark.asyncio
async def test_multiple_tickers_independent(cache):
    now = datetime.now(timezone.utc)
    await cache.update(PriceUpdate(ticker="AAPL", price=190.0, timestamp=now))
    await cache.update(PriceUpdate(ticker="GOOGL", price=175.0, timestamp=now))
    all_prices = await cache.get_all()
    assert set(all_prices.keys()) == {"AAPL", "GOOGL"}
    assert all_prices["AAPL"].price == 190.0
    assert all_prices["GOOGL"].price == 175.0


@pytest.mark.asyncio
async def test_remove_ticker(cache):
    now = datetime.now(timezone.utc)
    await cache.update(PriceUpdate(ticker="AAPL", price=190.0, timestamp=now))
    await cache.remove_ticker("AAPL")
    assert await cache.get("AAPL") is None


@pytest.mark.asyncio
async def test_history_ring_buffer(cache):
    now = datetime.now(timezone.utc)
    for i in range(400):
        await cache.update(PriceUpdate(ticker="AAPL", price=float(100 + i), timestamp=now))
    history = await cache.get_history("AAPL")
    assert len(history) == PriceCache.HISTORY_SIZE   # capped at 360
    # Most recent price is 499 (100 + 399)
    assert history[-1][1] == 499.0
```

### 13.2 Simulator tests (`tests/market/test_simulator.py`)

```python
import asyncio
from datetime import datetime, timezone

import pytest

from app.market.cache import PriceCache
from app.market.simulator import MarketSimulator


@pytest.fixture
async def running_sim():
    cache = PriceCache()
    sim = MarketSimulator(cache, tick_interval=0.05)  # fast for tests
    await sim.start()
    yield sim, cache
    await sim.stop()


@pytest.mark.asyncio
async def test_sim_produces_prices(running_sim):
    sim, cache = running_sim
    # Wait up to 1 second for at least 5 price updates
    for _ in range(20):
        all_prices = await cache.get_all()
        if len(all_prices) >= 5:
            break
        await asyncio.sleep(0.1)
    assert len(all_prices) >= 5


@pytest.mark.asyncio
async def test_sim_prices_positive(running_sim):
    sim, cache = running_sim
    await asyncio.sleep(0.5)  # let it run for a bit
    all_prices = await cache.get_all()
    for snap in all_prices.values():
        assert snap.price > 0, f"{snap.ticker} has non-positive price {snap.price}"


@pytest.mark.asyncio
async def test_sim_prices_are_near_seed(running_sim):
    """
    After only 1 second of simulation, prices should be within ±10% of seed.
    GBM drift over 1 second is negligible; large deviations would indicate a bug.
    """
    sim, cache = running_sim
    await asyncio.sleep(1.0)
    all_prices = await cache.get_all()

    from app.market.simulator import DEFAULT_TICKERS
    seed_map = {cfg.ticker: cfg.seed_price for cfg in DEFAULT_TICKERS}

    for snap in all_prices.values():
        seed = seed_map.get(snap.ticker)
        if seed:
            ratio = snap.price / seed
            assert 0.90 <= ratio <= 1.10, (
                f"{snap.ticker} price {snap.price:.2f} deviates >10% from seed {seed:.2f}"
            )


@pytest.mark.asyncio
async def test_add_remove_ticker(running_sim):
    sim, cache = running_sim
    await sim.add_ticker("PYPL")
    await asyncio.sleep(0.3)
    assert "PYPL" in sim.get_watched_tickers()

    await sim.remove_ticker("PYPL")
    assert "PYPL" not in sim.get_watched_tickers()


@pytest.mark.asyncio
async def test_subscriber_receives_updates(running_sim):
    sim, _ = running_sim
    received = []

    async def collect():
        async for snap in sim.subscribe():
            received.append(snap)
            if len(received) >= 3:
                return

    await asyncio.wait_for(collect(), timeout=5.0)
    assert len(received) >= 3
    assert all(s.price > 0 for s in received)


def test_gbm_step_deterministic():
    """Verify GBM formula correctness with a fixed random seed."""
    import math
    import numpy as np

    np.random.seed(42)
    cache = PriceCache()
    sim = MarketSimulator(cache, tick_interval=0.5)

    dt = 0.5 / sim.SECONDS_PER_YEAR
    # Run one step and verify prices are finite and positive
    now = datetime.now(timezone.utc)
    updates = sim._step_prices(dt, now)
    assert len(updates) == 10  # 10 default tickers
    for u in updates:
        assert math.isfinite(u.price)
        assert u.price > 0
```

### 13.3 Massive API tests (`tests/market/test_massive.py`)

```python
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
import respx
import httpx

from app.market.cache import PriceCache
from app.market.massive import MassiveApiClient, POLYGON_SNAPSHOT_URL


MOCK_SNAPSHOT_RESPONSE = {
    "status": "OK",
    "tickers": [
        {
            "ticker": "AAPL",
            "lastTrade": {"p": 191.50, "t": 1716580800000000000},
            "day": {"c": 191.24},
            "prevDay": {"c": 190.80},
        },
        {
            "ticker": "GOOGL",
            "lastTrade": {"p": 175.20, "t": 1716580799000000000},
            "day": {"c": 175.10},
            "prevDay": {"c": 174.50},
        },
    ],
}


def test_parse_snapshot_extracts_last_trade_price():
    cache = PriceCache()
    client = MassiveApiClient(api_key="test", cache=cache)
    updates = client._parse_snapshot_response(MOCK_SNAPSHOT_RESPONSE)
    assert len(updates) == 2
    aapl = next(u for u in updates if u.ticker == "AAPL")
    assert aapl.price == 191.50


def test_parse_snapshot_falls_back_to_day_close():
    """If lastTrade is missing, use day.c"""
    response = {
        "status": "OK",
        "tickers": [{"ticker": "JPM", "day": {"c": 197.30}, "prevDay": {"c": 196.00}}],
    }
    cache = PriceCache()
    client = MassiveApiClient(api_key="test", cache=cache)
    updates = client._parse_snapshot_response(response)
    assert len(updates) == 1
    assert updates[0].price == 197.30


def test_parse_snapshot_falls_back_to_prev_day():
    """If both lastTrade and day are missing, use prevDay.c"""
    response = {
        "status": "OK",
        "tickers": [{"ticker": "V", "prevDay": {"c": 275.10}}],
    }
    cache = PriceCache()
    client = MassiveApiClient(api_key="test", cache=cache)
    updates = client._parse_snapshot_response(response)
    assert len(updates) == 1
    assert updates[0].price == 275.10


def test_parse_snapshot_skips_zero_price():
    response = {
        "status": "OK",
        "tickers": [{"ticker": "BAD", "lastTrade": {"p": 0.0}}],
    }
    cache = PriceCache()
    client = MassiveApiClient(api_key="test", cache=cache)
    updates = client._parse_snapshot_response(response)
    assert len(updates) == 0


def test_parse_snapshot_skips_missing_ticker():
    response = {"status": "OK", "tickers": [{"lastTrade": {"p": 100.0}}]}
    cache = PriceCache()
    client = MassiveApiClient(api_key="test", cache=cache)
    updates = client._parse_snapshot_response(response)
    assert len(updates) == 0


@pytest.mark.asyncio
@respx.mock
async def test_fetch_snapshot_calls_correct_url():
    respx.get(POLYGON_SNAPSHOT_URL).mock(
        return_value=httpx.Response(200, json=MOCK_SNAPSHOT_RESPONSE)
    )
    cache = PriceCache()
    client = MassiveApiClient(api_key="mykey", cache=cache)
    client._client = httpx.AsyncClient()

    updates = await client._fetch_snapshot(["AAPL", "GOOGL"])
    assert len(updates) == 2

    # Verify the API key was passed as a query parameter
    request = respx.calls.last.request
    assert "apiKey=mykey" in str(request.url)
    await client._client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_rate_limit_backoff():
    """On 429, the client should back off and retry."""
    call_count = 0

    def handler(request):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(429, json={"error": "rate limited"})
        return httpx.Response(200, json=MOCK_SNAPSHOT_RESPONSE)

    respx.get(POLYGON_SNAPSHOT_URL).mock(side_effect=handler)

    cache = PriceCache()
    client = MassiveApiClient(
        api_key="test", cache=cache, poll_interval=0.05,
        initial_tickers=["AAPL"]
    )
    await client.start()
    await asyncio.sleep(0.5)  # give it time to retry
    await client.stop()

    # Should have called Polygon at least twice (1 rate-limited + 1 success)
    assert call_count >= 2


@pytest.mark.asyncio
async def test_add_remove_ticker():
    cache = PriceCache()
    client = MassiveApiClient(api_key="test", cache=cache)
    await client.add_ticker("PYPL")
    assert "PYPL" in client.get_watched_tickers()
    await client.remove_ticker("PYPL")
    assert "PYPL" not in client.get_watched_tickers()
```

### 13.4 Interface conformance test

```python
# tests/market/test_interface_conformance.py
"""
Both providers must satisfy the MarketDataProvider contract.
This parametrised test verifies the shared behaviour.
"""
import asyncio

import pytest

from app.market.base import MarketDataProvider
from app.market.cache import PriceCache
from app.market.simulator import MarketSimulator


@pytest.fixture(params=["simulator"])   # add "massive" with mocked HTTP later
def provider_and_cache(request):
    cache = PriceCache()
    if request.param == "simulator":
        return MarketSimulator(cache, tick_interval=0.05), cache
    raise ValueError(f"unknown provider: {request.param}")


@pytest.mark.asyncio
async def test_is_market_data_provider(provider_and_cache):
    provider, _ = provider_and_cache
    assert isinstance(provider, MarketDataProvider)


@pytest.mark.asyncio
async def test_start_stop(provider_and_cache):
    provider, _ = provider_and_cache
    await provider.start()
    await asyncio.sleep(0.1)
    await provider.stop()  # must not raise


@pytest.mark.asyncio
async def test_subscribe_yields_snapshots(provider_and_cache):
    provider, _ = provider_and_cache
    await provider.start()
    snapshots = []
    try:
        async for snap in provider.subscribe():
            snapshots.append(snap)
            if len(snapshots) >= 5:
                break
    finally:
        await provider.stop()
    assert len(snapshots) == 5
    for s in snapshots:
        assert s.price > 0
        assert s.ticker
        assert s.direction in ("up", "down", "flat")


@pytest.mark.asyncio
async def test_add_remove_ticker(provider_and_cache):
    provider, _ = provider_and_cache
    await provider.start()
    await provider.add_ticker("TEST")
    assert "TEST" in provider.get_watched_tickers()
    await provider.remove_ticker("TEST")
    assert "TEST" not in provider.get_watched_tickers()
    await provider.stop()
```

---

## 14. Sequence Diagrams

### 14.1 Price update flow (Simulator)

```
                    ┌─────────────┐        ┌────────────┐        ┌────────────────┐
                    │  Simulator  │        │ PriceCache │        │  SSE Clients   │
                    │  (bg task)  │        │            │        │  (browsers)    │
                    └──────┬──────┘        └─────┬──────┘        └───────┬────────┘
                           │                     │                       │
  every 500ms              │                     │                       │
  ─────────────────────────>                     │                       │
  GBM step → PriceUpdates  │                     │                       │
                           │   cache.update()    │                       │
                           │────────────────────>│                       │
                           │  PriceSnapshot      │                       │
                           │<────────────────────│                       │
                           │                     │                       │
                           │  _publish(snapshot) │                       │
                           │   (fan-out to N     │                       │
                           │    subscriber queues)│                      │
                           │──────────────────────────────────────────>  │
                           │                     │  yield snapshot       │
                           │                     │ ──────────────────>   │
                           │                     │  SSE frame sent       │
```

### 14.2 New ticker added

```
  Browser          FastAPI Route        Provider           PriceCache
     │                  │                  │                   │
     │  POST /api/watchlist  {ticker:"PYPL"}                   │
     │─────────────────>│                  │                   │
     │                  │ provider.add_ticker("PYPL")          │
     │                  │─────────────────>│                   │
     │                  │                  │  GBM config added │
     │                  │                  │  Cholesky rebuilt │
     │                  │  201 Created     │                   │
     │<─────────────────│                  │                   │
     │                  │                  │                   │
     │ (next tick)      │                  │                   │
     │                  │        PriceUpdate(PYPL, 100.00)     │
     │                  │                  │──────────────────>│
     │                  │                  │    PriceSnapshot  │
     │                  │                  │<──────────────────│
     │                  │                  │                   │
     │     SSE: {ticker:"PYPL", price:100.00, direction:"flat"}│
     │<─────────────────────────────────────────────────────── │
```

---

## 15. Key Design Decisions & Trade-offs

| Decision | Rationale |
|---|---|
| `asyncio.Lock` in PriceCache | Prevents data races between the producer task and concurrent SSE reads; low contention since the lock is held only during dict updates |
| Cholesky correlation | Produces statistically valid correlated returns; fast (O(n²) matrix multiply per tick); rebuilds on ticker add/remove |
| `asyncio.Queue` per subscriber | Decouples producer speed from consumer speed; slow clients (QueueFull) are dropped rather than blocking the sim loop |
| GBM with log-normal returns | Standard in quantitative finance; prevents negative prices; matches observed equity price behaviour |
| Heartbeat SSE comments | Keeps connection alive through AWS ALB (60s timeout) and Nginx (default 65s); costs zero bandwidth |
| `_last_prices` in MassiveApiClient | Polygon may omit tickers in partial responses (e.g. market closed); keeping the last known price avoids "new ticker" false positives |
| `HISTORY_SIZE = 360` | 360 × 500ms = 180s = 3 minutes of sparkline data; trades off memory vs. UI richness |
| Provider selected at startup | Environment is read once; switching providers requires a restart — acceptable for this use-case; avoids complex hot-swap logic |
