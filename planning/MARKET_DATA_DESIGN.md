# FinAlly — Market Data Backend Design

## Overview

This document is the implementation guide for the market data subsystem. It is derived from and fully aligned with the three planning documents:

- `MARKET_INTERFACE.md` — unified interface, data model, cache, polling loop, SSE
- `MARKET_SIMULATOR.md` — GBM simulator design and code structure
- `MASSIVE_API.md` — Massive REST API reference and response schemas

Read those documents first. This document adds concrete implementation detail, fills in gaps (error handling, tests, edge cases), and serves as the implementation checklist for the Market Data Engineer agent.

---

## 1. Module Layout

```
backend/app/market/
├── __init__.py       # Re-exports + create_market_data_source() factory
├── interface.py      # PriceUpdate model + MarketDataSource ABC
├── cache.py          # PriceCache singleton
├── loop.py           # Background polling task
├── simulator.py      # MarketSimulator + SimulatorConfig + GBMSimulator
└── massive.py        # MassiveAPIClient
```

No other files. No `factory.py`, no `models.py`, no `base.py`. The factory lives in `__init__.py` as specified in `MARKET_INTERFACE.md`.

---

## 2. Data Model (`interface.py`)

### `PriceUpdate`

The single data structure that flows through the entire market data layer. Everything downstream — the SSE endpoint, the watchlist route, the portfolio valuation — works with `PriceUpdate` objects.

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

**Design notes:**
- `prev_price` is always the price from the previous poll cycle, stored in `PriceCache`. The polling loop's `_merge_with_prev()` attaches it before writing to the cache.
- `change_pct` is the per-tick move, not the daily change.
- There is no `direction` field — the frontend derives "up"/"down"/"flat" from the sign of `change_pct`.
- `timestamp` is an ISO 8601 string (not a `datetime` object) for direct JSON serialisation.

---

## 3. Abstract Interface (`interface.py`)

```python
# market/interface.py (continued)
from abc import ABC, abstractmethod


class MarketDataSource(ABC):
    @abstractmethod
    async def start(self) -> None:
        """
        Start the data source. Called once at application startup.
        For the simulator: launches the background GBM loop.
        For Massive: initialises the httpx client.
        Must be idempotent — safe to call even if already started.
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
            tickers: List of uppercase ticker symbols, e.g. ["AAPL", "MSFT"].

        Returns:
            Dict mapping ticker → PriceUpdate. Tickers with no data are
            omitted rather than raised as errors. The polling loop handles
            missing tickers gracefully (last known cached price is retained).

        Raises:
            httpx.HTTPStatusError: On Massive API non-2xx responses.
            asyncio.TimeoutError: If the request exceeds the configured timeout.
        """
```

**What is NOT on this interface:**
- `add_ticker` / `remove_ticker` — the polling loop calls `get_tickers()` (a DB callback) on every cycle, so newly added tickers are picked up automatically without touching the data source.
- `subscribe()` — there is no push/pub-sub mechanism. The SSE endpoint polls `PriceCache.get_all()` on its own 500ms timer.

---

## 4. Price Cache (`cache.py`)

Module-level singleton. Written by the polling loop; read by the SSE endpoint and any route that needs a live price (e.g. trade execution).

```python
# market/cache.py
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
```

**Design notes:**
- `asyncio.Lock` is used (not `threading.Lock`) because all callers are coroutines in the same event loop.
- `update_many` acquires the lock once for a batch — prevents a partial update being visible to a concurrent reader mid-batch.
- The singleton `price_cache` is the shared state between the polling loop and all readers. Import it directly: `from app.market.cache import price_cache`.

---

## 5. Background Polling Loop (`loop.py`)

A single asyncio task drives the data source and writes to the cache. It is the only writer to `PriceCache`.

```python
# market/loop.py
import asyncio
import logging
from collections.abc import Callable

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
```

**Design notes:**
- The loop never calls `add_ticker` or `remove_ticker` on the source. The `get_tickers` callback (which queries the DB) picks up watchlist changes on the next cycle.
- On Massive, a 429 from `get_prices()` is caught by the broad `except Exception` handler, logged, and the loop sleeps normally before retrying. For 429 specifically, the caller should sleep longer — see the Massive client section.
- Cancellation (`CancelledError`) is re-raised immediately so FastAPI's shutdown can cancel the task cleanly.

---

## 6. Market Simulator (`simulator.py`)

