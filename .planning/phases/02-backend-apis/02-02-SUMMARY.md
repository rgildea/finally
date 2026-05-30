---
phase: 02-backend-apis
plan: "02"
subsystem: api
tags: [fastapi, sqlite, portfolio, trade-execution, pnl, snapshot-recorder]

# Dependency graph
requires:
  - phase: 02-backend-apis
    plan: "01"
    provides: busy_timeout in get_connection(), market router registered in main.py

provides:
  - execute_trade: atomic buy/sell with weighted avg cost, cash debit/credit, trade log
  - GET /api/portfolio: positions list with live P&L (unrealized_pnl, pnl_pct), cash, total_value
  - POST /api/portfolio/trade: cache-priced trade execution with 503/400/422 error paths
  - GET /api/portfolio/history: chronological portfolio_snapshots
  - snapshot_recorder: background asyncio task recording total_value every 30s
  - TradeRequest: Pydantic model validating ticker/side/quantity

affects:
  - 02-03 (watchlist APIs can follow the same router pattern)
  - frontend (portfolio panel, positions table, trade bar, P&L chart all consume these endpoints)
  - 03-chat (AI trade execution calls execute_trade directly)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "execute_trade: synchronous helper with with con: atomic block; price passed in from caller"
    - "Portfolio GET: async def required because price_cache.get_many() must be awaited"
    - "snapshot_recorder: asyncio.create_task in lifespan; sleeps 30s then computes and writes"
    - "_compute_total_value/_write_snapshot: factored shared helpers used by both GET portfolio and snapshot_recorder"
    - "Price fallback: avg_cost used as current_price when ticker not in cache (fresh startup)"

key-files:
  created:
    - backend/app/routers/portfolio.py
    - backend/tests/test_portfolio.py
  modified:
    - backend/app/main.py

key-decisions:
  - "execute_trade is synchronous (price resolved by async caller before entry) — keeps atomic block simple with no await inside with con:"
  - "snapshot_recorder sleeps before first write (30s delay on startup) — acceptable per research Assumption A2"
  - "POST /api/portfolio/trade also records a snapshot after a successful trade for immediate P&L chart update"
  - "sell-to-zero removes the position row (DELETE vs UPDATE quantity=0) — cleaner downstream query logic"
  - "_compute_total_value and _write_snapshot factored as shared helpers — avoids duplicate cash+position math"

requirements-completed: [PORT-01, PORT-02, PORT-03, PORT-04, PORT-05, PORT-06, TEST-01, TEST-02, TEST-04]

# Metrics
duration: ~4min
completed: "2026-05-30"
---

# Phase 2 Plan 02: Portfolio APIs and Trade Execution Summary

**Atomic trade execution, portfolio P&L endpoint, history, and background snapshot recorder — trading engine complete**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-05-30T04:40:47Z
- **Completed:** 2026-05-30T04:44:43Z
- **Tasks:** 2 (both TDD)
- **Files modified:** 3

## Accomplishments

- `execute_trade`: synchronous helper with `with con:` atomicity — buy/sell, weighted avg cost, cash debit/credit, trades log row, all or nothing
- `TradeRequest`: Pydantic model with three field_validators (normalize_ticker, validate_side, validate_quantity) → 422 before any DB access
- `GET /api/portfolio`: async endpoint, joins DB positions with price_cache, returns unrealized_pnl/pnl_pct/market_value per position, monetary values rounded to 2dp, fallback to avg_cost when cache miss
- `POST /api/portfolio/trade`: resolves price from cache (503 if missing), calls execute_trade (400 on ValueError), records snapshot after success
- `GET /api/portfolio/history`: returns portfolio_snapshots ordered chronologically
- `snapshot_recorder`: asyncio background task sleeping 30s then writing total_value to portfolio_snapshots
- `_compute_total_value` / `_write_snapshot`: factored shared helpers
- `main.py` updated: portfolio_router registered, snapshot_task created/cancelled in lifespan
- Full suite: 87 tests passing (72 existing + 15 new portfolio tests)

## Task Commits

Each task followed TDD (RED → GREEN):

1. **Task 1: Trade execution RED** - `ad88ea6` (test)
2. **Task 1: Trade execution GREEN** - `0c6d485` (feat)
3. **Task 2: Endpoints RED** - `bc9896d` (test)
4. **Task 2: Endpoints GREEN** - `0208c8d` (feat)

## Files Created/Modified

- `backend/app/routers/portfolio.py` — TradeRequest, execute_trade, _compute_total_value, _write_snapshot, snapshot_recorder, GET /api/portfolio, POST /api/portfolio/trade, GET /api/portfolio/history
- `backend/tests/test_portfolio.py` — 15 tests covering trade logic, P&L math, endpoint shapes, error paths, snapshot
- `backend/app/main.py` — added portfolio_router import/registration, snapshot_task in lifespan

## Decisions Made

- `execute_trade` is synchronous (price pre-resolved by async caller) — atomic `with con:` block contains no awaits, which simplifies rollback semantics
- Sell-to-zero DELETEs the position row rather than leaving quantity=0 — cleaner downstream query results
- Snapshot also recorded after each successful trade (in addition to the 30s background task) — ensures P&L chart updates immediately after a trade
- `_compute_total_value` and `_write_snapshot` factored as module-level helpers so both the snapshot_recorder and the trade endpoint share the same math

## Deviations from Plan

None — plan executed exactly as written. All behaviors match the task specifications.

## Known Stubs

None. All endpoints return live data from DB and price_cache.

## Threat Flags

No new threat surfaces beyond those covered in the plan's threat model.
All three mitigations implemented:
- T-02-03: TradeRequest validators (422 before DB) — DONE
- T-02-04: Parameterized queries + `with con:` atomicity — DONE
- T-02-05: Price from price_cache only, 503 if missing — DONE

---

## Self-Check

Files exist:
- backend/app/routers/portfolio.py — FOUND
- backend/tests/test_portfolio.py — FOUND
- backend/app/main.py (modified) — FOUND

Commits exist:
- ad88ea6 — FOUND
- 0c6d485 — FOUND
- bc9896d — FOUND
- 0208c8d — FOUND

Test suite: 87/87 passed

## Self-Check: PASSED

---
*Phase: 02-backend-apis*
*Completed: 2026-05-30*
