# Market Data Backend — Code Review

**Date:** 2026-05-25  
**Reviewer:** Claude Sonnet 4.6  
**Scope:** `backend/app/market/` and `backend/tests/market/`  
**Commit:** `823b59b` — feat: implement market data backend (interface, simulator, Massive API)

---

## Executive Summary

The market data subsystem is well-structured and faithfully implements the layered architecture specified in the planning documents. The module boundaries are clean, the GBM mathematics are correct, and the test coverage is solid. All **55 tests pass** in 2.78 seconds.

Seven issues were found — two confirmed at medium severity, two confirmed at low severity, and three plausible at low severity. None block the simulator path (the default). The two medium findings both affect the Massive API path and should be fixed before that path is enabled in production.

---

## Test Results

```
55 passed in 2.78s
```

| Module | Tests | Result |
|--------|-------|--------|
| `test_cache.py` | 10 | ✅ All pass |
| `test_interface.py` | 7 | ✅ All pass |
| `test_loop.py` | 6 | ✅ All pass |
| `test_massive.py` | 18 | ✅ All pass |
| `test_simulator.py` | 14 | ✅ All pass |

Tests ran on Python 3.13.7 with pytest 9.0.3 / pytest-asyncio 1.3.0.

---

## Architecture Assessment

The implementation follows the design closely and makes several good choices:

**Strengths:**
- Clean separation between `interface.py`, `cache.py`, `loop.py`, `simulator.py`, and `massive.py` — each file has one job
- `PriceCache` uses `asyncio.Lock` throughout; all methods are async and lock-safe
- `update_many()` acquires the lock once for a batch, preventing half-visible updates
- `get_all()` returns a shallow copy — mutations to the returned dict don't corrupt the cache
- `MarketSimulator.start()` is correctly idempotent via `if self._task is not None and not self._task.done()`
- `_run_loop` re-raises `CancelledError` immediately, enabling clean FastAPI shutdown
- GBM uses the Itô correction `(μ - σ²/2)·dt` — the expected price is `S·exp(μ·dt)`, not biased by variance
- `dt` is computed using trading years (252 days × 6.5 h/day), not calendar time — correct scaling
- The `_merge_with_prev` mechanism cleanly separates price generation (simulator / Massive) from change tracking (cache layer)
- Factory in `__init__.py` is simple and correct

**Design divergence noted:**  
`MARKET_INTERFACE.md` specifies `_merge_with_prev` as a synchronous function taking `cached` as an explicit parameter. The implementation made it `async` and reads the global `price_cache` singleton internally. Both work correctly, but the design's version was easier to unit-test in isolation. The actual tests work around this via an `autouse` fixture that clears the global singleton.

---

## Findings

Findings are ranked most-severe first. Each is **CONFIRMED** (definitively wrong) or **PLAUSIBLE** (real failure scenario, may require unusual inputs).

---

### Finding 1 — No 429 back-off in polling loop **[CONFIRMED, Medium]**

**File:** `backend/app/market/loop.py:37–39`

```python
except Exception:
    logger.exception("Error in polling loop — will retry next cycle")
await asyncio.sleep(interval_seconds)   # 15.0 s for Massive free tier
```

**What should happen:** All three design documents (`MASSIVE_API.md`, `MARKET_DATA_DESIGN.md §7.1`, and the error-handling table in `§13`) specify a **60-second back-off** on HTTP 429 responses.

**What actually happens:** A `429 Too Many Requests` from Massive raises `httpx.HTTPStatusError`, which is caught by the generic `except Exception` block. The loop logs it and sleeps only `interval_seconds` (15 s on the free tier), then immediately retries. At 5 req/min budget this produces another 429, then another, creating a cascade that burns the rate limit indefinitely and never recovers to normal operation.

**Fix:**
```python
except httpx.HTTPStatusError as e:
    if e.response.status_code == 429:
        logger.warning("Massive API rate limited — backing off 60s")
        await asyncio.sleep(60)
    else:
        logger.exception("HTTP error in polling loop")
except Exception:
    logger.exception("Error in polling loop — will retry next cycle")
```
*(requires `import httpx` in `loop.py`)*

---

### Finding 2 — `MassiveAPIClient.start()` is not idempotent **[CONFIRMED, Medium]**

**File:** `backend/app/market/massive.py:38–40`