### 6.1 Configuration

All constants live in the module as a `SimulatorConfig` dataclass. No magic numbers in the simulation loop.

```python
# market/simulator.py
import asyncio
import math
import random
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .interface import MarketDataSource, PriceUpdate

logger = logging.getLogger(__name__)


@dataclass
class TickerConfig:
    seed_price: float
    mu: float       # Annual drift (expected return), e.g. 0.12 = 12%/year
    sigma: float    # Annual volatility, e.g. 0.28 = 28%/year
    sector: str


@dataclass
class SimulatorConfig:
    tickers: dict[str, TickerConfig] = field(default_factory=lambda: _DEFAULT_TICKERS.copy())
    sector_correlations: dict[str, float] = field(default_factory=lambda: _DEFAULT_CORRELATIONS.copy())
    tick_interval_seconds: float = 0.5
    event_probability: float = 0.001   # Per tick, per ticker
    event_magnitude_min: float = 0.02  # 2% minimum shock
    event_magnitude_max: float = 0.05  # 5% maximum shock


# ── Default ticker universe ────────────────────────────────────────────────────
#
# Seed prices and GBM parameters for the 10 default watchlist tickers.
# Source of truth: MARKET_SIMULATOR.md § Ticker Configuration

_DEFAULT_TICKERS: dict[str, TickerConfig] = {
    "AAPL":  TickerConfig(seed_price=190.00, mu=0.12, sigma=0.28, sector="Tech"),
    "MSFT":  TickerConfig(seed_price=420.00, mu=0.13, sigma=0.26, sector="Tech"),
    "NVDA":  TickerConfig(seed_price=875.00, mu=0.20, sigma=0.55, sector="Tech"),
    "META":  TickerConfig(seed_price=510.00, mu=0.15, sigma=0.38, sector="Tech"),
    "GOOGL": TickerConfig(seed_price=175.00, mu=0.11, sigma=0.27, sector="Tech"),
    "AMZN":  TickerConfig(seed_price=185.00, mu=0.14, sigma=0.32, sector="Tech"),
    "TSLA":  TickerConfig(seed_price=250.00, mu=0.10, sigma=0.65, sector="EV/Tech"),
    "NFLX":  TickerConfig(seed_price=640.00, mu=0.12, sigma=0.40, sector="Media"),
    "JPM":   TickerConfig(seed_price=195.00, mu=0.09, sigma=0.22, sector="Finance"),
    "V":     TickerConfig(seed_price=275.00, mu=0.10, sigma=0.20, sector="Finance"),
}

# Correlation coefficient ρ per sector.
# Controls how much a sector-wide shock contributes to each ticker's move.
# Z_ticker = ρ·Z_sector + √(1-ρ²)·Z_idiosyncratic
_DEFAULT_CORRELATIONS: dict[str, float] = {
    "Tech":    0.60,
    "EV/Tech": 0.40,   # TSLA has partial tech correlation but does its own thing
    "Media":   0.30,   # NFLX has weaker correlation with the broader market
    "Finance": 0.55,
}

# Fallback for any ticker the user adds that is not in _DEFAULT_TICKERS
_FALLBACK_CONFIG = TickerConfig(seed_price=100.0, mu=0.10, sigma=0.30, sector="Tech")
```

### 6.2 GBM Mathematics

**Continuous-time SDE:**
```
dS = μ·S·dt + σ·S·dW
```

**Discrete-time approximation (Euler-Maruyama / log-normal):**
```
S(t+dt) = S(t) · exp( (μ - σ²/2)·dt  +  σ·√dt·Z )
```

Where:
- `μ` — annual drift, e.g. `0.12` (12%/year)
- `σ` — annual volatility, e.g. `0.28` (28%/year)
- `dt` — time step in **trading years**: `0.5 / (252 × 6.5 × 3600) ≈ 8.5 × 10⁻⁸`
- `Z` — standard normal random variable

The `(μ - σ²/2)` term (Itô correction) ensures the expected price is `S·exp(μ·dt)`, not biased upward by the variance.

**Why trading hours, not calendar time:**

```python
# Correct — uses 252 trading days × 6.5 hours/day
dt = tick_interval / (252 * 6.5 * 3600)   # ≈ 8.5e-8

# Wrong — calendar year inflates sigma by ~2.3×
dt = tick_interval / (365.25 * 24 * 3600)  # do not use
```

