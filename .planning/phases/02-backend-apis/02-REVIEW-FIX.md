---
phase: 02-backend-apis
fixed_at: 2026-05-30T00:00:00Z
review_path: .planning/phases/02-backend-apis/02-REVIEW.md
iteration: 1
findings_in_scope: 5
fixed: 5
skipped: 0
status: all_fixed
---

# Phase 02: Code Review Fix Report

**Fixed at:** 2026-05-30
**Source review:** .planning/phases/02-backend-apis/02-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 5
- Fixed: 5
- Skipped: 0

## Fixed Issues

### CR-01: Floating-point exact equality used to decide position deletion

**Files modified:** `backend/app/routers/portfolio.py`
**Commit:** 3ee8819
**Applied fix:** Replaced `if remaining == 0:` with `EPSILON = 1e-9` and `if remaining <= EPSILON:` in the sell-path of `execute_trade`. Positions with IEEE 754 floating-point residues (e.g. `5.55e-17` from `0.3 - 0.3`) are now correctly deleted rather than left as phantom near-zero rows.

### WR-01: DELETE /watchlist/{ticker} path parameter has no length or character validation

**Files modified:** `backend/app/routers/watchlist.py`
**Commit:** 9dec74a
**Applied fix:** Added `from fastapi import APIRouter, HTTPException` (was missing `HTTPException`) and inserted a guard in `remove_ticker` after `.upper().strip()`: raises `HTTPException(status_code=422, detail="Invalid ticker")` when ticker is empty or longer than 10 characters. Matches the constraint enforced by `WatchlistRequest` on the POST side.

### WR-02: Portfolio value computation is duplicated

**Files modified:** `backend/app/routers/portfolio.py`
**Commit:** ab4425d
**Applied fix:** Removed the `total_market_value` accumulator from `get_portfolio()` and replaced `total_value = round(profile["cash_balance"] + total_market_value, 2)` with `total_value = await _compute_total_value()`. The per-position loop is retained for building the positions list, but the authoritative total now comes from the single shared helper, eliminating the potential 1-cent rounding discrepancy.

### WR-03: SSE stream has no keep-alive / ping mechanism

**Files modified:** `backend/app/routers/market.py`
**Commit:** e359bcb
**Applied fix:** Wrapped the existing `for ticker, update in updates.items()` loop in `if updates:` and added an `else` branch that yields `ServerSentEvent(comment="ping")`. This sends an SSE comment line on every 500ms tick when the cache is empty, preventing proxy and load-balancer idle-connection timeouts.

### WR-04: add_ticker is sync (def) while all others are async def

**Files modified:** `backend/app/routers/watchlist.py`
**Commit:** 1e593a6
**Applied fix:** Changed `def add_ticker(req: WatchlistRequest)` to `async def add_ticker(req: WatchlistRequest)`. No other changes needed; the body contains only synchronous SQLite calls, which is consistent with every other endpoint in the codebase.

---

_Fixed: 2026-05-30_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
