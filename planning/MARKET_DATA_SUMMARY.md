# Market Data Backend — Architecture Summary

**As of:** 2026-05-25  
**Scope:** `backend/app/market/`  
**Tests:** 59 passing

---

## Overview

The market data subsystem provides real-time (or simulated) price data to the rest of the application. It is built around a common abstract interface so the rest of the backend is completely agnostic to whether prices come from the simulator or a real API.

Two implementations exist:

| Source | When active | Update rate |
|--------|------------|-------------|
| `MarketSimulator` | `MASSIVE_API_KEY` not set (default) | 500ms |
| `MassiveAPIClient` | `MASSIVE_API_KEY` set in `.env` | 15s (free tier) |

---

## Modules

### `interface.py`

Defines the contract the rest of the app depends on.

- **`PriceUpdate`** — Pydantic model: `ticker`, `price`, `prev_price`, `timestamp` (ISO UTC), and a computed `change_pct` field.
- **`MarketDataSource`** — Abstract base class with three methods: `start()`, `stop()`, `get_prices(tickers)`. Both implementations must be idempotent on `start()`.

### `simulator.py`

Default data source. Runs entirely in-process with no external dependencies.

- **`TickerConfig`** — Per-ticker GBM parameters: `seed_price`, `mu` (annual drift), `sigma` (annual volatility), `sector`.
- **`SimulatorConfig`** — Top-level config: ticker map, sector correlations, tick interval, event settings.
- **`MarketSimulator`** — Implements `MarketDataSource`. On `start()`, launches an `asyncio` background task that calls `_tick()` every 500ms.

**GBM implementation:**

```
S(t+dt) = S(t) · exp((μ - σ²/2)·dt + σ·√dt·Z)
```

- `dt` is scaled in **trading years** (252 days × 6.5 h/day × 3600 s/h) — not calendar time.
- The `μ - σ²/2` Itô correction keeps the expected price unbiased by variance.
- `Z` is a weighted mix of a sector shock and an idiosyncratic shock:
  ```
  Z = ρ·Z_sector + √(1-ρ²)·Z_idio
  ```
  The values in `_DEFAULT_CORRELATIONS` are **factor loadings** (ρ), not pairwise correlations. Pairwise correlation between two tickers in the same sector = ρ².

**Random events:** With probability `event_probability` (default 0.001 per tick, globally), one random ticker is shocked by 2–5% up or down. This is applied before the GBM step so the price continues naturally from the new level.

**Default tickers and parameters:**

| Ticker | Seed | μ | σ | Sector |
|--------|------|---|---|--------|
| AAPL | $190 | 12% | 28% | Tech |
| MSFT | $420 | 13% | 26% | Tech |
| NVDA | $875 | 20% | 55% | Tech |
| META | $510 | 15% | 38% | Tech |
| GOOGL | $175 | 11% | 27% | Tech |
| AMZN | $185 | 14% | 32% | Tech |
| TSLA | $250 | 10% | 65% | EV/Tech |
| NFLX | $640 | 12% | 40% | Media |
| JPM | $195 | 9% | 22% | Finance |
| V | $275 | 10% | 20% | Finance |

Unknown tickers added at runtime fall back to: seed $100, μ=10%, σ=30%, sector=Tech.

### `massive.py`

Optional live-data source. Wraps the Massive (Polygon.io) REST API using `httpx.AsyncClient`.

- Polls `/v2/snapshot/locale/us/markets/stocks/tickers` with the current watchlist.
- `_extract_price()` checks `lastTrade.p`, then `day.c`, using explicit `is not None` guards (so a price of `0.0` is not silently skipped).
- Normalises tickers to uppercase, filters prices ≤ 0.
- `start()` is idempotent — a second call is a no-op.

### `cache.py`

In-memory store for the latest `PriceUpdate` per ticker. All methods are `async` and protected by a single `asyncio.Lock`.

- **`update_many()`** acquires the lock once per batch — no half-visible updates.
- **`get_all()`** returns a shallow copy — callers cannot corrupt the cache.
- **Module-level singleton** `price_cache` is imported by `loop.py` and the SSE endpoint.

### `loop.py`