Using calendar time makes volatility appear 2.3× lower than specified, because most of those seconds are nights and weekends when markets are closed.

### 6.3 Sector Correlation

Instead of a full Cholesky decomposition, the simulator uses a simpler and equivalent **sector-shock mixing** approach:

```
Z_ticker = ρ·Z_sector + √(1-ρ²)·Z_idiosyncratic
```

- `Z_sector` — one N(0,1) draw per sector per tick (shared across all tickers in that sector)
- `Z_idiosyncratic` — one N(0,1) draw per ticker per tick (independent)
- `ρ` — the sector correlation coefficient from `_DEFAULT_CORRELATIONS`

This produces the correct pairwise correlation: `Corr(Z_i, Z_j) = ρ²` for two tickers in the same sector.

### 6.4 `MarketSimulator` Implementation

```python
class MarketSimulator(MarketDataSource):
    """
    Simulates stock prices using GBM with sector correlations and random events.

    The simulation loop runs as an asyncio background task (started by start()).
    get_prices() reads the current in-memory prices synchronously — no I/O.
    """

    def __init__(self, config: SimulatorConfig | None = None) -> None:
        self._config = config or SimulatorConfig()
        # Live prices — updated by _tick(), read by get_prices()
        self._prices: dict[str, float] = {
            ticker: cfg.seed_price
            for ticker, cfg in self._config.tickers.items()
        }
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(
            self._run_loop(), name="market-simulator"
        )
        logger.info("Market simulator started")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Market simulator stopped")

    async def get_prices(self, tickers: list[str]) -> dict[str, PriceUpdate]:
        """
        Return current simulated prices for the requested tickers.
        Called by the polling loop every tick_interval_seconds.

        Tickers not in the config use the fallback config and start at $100.
        prev_price is set equal to price here; the polling loop's _merge_with_prev()
        replaces it with the actual previously cached price before writing to the cache.
        """
        now = datetime.now(timezone.utc).isoformat()
        result: dict[str, PriceUpdate] = {}
        for ticker in tickers:
            if ticker not in self._prices:
                # Dynamically add unknown tickers with fallback config
                self._config.tickers[ticker] = _FALLBACK_CONFIG
                self._prices[ticker] = _FALLBACK_CONFIG.seed_price
            price = round(self._prices[ticker], 2)
            result[ticker] = PriceUpdate(
                ticker=ticker,
                price=price,
                prev_price=price,   # polling loop replaces this with cached prev
                timestamp=now,
            )
        return result

    async def _run_loop(self) -> None:
        """Main simulation loop. Ticks every tick_interval_seconds."""
        cfg = self._config
        # dt in trading years: 252 trading days, 6.5 trading hours per day
        dt = cfg.tick_interval_seconds / (252 * 6.5 * 3600)

        while True:
            try:
                self._tick(dt)
                await asyncio.sleep(cfg.tick_interval_seconds)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Error in simulator tick — continuing")
                await asyncio.sleep(cfg.tick_interval_seconds)

    def _tick(self, dt: float) -> None:
        """Advance all ticker prices by one GBM time step."""
        sector_shocks = self._draw_sector_shocks()
        self._maybe_trigger_event()

        cfg = self._config
        for ticker, ticker_cfg in cfg.tickers.items():
            if ticker not in self._prices:
                continue
            rho = cfg.sector_correlations.get(ticker_cfg.sector, 0.0)
            z_sector = sector_shocks.get(ticker_cfg.sector, 0.0)
            z_idio = random.gauss(0, 1)

            # Sector-shock mixing: produces correct pairwise correlation = ρ²
            z = rho * z_sector + math.sqrt(max(0.0, 1 - rho ** 2)) * z_idio

            drift = (ticker_cfg.mu - 0.5 * ticker_cfg.sigma ** 2) * dt
            diffusion = ticker_cfg.sigma * math.sqrt(dt) * z
            self._prices[ticker] *= math.exp(drift + diffusion)

    def _draw_sector_shocks(self) -> dict[str, float]:
        """Draw one independent N(0,1) shock per active sector."""
        sectors = {cfg.sector for cfg in self._config.tickers.values()}
        return {sector: random.gauss(0, 1) for sector in sectors}

    def _maybe_trigger_event(self) -> None:
        """
        With small probability, apply a sudden 2–5% shock to a random ticker.
        Applied before the GBM step so the price continues naturally from the new level.
        At 0.001 probability per tick with 10 tickers: ~1 event per ~13 minutes.
        """
        cfg = self._config
        if random.random() < cfg.event_probability:
            ticker = random.choice(list(self._prices))
            magnitude = random.uniform(cfg.event_magnitude_min, cfg.event_magnitude_max)
            direction = 1 if random.random() > 0.5 else -1
            self._prices[ticker] *= (1 + direction * magnitude)
            logger.debug(
                "Market event: %s moved %+.1f%%", ticker, direction * magnitude * 100
            )
```

