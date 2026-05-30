---
phase: 02-backend-apis
reviewed: 2026-05-30T00:00:00Z
depth: standard
files_reviewed: 9
files_reviewed_list:
  - backend/app/routers/market.py
  - backend/app/routers/portfolio.py
  - backend/app/routers/watchlist.py
  - backend/app/db/database.py
  - backend/app/main.py
  - backend/tests/test_market_sse.py
  - backend/tests/test_db.py
  - backend/tests/test_portfolio.py
  - backend/tests/test_watchlist.py
findings:
  critical: 1
  warning: 4
  info: 3
  total: 8
status: issues_found
---

# Phase 02: Code Review Report

**Reviewed:** 2026-05-30
**Depth:** standard
**Files Reviewed:** 9
**Status:** issues_found

## Summary

The backend API layer is well-structured. Transaction handling is correct (the `with con:` block covers all DB mutations in `execute_trade`), input validation is present on both POST body models, and the SSE generator pattern is idiomatic for the installed fastapi-sse library. One critical bug exists in the sell-path position-cleanup logic: floating-point exact equality is used to decide whether to delete a position row, which will silently leave orphaned zero-quantity rows when fractional quantities are involved. Four warnings address missing validation on the DELETE path parameter, a duplicated portfolio computation, an inconsistent sync endpoint, and a missing keep-alive on the SSE stream. Three info items cover dead test code and import noise.

## Critical Issues

### CR-01: Floating-point exact equality used to decide position deletion

**File:** `backend/app/routers/portfolio.py:100`
**Issue:** When selling shares, the remaining quantity is computed as `remaining = existing["quantity"] - quantity` (line 99), then compared with `remaining == 0` (line 100) to decide whether to DELETE the position row or UPDATE it. Because both `existing["quantity"]` and `quantity` are IEEE 754 doubles (stored as REAL in SQLite, accepted as `float` in `TradeRequest`), this comparison fails whenever floating-point subtraction produces a residue. For example, buying 0.3 shares then selling 0.3 shares yields `remaining ≈ 5.55e-17` instead of `0.0`. The DELETE branch is skipped, the position row is updated to a near-zero (but non-zero) quantity, and the position appears in the portfolio forever. Any subsequent sell of a whole-number quantity will hit "Insufficient shares" against a position the user believes is closed.

**Fix:**
```python
EPSILON = 1e-9  # smaller than any meaningful fractional share quantity

remaining = existing["quantity"] - quantity
if remaining <= EPSILON:
    con.execute("DELETE FROM positions WHERE id=?", (existing["id"],))
else:
    con.execute(
        "UPDATE positions SET quantity=?, updated_at=? WHERE id=?",
        (remaining, now, existing["id"]),
    )
```

## Warnings

### WR-01: DELETE /watchlist/{ticker} path parameter has no length or character validation

**File:** `backend/app/routers/watchlist.py:62-65`
**Issue:** The POST endpoint normalizes and validates the ticker via `WatchlistRequest` (max 10 chars, non-empty). The DELETE endpoint accepts the raw path parameter and only calls `.upper().strip()`. A caller can supply a 200-character path segment; it will harmlessly miss in the DB but still touch `price_cache.remove`. More importantly, the validation contract is asymmetric: the same ticker string goes through different rules on add vs. remove. If validation rules ever tighten on the POST side, the DELETE side silently diverges.

**Fix:**
```python
@router.delete("/watchlist/{ticker}")
async def remove_ticker(ticker: str) -> dict:
    ticker = ticker.upper().strip()
    if not ticker or len(ticker) > 10:
        raise HTTPException(status_code=422, detail="Invalid ticker")
    ...
```

### WR-02: Portfolio value computation is duplicated between get_portfolio and _compute_total_value

**File:** `backend/app/routers/portfolio.py:128-152` and `191-234`
**Issue:** `_compute_total_value()` and the `get_portfolio()` endpoint both execute identical logic: fetch `cash_balance`, fetch positions, call `price_cache.get_many`, and compute `cash + sum(qty * price)`. If the fallback behavior (using `avg_cost` when price is missing) or rounding logic changes, both copies must be updated in sync. The two are already slightly inconsistent: `_compute_total_value` rounds the result at the end; `get_portfolio` rounds per-field and recomputes `total_value` from already-rounded components, which can produce a 1-cent discrepancy.