Bridges the data source and the cache. A single `asyncio` task runs `polling_loop()` for the lifetime of the application.

```
while True:
    tickers = get_tickers()          # current watchlist — called every cycle
    updates = await source.get_prices(tickers)
    merged  = await _merge_with_prev(updates)   # attach previous price for change_pct
    await price_cache.update_many(merged)
    await asyncio.sleep(interval_seconds)
```

Error handling:
- **HTTP 429** → 60-second back-off, then continue.
- **Other HTTP errors** → log with status code, continue at normal interval.
- **Any other exception** → log, continue.

### `__init__.py`

Factory: reads `MASSIVE_API_KEY` from the environment and returns the correct `MarketDataSource` instance.

```python
from app.market import create_market_source
source = create_market_source()  # MarketSimulator or MassiveAPIClient
```

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Abstract interface | SSE endpoint, polling loop, and tests are all source-agnostic |
| Asyncio background task (not thread) | Single-threaded async model; no locking needed between GBM and the event loop |
| `asyncio.Lock` in `PriceCache` | Cache is written by the polling task and read by SSE handlers concurrently |
| `_merge_with_prev` in loop, not source | Price sources return raw prices; change tracking is a cache-layer concern |
| `get_tickers` callable (not a list) | Newly added tickers are picked up each cycle without restarting the loop |
| Trading-year `dt` | Correct annualisation; μ and σ are interpretable real-world numbers |
| `dataclasses.replace(_FALLBACK_CONFIG)` | Each dynamically added ticker gets its own config copy — no shared mutable alias |

---

## Test Suite

59 tests across 5 files. Run with:

```bash
cd backend
uv run --group dev pytest
```

| File | Tests | What it covers |
|------|-------|---------------|
| `test_cache.py` | 10 | update, overwrite, remove, batch atomicity, copy isolation |
| `test_interface.py` | 7 | `change_pct` branches, zero-division guard, field types |
| `test_loop.py` | 9 | `_merge_with_prev` (first/second poll, multiple tickers), happy path, empty watchlist, exception survival, 429 back-off |
| `test_massive.py` | 19 | price priority, walrus/zero guard, timestamp conversion, uppercase normalisation, 429/401 errors, start/stop lifecycle, idempotent `start()` |
| `test_simulator.py` | 14 | idempotent `start()`, unknown ticker fallback, GBM correctness (zero-drift zero-vol), Itô correction, sector shocks |

---

## Live Demo

A Rich terminal demo runs the simulator for 6 tickers and displays live prices, sparklines, and a random-event log.

```bash
cd backend
uv run --group dev python demo.py
```

The demo uses an elevated `event_probability` (4% per tick vs the production default of 0.1%) so shock events appear within seconds rather than minutes.

Press **Ctrl-C** to exit.

---

## Downstream Usage Examples

### 1. Read all cached prices (SSE endpoint pattern)

```python
from app.market.cache import price_cache

all_prices = await price_cache.get_all()
for ticker, upd in all_prices.items():
    print(f"{ticker}: ${upd.price:.2f}  ({upd.change_pct:+.3f}%)")
```

### 2. Start the simulator and poll it directly

```python
import asyncio
from app.market.simulator import MarketSimulator

async def main():
    sim = MarketSimulator()
    await sim.start()
    await asyncio.sleep(2)
    prices = await sim.get_prices(["AAPL", "TSLA"])
    for ticker, upd in prices.items():
        print(f"{ticker}: ${upd.price:.2f}")
    await sim.stop()

asyncio.run(main())
```

### 3. Use the factory (simulator or Massive, driven by env var)

```python
from app.market import create_market_source
from app.market.loop import polling_loop

source = create_market_source()
await source.start()

watchlist = ["AAPL", "MSFT", "NVDA"]
task = asyncio.create_task(
    polling_loop(source, get_tickers=lambda: watchlist, interval_seconds=0.5)
)
# price_cache is now updated automatically every 500ms
```

### 4. Subscribe to the SSE stream (frontend pattern)

```javascript
const es = new EventSource("/api/stream/prices");
es.onmessage = (e) => {
    const { ticker, price, change_pct } = JSON.parse(e.data);
    updateUI(ticker, price, change_pct);
};
```