---

## 7. Massive API Client (`massive.py`)

### 7.1 API facts (from `MASSIVE_API.md`)

- **New base URL:** `https://api.massive.com` (legacy `https://api.polygon.io` still works)
- **Endpoint used:** `GET /v2/snapshot/locale/us/markets/stocks/tickers`
- **Bulk fetch:** all watchlist tickers in a single call via `?tickers=AAPL,MSFT,...`
- **Price field priority:** `lastTrade.p` → `day.c` (both are acceptable live prices)
- **Timestamps:** Unix **milliseconds** in `lastTrade.t`
- **Plan access:** Starter and above. **Not available on Basic (free) tier.**
- **Rate limits:** 5 req/min on free; unlimited on paid tiers
- **On 429:** back off 60 seconds before retrying

### 7.2 Implementation

```python
# market/massive.py
import asyncio
import logging
from datetime import datetime, timezone

import httpx

from .interface import MarketDataSource, PriceUpdate

logger = logging.getLogger(__name__)

MASSIVE_BASE_URL = "https://api.massive.com"
SNAPSHOT_PATH = "/v2/snapshot/locale/us/markets/stocks/tickers"


class MassiveAPIClient(MarketDataSource):
    """
    Fetches real stock prices from the Massive REST API.
    Uses the /v2/snapshot endpoint for bulk multi-ticker fetching.
    See MASSIVE_API.md for endpoint details and response schemas.

    Notes:
    - The snapshot endpoint requires a Starter plan or above.
      It is NOT available on the Basic (free) tier.
    - On 429 Too Many Requests, the client waits 60 seconds before
      the polling loop retries.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = MASSIVE_BASE_URL,
        timeout: float = 10.0,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        self._client = httpx.AsyncClient(timeout=self._timeout)
        logger.info("Massive API client started (base_url=%s)", self._base_url)

    async def stop(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
        logger.info("Massive API client stopped")

    async def get_prices(self, tickers: list[str]) -> dict[str, PriceUpdate]:
        """
        Fetch the latest snapshot for all requested tickers in one API call.

        Raises:
            RuntimeError: If start() has not been called.
            httpx.HTTPStatusError: On non-2xx responses (including 429).
            asyncio.TimeoutError: If the request exceeds self._timeout.
        """
        if not self._client:
            raise RuntimeError("MassiveAPIClient.start() must be called before get_prices()")

        response = await self._client.get(
            f"{self._base_url}{SNAPSHOT_PATH}",
            params={
                "tickers": ",".join(tickers),
                "apiKey": self._api_key,
            },
        )
        response.raise_for_status()
        return self._parse_response(response.json())

    def _parse_response(self, data: dict) -> dict[str, PriceUpdate]:
        """
        Parse the Massive snapshot response into PriceUpdate objects.

        Price field priority (from MASSIVE_API.md):
          1. lastTrade.p — most recent trade price (primary)
          2. day.c       — current day's close/price (fallback)

        Timestamps in lastTrade.t are Unix milliseconds.
        """
        result: dict[str, PriceUpdate] = {}
        now_iso = datetime.now(timezone.utc).isoformat()

        for item in data.get("tickers", []):
            ticker = item.get("ticker", "").upper()
            if not ticker:
                continue

            price = self._extract_price(item)
            if not price or price <= 0:
                logger.debug("Skipping %s — no valid price in snapshot", ticker)
                continue

            timestamp = self._extract_timestamp(item, now_iso)

            # prev_price is set to price here; the polling loop's _merge_with_prev()
            # replaces it with the actual cached prev before writing to PriceCache.
            result[ticker] = PriceUpdate(
                ticker=ticker,
                price=price,
                prev_price=price,
                timestamp=timestamp,
            )

        return result

    @staticmethod
    def _extract_price(item: dict) -> float | None:
        """Extract the best available price from a snapshot item."""
        last_trade = item.get("lastTrade") or {}
        if p := last_trade.get("p"):
            return float(p)
        day = item.get("day") or {}
        if c := day.get("c"):
            return float(c)
        return None

    @staticmethod
    def _extract_timestamp(item: dict, fallback: str) -> str:
        """
        Convert lastTrade.t (Unix milliseconds) to ISO 8601 UTC string.
        Falls back to current time if the field is missing or unparseable.
        """
        try:
            last_trade = item.get("lastTrade") or {}
            t_ms = last_trade.get("t")
            if t_ms is not None:
                ts = datetime.fromtimestamp(int(t_ms) / 1000, tz=timezone.utc)
                return ts.isoformat()
        except (TypeError, ValueError, OSError):
            pass
        return fallback
```