```python
async def start(self) -> None:
    self._client = httpx.AsyncClient(timeout=self._timeout)  # no guard
    logger.info("Massive API client started (base_url=%s)", self._base_url)
```

**The contract:** `MarketDataSource.start()` is documented as "Must be idempotent — safe to call even if already started." `MarketSimulator.start()` implements this correctly:

```python
async def start(self) -> None:
    if self._task is not None and not self._task.done():
        return
```

**What actually happens:** A second call to `MassiveAPIClient.start()` creates a fresh `httpx.AsyncClient` and silently overwrites `self._client`, leaving the previous client open (TCP connections, file descriptors, memory). The previous client is never explicitly closed — it relies on garbage-collection finalizers.

**Fix:**
```python
async def start(self) -> None:
    if self._client is not None:
        return
    self._client = httpx.AsyncClient(timeout=self._timeout)
    logger.info("Massive API client started (base_url=%s)", self._base_url)
```

---

### Finding 3 — `event_probability` comment says "per ticker" but implementation rolls once per tick **[CONFIRMED, Low]**

**File:** `backend/app/market/simulator.py:53` (comment) and `:164` (implementation)

```python
# SimulatorConfig:
event_probability: float = 0.001   # Per tick, per ticker  ← incorrect comment
```

```python
def _maybe_trigger_event(self) -> None:
    cfg = self._config
    if random.random() < cfg.event_probability:   # ONE roll for the entire tick
        ticker = random.choice(list(self._prices)) # ONE random ticker
```

**The discrepancy:** "Per tick, per ticker" implies each of the 10 default tickers independently has a 0.001 probability of being shocked on each tick. The actual implementation rolls *once globally* per tick and, if it fires, applies the event to *one* randomly chosen ticker.

**Consequence:** The effective per-ticker event probability is `event_probability / n_tickers ≈ 0.001 / 10 = 0.0001` — ten times lower than the comment implies. With the default 10 tickers, a specific ticker gets a shock approximately every 5,000 ticks (~42 minutes), not every 1,000 ticks (~8 minutes). Anyone tuning `event_probability` expecting per-ticker semantics will get far fewer events than intended.

**Note:** The `MARKET_DATA_DESIGN.md §6.3` comment "~1 event per ~13 minutes" is approximately consistent with the current implementation (1/0.001 ticks × 0.5 s/tick ≈ 8 min), so the frequency itself may have been intentional — but the field comment is misleading.

**Fix (option A — fix the comment to match implementation):**
```python
event_probability: float = 0.001   # Per tick, globally (one random ticker selected if fired)
```

**Fix (option B — fix the implementation to match "per ticker" semantics):**
```python
def _maybe_trigger_event(self) -> None:
    cfg = self._config
    for ticker in list(self._prices):
        if random.random() < cfg.event_probability:
            magnitude = random.uniform(cfg.event_magnitude_min, cfg.event_magnitude_max)
            direction = 1 if random.random() > 0.5 else -1
            self._prices[ticker] *= (1 + direction * magnitude)
```

---

### Finding 4 — Non-429 HTTP errors retried indefinitely with no escalation **[CONFIRMED, Low]**

**File:** `backend/app/market/loop.py:37`

A permanent `401 Unauthorized` or `403 Forbidden` from the Massive API (e.g. bad API key, plan downgrade) is caught by the generic `except Exception` handler, logged at ERROR level, and retried after `interval_seconds` — forever, with no maximum retry count, no circuit-breaker, and no way to distinguish a permanent error from a transient one.

**Consequence in production:** A bad API key would fill logs with repeated `ERROR` messages every 15 seconds, indefinitely, consuming the Massive free-tier quota and making the error effectively invisible compared to a clean startup failure.

**Suggested improvement:** Add a consecutive-error counter; after N consecutive errors raise an alert or set a flag visible at `/api/health`. At minimum, log the HTTP status code so operators can distinguish 401 from 503:

```python
except httpx.HTTPStatusError as e:
    logger.error(
        "Massive API HTTP %d in polling loop — will retry",
        e.response.status_code,
    )
```

---

### Finding 5 — Shared mutable `_FALLBACK_CONFIG` aliased across all dynamically added tickers **[PLAUSIBLE, Low]**

**File:** `backend/app/market/simulator.py:106`