**Fix:** Have `get_portfolio` call `_compute_total_value()` for the total, or extract the shared DB-query portion into a helper that both call. At minimum, document the intentional duplication if it is kept.

### WR-03: SSE stream has no keep-alive / ping mechanism

**File:** `backend/app/routers/market.py:24-28`
**Issue:** The `price_event_stream` generator only yields events when the cache is non-empty. If the market data poller is slow to start, or all tickers are momentarily absent from the cache, the SSE connection is silent. Proxies and load balancers (nginx, AWS ALB, Cloudflare) typically close connections idle for 60-120 seconds. The `fastapi.sse` library provides `KEEPALIVE_COMMENT` and `_PING_INTERVAL` for exactly this purpose, but neither is used. A silent connection drop forces the client's `EventSource` to reconnect with exponential backoff, causing a gap in price updates.

**Fix:**
```python
from fastapi.sse import EventSourceResponse, ServerSentEvent, KEEPALIVE_COMMENT

async def price_event_stream() -> AsyncIterable[ServerSentEvent]:
    while True:
        updates = await price_cache.get_all()
        if updates:
            for ticker, update in updates.items():
                yield ServerSentEvent(data=update.model_dump(), event="price_update")
        else:
            # Keep connection alive when cache is empty
            yield ServerSentEvent(comment="ping")
        await asyncio.sleep(0.5)
```

### WR-04: add_ticker is a sync endpoint; all others are async

**File:** `backend/app/routers/watchlist.py:46`
**Issue:** `add_ticker` is declared `def` (synchronous) while every other endpoint in both routers is `async def`. FastAPI runs sync route handlers in a threadpool executor, which means `add_ticker` acquires a worker thread on each call. This is not incorrect, but it is inconsistent and means any future addition of an `await` call inside this function will silently do nothing (the function will not be treated as a coroutine). It also makes the pattern harder to follow.

**Fix:** Change to `async def add_ticker(...)` to match all other endpoints. The SQLite call inside is synchronous but brief, so running it on the event loop is acceptable for this workload (consistent with every other endpoint in the codebase).

## Info

### IN-01: test_watchlist.py — dead code and unused imports

**File:** `backend/tests/test_watchlist.py:50-55`
**Issue:** `test_get_watchlist` contains two dead-code lines: line 50-51 instantiates an `AsyncMock` context manager and immediately discards it with `as _: pass`, and line 54 imports `app.market.cache as cache_mod` then line 55 assigns `monkeypatch_cache = AsyncMock(return_value={})` — neither is ever used. Additionally, `get_watchlist_tickers` is imported from `app.db.database` (line 8) but never called in any test body.

**Fix:** Remove lines 50-51, 54-55, and the unused `get_watchlist_tickers` import.

### IN-02: test_watchlist.py uses convoluted __import__ pattern instead of top-level import

**File:** `backend/tests/test_watchlist.py:57, 83, 181, 207`
**Issue:** Tests use `__import__("unittest.mock", fromlist=["patch"]).patch.object(...)` in four places. `AsyncMock` is already imported at the top of the file; `patch` should be too. This pattern is harder to read and provides no benefit over a normal import.

**Fix:**
```python
# At the top of the file, replace the existing import:
from unittest.mock import AsyncMock, patch

# Then in each test, simply:
with patch.object(price_cache, "get_many", AsyncMock(return_value={})):
    ...
```

### IN-03: test_market_sse.py does not assert change_pct value

**File:** `backend/tests/test_market_sse.py:46-56`
**Issue:** `test_sse_event_value` asserts `ticker` and `price` but not `change_pct`, which is the only computed field on `PriceUpdate`. A regression in the `change_pct` formula (division by zero guard, wrong sign, etc.) would go undetected. The test setup provides both `price=190.0` and `prev_price=189.0`, making the expected value trivially calculable.

**Fix:** Add:
```python
assert event.data["change_pct"] == pytest.approx((190.0 - 189.0) / 189.0 * 100)
```

---

_Reviewed: 2026-05-30_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