### 7.3 Rate limit handling in the polling loop

The `polling_loop` in `loop.py` catches all exceptions and retries after `interval_seconds`. For 429 responses, the Massive client raises `httpx.HTTPStatusError`. The loop logs and waits. To add a dedicated 60-second backoff for 429, override the loop in `main.py` or add a thin wrapper:

```python
# In polling_loop, after the except block (optional enhancement):
except httpx.HTTPStatusError as e:
    if e.response.status_code == 429:
        logger.warning("Massive API rate limited — backing off 60s")
        await asyncio.sleep(60)
        continue
    logger.exception("HTTP error in polling loop")
```

---

## 8. Factory (`__init__.py`)

```python
# market/__init__.py
import os

from .interface import MarketDataSource, PriceUpdate
from .cache import PriceCache, price_cache
from .simulator import MarketSimulator
from .massive import MassiveAPIClient

__all__ = [
    "MarketDataSource",
    "PriceUpdate",
    "PriceCache",
    "price_cache",
    "create_market_data_source",
]


def create_market_data_source() -> MarketDataSource:
    """
    Return the appropriate MarketDataSource based on environment variables.

    - MASSIVE_API_KEY set and non-empty → MassiveAPIClient
    - Otherwise → MarketSimulator

    Note: The Massive snapshot endpoint requires a Starter plan or above.
    It is not available on the Basic (free) tier.
    """
    api_key = os.getenv("MASSIVE_API_KEY", "").strip()
    if api_key:
        return MassiveAPIClient(api_key=api_key)
    return MarketSimulator()
```

---

## 9. FastAPI Integration (`main.py`)

```python
# app/main.py
import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .market import create_market_data_source, price_cache
from .market.loop import polling_loop
from .database import get_watchlist_tickers   # returns list[str] from SQLite


@asynccontextmanager
async def lifespan(app: FastAPI):
    source = create_market_data_source()
    await source.start()

    # Simulator: 500ms matches tick rate
    # Massive free tier: 15s (Starter+: 5s, Advanced+: 1s)
    interval = 0.5 if not os.getenv("MASSIVE_API_KEY") else 15.0

    task = asyncio.create_task(
        polling_loop(source, get_watchlist_tickers, interval),
        name="price-polling",
    )

    yield

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    await source.stop()


app = FastAPI(title="FinAlly", lifespan=lifespan)

# Routers
from .routes import stream, portfolio, watchlist, chat  # noqa: E402
app.include_router(stream.router)
app.include_router(portfolio.router)
app.include_router(watchlist.router)
app.include_router(chat.router)

@app.get("/api/health")
async def health():
    return {"status": "ok"}

# Static files last (catch-all)
app.mount("/", StaticFiles(directory="static", html=True), name="static")
```

---

## 10. SSE Endpoint (`routes/stream.py`)

The SSE endpoint reads from `price_cache` every 500ms and pushes all tickers as a single JSON object per event. It does not interact with the `MarketDataSource` directly.

```python
# routes/stream.py
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

    Event format — one JSON object containing all tickers:
        data: {"AAPL": {"ticker": "AAPL", "price": 190.85, "prev_price": 190.60,
                        "timestamp": "...", "change_pct": 0.13}, ...}

    The client connects with the native EventSource API:
        const es = new EventSource("/api/stream/prices");
        es.onmessage = (e) => {
          const prices = JSON.parse(e.data);
          // prices["AAPL"].price, prices["AAPL"].change_pct, etc.
        };

    EventSource handles reconnection automatically on network errors.
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
            "X-Accel-Buffering": "no",   # Disable nginx/proxy buffering
        },
    )
```

**SSE event format:**