```python
_FALLBACK_CONFIG = TickerConfig(seed_price=100.0, mu=0.10, sigma=0.30, sector="Tech")

async def get_prices(self, tickers):
    for ticker in tickers:
        if ticker not in self._prices:
            self._config.tickers[ticker] = _FALLBACK_CONFIG   # same object reference!
            self._prices[ticker] = _FALLBACK_CONFIG.seed_price
```

`TickerConfig` is a plain mutable dataclass (no `frozen=True`). Every unknown ticker added to the watchlist stores a reference to the *same* `_FALLBACK_CONFIG` object. In `_tick()`, `ticker_cfg` for all of them is the identical Python object.

If any future code mutates a per-ticker config field (e.g., to tune volatility for a newly added ticker via an admin API), it silently changes the `_FALLBACK_CONFIG` module-level singleton — affecting every other dynamically added ticker and making the fallback permanently wrong.

**Fix:**
```python
import dataclasses

self._config.tickers[ticker] = dataclasses.replace(_FALLBACK_CONFIG)
```

---

### Finding 6 — Walrus operator in `_extract_price` silently drops a price of `0.0` **[PLAUSIBLE, Low]**

**File:** `backend/app/market/massive.py:112`

```python
@staticmethod
def _extract_price(item: dict) -> float | None:
    last_trade = item.get("lastTrade") or {}
    if p := last_trade.get("p"):    # falsy for p=0.0 — falls through!
        return float(p)
    day = item.get("day") or {}
    if c := day.get("c"):           # falsy for c=0.0 — falls through!
        return float(c)
    return None
```

When `lastTrade.p` is exactly `0.0` (which the walrus operator evaluates as falsy), the function skips it and falls through to `day.c`. If `day.c` is also `0.0` or absent, `_extract_price` returns `None` and the ticker is silently dropped from the batch.

A real stock trading at $0.00 is essentially impossible, but the logic is unambiguously wrong and could also be triggered by an API returning `0` as an integer rather than a float, or during pre-market when `lastTrade.p` may legitimately be absent or zero.

**Fix:** Replace falsy checks with explicit `None` checks:
```python
if (p := last_trade.get("p")) is not None:
    return float(p)
...
if (c := day.get("c")) is not None:
    return float(c)
```

The existing `if not price or price <= 0` guard in `_parse_response` then correctly handles the explicit zero/negative case.

---

### Finding 7 — GBM sector correlation: config values are factor loadings (ρ), not pairwise correlations (ρ²) **[PLAUSIBLE, Low / Documentation]**

**File:** `backend/app/market/simulator.py:37–42` and `:147`

```python
_DEFAULT_CORRELATIONS = {
    "Tech": 0.60,    # ← labeled "ρ (correlation)" in design doc table
    ...
}

# In _tick():
# Sector-shock mixing: produces correct pairwise correlation = ρ²
z = rho * z_sector + math.sqrt(max(0.0, 1 - rho ** 2)) * z_idio
```

The inline comment at line 147 is mathematically correct: with this mixing formula, the pairwise correlation between two tickers in the same sector is `ρ²`, not `ρ`. For Tech with `ρ=0.60`, the actual pairwise return correlation between, say, AAPL and MSFT is **0.36**, not 0.60.

The `MARKET_DATA_DESIGN.md` table header labels the column `ρ (correlation)`, implying the numbers represent the target pairwise correlation. Anyone tuning the table to achieve a specific pairwise correlation (e.g., "I want Tech stocks to move together 60% of the time") will set values that produce a different result (36% for `ρ=0.60`).

**Fix (documentation):** Update `MARKET_DATA_DESIGN.md` table and the `_DEFAULT_CORRELATIONS` comment to clarify that the values are **factor loadings**, and note that pairwise correlation = ρ². Or rename the variable to `_DEFAULT_FACTOR_LOADINGS`.

**Fix (if 60% pairwise correlation is the intent):** Use `rho = sqrt(0.60) ≈ 0.775` as the factor loading to achieve 0.60 pairwise correlation.

---

## Test Coverage Assessment

### Strengths