```json
{
  "AAPL": {"ticker": "AAPL", "price": 190.85, "prev_price": 190.60,
           "timestamp": "2024-01-15T14:30:00.500Z", "change_pct": 0.13},
  "MSFT": {"ticker": "MSFT", "price": 421.10, "prev_price": 420.90,
           "timestamp": "2024-01-15T14:30:00.500Z", "change_pct": 0.05}
}
```

Note: With the Massive client, the poll interval (15s) is longer than the SSE push interval (500ms). Between polls, the SSE endpoint pushes the same cached prices repeatedly — `change_pct` will be 0.0 for those frames. The frontend should handle this gracefully (no flash animation for a zero change).

---

## 11. Data Flow

```
MarketSimulator (500ms GBM loop)     MassiveAPIClient (15s REST poll)
         |                                     |
         └──────────────┬──────────────────────┘
                        │  await source.get_prices(tickers)
                        ▼
                  polling_loop
                        │  _merge_with_prev() — attaches cached prev_price
                        │  price_cache.update_many(merged)
                        ▼
               PriceCache (in-memory)
                        │  get_all() every 500ms
                        ▼
            SSE /api/stream/prices
                        │  data: {"AAPL": {...}, "MSFT": {...}, ...}
                        ▼
              Browser EventSource
```

---

## 12. Watchlist Integration

The `get_tickers` callback passed to `polling_loop` queries the `watchlist` table in SQLite. This means adding or removing a ticker from the watchlist (via `POST /api/watchlist` or `DELETE /api/watchlist/{ticker}`) is automatically reflected on the next polling cycle — no restart, no data source interaction required.

```python
# database.py (relevant function)
def get_watchlist_tickers() -> list[str]:
    """Return all tickers in the default user's watchlist."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT ticker FROM watchlist WHERE user_id = 'default'"
        ).fetchall()
    return [row["ticker"] for row in rows]
```

When a ticker is removed from the watchlist, its price should also be cleared from the cache to avoid stale data appearing in `get_all()`:

```python
# In the DELETE /api/watchlist/{ticker} route handler:
await price_cache.remove(ticker)
```

---

## 13. Error Handling Summary

| Scenario | Behavior |
|----------|----------|
| Massive returns 429 | `polling_loop` logs, sleeps 60s, retries |
| Massive returns 5xx | `polling_loop` logs, sleeps `interval_seconds`, retries |
| Ticker absent from API response | Omitted from `update_many`; cache retains last known price |
| Simulator exception in `_tick` | Logged; simulator sleeps and continues next tick |
| SSE client disconnects | `CancelledError` propagates; generator exits via `break` |
| No tickers in watchlist | `polling_loop` skips `get_prices` call; cache unchanged |
| `start()` not called before `get_prices()` | `RuntimeError` raised immediately |

---

## 14. Python Dependencies

```toml
# backend/pyproject.toml (market data dependencies)
[project]
dependencies = [
    "fastapi>=0.111",
    "uvicorn[standard]>=0.29",
    "httpx>=0.27",        # Async HTTP client for Massive API
    "pydantic>=2.7",      # PriceUpdate model + computed_field
    "python-dotenv>=1.0", # .env file loading
    # numpy is NOT required — sector-shock correlation avoids Cholesky
]
```

No numpy dependency for market data. The sector-shock mixing approach uses only `math` and `random` from the standard library.

---

## 15. Unit Tests

### 15.1 Cache (`tests/market/test_cache.py`)

```python
import asyncio
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
```

### 15.2 Polling loop (`tests/market/test_loop.py`)

```python
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock
import pytest
from app.market.cache import PriceCache, price_cache as _global_cache
from app.market.interface import PriceUpdate
from app.market.loop import _merge_with_prev


def make_update(ticker, price):
    return PriceUpdate(
        ticker=ticker, price=price, prev_price=price,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@pytest.mark.asyncio
async def test_merge_with_prev_first_poll():
    """On first poll there is no prev — prev_price should equal current price."""
    # Ensure a clean cache for this test
    from app.market import cache as cache_module
    cache_module.price_cache._data.clear()

    updates = {"AAPL": make_update("AAPL", 190.0)}
    merged = await _merge_with_prev(updates)
    assert merged["AAPL"].prev_price == 190.0
    assert merged["AAPL"].change_pct == 0.0


@pytest.mark.asyncio
async def test_merge_with_prev_subsequent_poll():
    """Second poll should attach the previous cached price."""
    from app.market import cache as cache_module
    cache_module.price_cache._data.clear()

    # Seed the cache with a prior price
    await cache_module.price_cache.update("AAPL", make_update("AAPL", 190.0))

    updates = {"AAPL": make_update("AAPL", 191.0)}
    merged = await _merge_with_prev(updates)
    assert merged["AAPL"].prev_price == 190.0
    assert merged["AAPL"].price == 191.0
    assert abs(merged["AAPL"].change_pct - (1.0 / 190.0 * 100)) < 0.001
```

### 15.3 Simulator (`tests/market/test_simulator.py`)

```python
import asyncio
import math
import pytest
from app.market.simulator import MarketSimulator, SimulatorConfig, _DEFAULT_TICKERS
from app.market.interface import PriceUpdate


@pytest.mark.asyncio
async def test_get_prices_returns_all_default_tickers():
    sim = MarketSimulator()
    await sim.start()
    try:
        result = await sim.get_prices(list(_DEFAULT_TICKERS.keys()))
        assert set(result.keys()) == set(_DEFAULT_TICKERS.keys())
    finally:
        await sim.stop()


@pytest.mark.asyncio
async def test_all_prices_positive():
    sim = MarketSimulator()
    await sim.start()
    await asyncio.sleep(1.0)  # let the sim run for a second
    try:
        result = await sim.get_prices(list(_DEFAULT_TICKERS.keys()))
        for ticker, update in result.items():
            assert update.price > 0, f"{ticker} has non-positive price {update.price}"
    finally:
        await sim.stop()


@pytest.mark.asyncio
async def test_unknown_ticker_uses_fallback():
    sim = MarketSimulator()
    await sim.start()
    try:
        result = await sim.get_prices(["ZZZZ"])
        assert "ZZZZ" in result
        assert result["ZZZZ"].price == 100.0   # fallback seed price
    finally:
        await sim.stop()


@pytest.mark.asyncio
async def test_prices_near_seed_after_short_run():
    """After 1 second, prices should be within ±10% of seed values."""
    sim = MarketSimulator()
    await sim.start()
    await asyncio.sleep(1.0)
    try:
        result = await sim.get_prices(list(_DEFAULT_TICKERS.keys()))
        for ticker, update in result.items():
            seed = _DEFAULT_TICKERS[ticker].seed_price
            ratio = update.price / seed
            assert 0.90 <= ratio <= 1.10, (
                f"{ticker} price {update.price:.2f} deviates >10% from seed {seed:.2f}"
            )
    finally:
        await sim.stop()


def test_tick_produces_finite_prices():
    """Unit test for _tick() without running the async loop."""
    import random
    random.seed(42)
    sim = MarketSimulator()
    dt = 0.5 / (252 * 6.5 * 3600)
    sim._tick(dt)
    for ticker, price in sim._prices.items():
        assert math.isfinite(price), f"{ticker} produced non-finite price"
        assert price > 0, f"{ticker} produced non-positive price"


def test_sector_shocks_one_per_sector():
    sim = MarketSimulator()
    shocks = sim._draw_sector_shocks()
    expected_sectors = {"Tech", "EV/Tech", "Media", "Finance"}
    assert set(shocks.keys()) == expected_sectors


@pytest.mark.asyncio
async def test_stop_without_start_is_safe():
    sim = MarketSimulator()
    await sim.stop()   # Should not raise
```

### 15.4 Massive client (`tests/market/test_massive.py`)