- **`test_cache.py`** (10 tests): Comprehensive — covers update, overwrite, remove, missing keys, batching, isolation of the returned copy. Nothing missing.
- **`test_interface.py`** (7 tests): Covers all `change_pct` branches including zero-division guard, large moves, and field types.
- **`test_loop.py`** (6 tests): Tests `_merge_with_prev` (first poll, second poll, multiple tickers), `polling_loop` happy path, empty watchlist, and exception survival. The `autouse` fixture cleanly resets global state.
- **`test_simulator.py`** (14 tests): Good coverage including idempotent `start()`, unknown ticker fallback, `_tick()` correctness (zero-drift zero-vol), Ito correction, sector shocks.
- **`test_massive.py`** (18 tests): Thorough — price priority, fallback, zero/missing price skip, timestamp ms→ISO, uppercase normalization, 429/401 errors, `start()`/`stop()` lifecycle.

### Gaps

| Gap | Severity |
|-----|----------|
| No test for `MassiveAPIClient.start()` called twice (the idempotency bug in Finding 2) | Medium |
| No test for 429 triggering a 60-second back-off in `polling_loop` | Medium |
| No test for `_extract_price` receiving `lastTrade.p = 0.0` (the walrus issue in Finding 6) | Low |
| `test_prices_near_seed_after_short_run` uses `asyncio.sleep(1.0)` as a probabilistic bound — fine in practice but technically flaky if a random event fires twice on a high-sigma ticker (TSLA σ=0.65). The ±10% window is wide enough that this is extremely unlikely to fail. | Very Low |
| Test fixture (`clear_global_cache`) clears `_data` by direct dict mutation, bypassing `asyncio.Lock`. Functionally safe because the fixture runs between tests (no concurrent async tasks), but fragile if the fixture contract is ever changed. | Very Low |

---

## Error Handling Summary

| Scenario | Specified Behavior | Actual Behavior | Gap? |
|----------|--------------------|-----------------|------|
| Massive 429 | Sleep 60s, retry | Sleep `interval_seconds` (15s), retry | ✅ **Yes — Finding 1** |
| Massive 5xx | Log, sleep, retry | Log, sleep, retry | ✅ Correct |
| Massive 401/403 | (Not specified in detail) | Log, sleep, retry forever | ⚠️ Finding 4 |
| Ticker absent from API response | Omit; cache retains last price | Correct | ✅ |
| Simulator `_tick()` exception | Log, continue | Log, continue | ✅ |
| SSE client disconnect | `CancelledError` exits generator | Correct | ✅ |
| No tickers in watchlist | Skip `get_prices` call | Correct | ✅ |
| `start()` not called before `get_prices()` | `RuntimeError` | `RuntimeError` | ✅ |
| `start()` called twice on Massive client | Safe (idempotent per contract) | Leaks old client | ✅ **Yes — Finding 2** |
| Ticker removed from watchlist | `price_cache.remove(ticker)` should be called | `remove()` exists but wiring is future work (in the DELETE route) | ⚠️ Integration gap (out of scope for this PR) |

---

## Recommendations

**Must fix before enabling Massive API in production:**

1. Add 60-second back-off for 429 in `polling_loop` (Finding 1)
2. Add idempotency guard to `MassiveAPIClient.start()` (Finding 2)

**Should fix:**

3. Correct the `event_probability` comment to match implementation, or fix the implementation (Finding 3)
4. Add status-code-aware logging for non-429 HTTP errors (Finding 4)
5. Use `dataclasses.replace(_FALLBACK_CONFIG)` for dynamic ticker configs (Finding 5)
6. Replace walrus operator with explicit `is not None` in `_extract_price` (Finding 6)

**Nice to have:**

7. Clarify GBM correlation documentation — ρ vs ρ² labeling (Finding 7)
8. Add tests for `MassiveAPIClient.start()` called twice and 429 back-off behavior in `polling_loop`

---

## Verdict

**Simulator path (default): ✅ Ready**  
The simulator is correctly implemented and well-tested. All 55 tests pass. The GBM math, Ito correction, sector-shock mixing, and dynamic ticker support all work as designed. The event frequency comment mismatch (Finding 3) is low-severity and does not affect correctness.

**Massive API path: ⚠️ Fix Findings 1 and 2 before production use**  
The client itself is correctly implemented and tested with `respx` mocks. The two blocking issues are in the polling loop (no 429 back-off) and the client lifecycle (non-idempotent `start()`). Both are quick fixes requiring ~10 lines of code.