```python
import pytest
import httpx
import respx
from datetime import datetime, timezone
from app.market.massive import MassiveAPIClient, MASSIVE_BASE_URL, SNAPSHOT_PATH

SNAPSHOT_URL = f"{MASSIVE_BASE_URL}{SNAPSHOT_PATH}"

MOCK_RESPONSE = {
    "status": "OK",
    "count": 2,
    "tickers": [
        {
            "ticker": "AAPL",
            "lastTrade": {"p": 190.85, "t": 1703001234000},
            "day": {"c": 190.60},
        },
        {
            "ticker": "MSFT",
            "lastTrade": {"p": 421.10, "t": 1703001234000},
            "day": {"c": 420.90},
        },
    ],
}


def make_client() -> MassiveAPIClient:
    return MassiveAPIClient(api_key="test-key")


def test_parse_response_uses_last_trade_price():
    client = make_client()
    result = client._parse_response(MOCK_RESPONSE)
    assert result["AAPL"].price == 190.85
    assert result["MSFT"].price == 421.10


def test_parse_response_falls_back_to_day_close():
    response = {
        "status": "OK",
        "tickers": [{"ticker": "JPM", "day": {"c": 195.30}}],
    }
    client = make_client()
    result = client._parse_response(response)
    assert result["JPM"].price == 195.30


def test_parse_response_skips_zero_price():
    response = {
        "status": "OK",
        "tickers": [{"ticker": "BAD", "lastTrade": {"p": 0.0}}],
    }
    client = make_client()
    result = client._parse_response(response)
    assert "BAD" not in result


def test_parse_response_skips_missing_ticker_field():
    response = {"status": "OK", "tickers": [{"lastTrade": {"p": 100.0}}]}
    client = make_client()
    result = client._parse_response(response)
    assert len(result) == 0


def test_timestamp_parsed_from_milliseconds():
    """lastTrade.t is Unix milliseconds — verify correct conversion."""
    item = {"ticker": "AAPL", "lastTrade": {"p": 190.0, "t": 1703001234000}}
    client = make_client()
    result = client._parse_response({"status": "OK", "tickers": [item]})
    ts = result["AAPL"].timestamp
    # Should parse as a valid ISO datetime
    parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    assert parsed.year == 2023   # 1703001234000 ms = Dec 19, 2023


@pytest.mark.asyncio
@respx.mock
async def test_get_prices_calls_correct_url():
    respx.get(SNAPSHOT_URL).mock(
        return_value=httpx.Response(200, json=MOCK_RESPONSE)
    )
    client = make_client()
    await client.start()
    result = await client.get_prices(["AAPL", "MSFT"])
    assert len(result) == 2
    request = respx.calls.last.request
    assert "apiKey=test-key" in str(request.url)
    await client.stop()


@pytest.mark.asyncio
@respx.mock
async def test_get_prices_raises_on_429():
    respx.get(SNAPSHOT_URL).mock(
        return_value=httpx.Response(429, json={"error": "rate limited"})
    )
    client = make_client()
    await client.start()
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await client.get_prices(["AAPL"])
    assert exc_info.value.response.status_code == 429
    await client.stop()


@pytest.mark.asyncio
async def test_get_prices_before_start_raises():
    client = make_client()
    with pytest.raises(RuntimeError, match="start()"):
        await client.get_prices(["AAPL"])


@pytest.mark.asyncio
async def test_stop_without_start_is_safe():
    client = make_client()
    await client.stop()   # Should not raise
```

### 15.5 `PriceUpdate` model (`tests/market/test_interface.py`)

```python
from app.market.interface import PriceUpdate


def test_change_pct_uptick():
    u = PriceUpdate(ticker="AAPL", price=191.0, prev_price=190.0, timestamp="t")
    assert abs(u.change_pct - (1.0 / 190.0 * 100)) < 0.001


def test_change_pct_downtick():
    u = PriceUpdate(ticker="AAPL", price=188.0, prev_price=190.0, timestamp="t")
    assert u.change_pct < 0


def test_change_pct_flat():
    u = PriceUpdate(ticker="AAPL", price=190.0, prev_price=190.0, timestamp="t")
    assert u.change_pct == 0.0


def test_change_pct_zero_prev_price():
    """Guard against division by zero on first tick."""
    u = PriceUpdate(ticker="AAPL", price=190.0, prev_price=0.0, timestamp="t")
    assert u.change_pct == 0.0
```

---

## 16. Implementation Checklist

In order, for the Market Data Engineer agent:

- [ ] Create `backend/app/market/` directory with `__init__.py`
- [ ] Implement `interface.py` — `PriceUpdate` and `MarketDataSource`
- [ ] Implement `cache.py` — `PriceCache` class and `price_cache` singleton
- [ ] Implement `loop.py` — `polling_loop` and `_merge_with_prev`
- [ ] Implement `simulator.py` — `SimulatorConfig`, `TickerConfig`, `MarketSimulator`
- [ ] Implement `massive.py` — `MassiveAPIClient`
- [ ] Implement `__init__.py` factory — `create_market_data_source()`
- [ ] Wire up lifespan in `main.py`
- [ ] Implement SSE route in `routes/stream.py`
- [ ] All unit tests pass: `uv run pytest tests/market/ -v`
- [ ] Manual smoke test: simulator runs, prices visible at `/api/stream/prices`
- [ ] (If Massive key available) Manual smoke test: real prices stream correctly
