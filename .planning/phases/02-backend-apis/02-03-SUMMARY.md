---
phase: 02-backend-apis
plan: "03"
subsystem: api
tags: [fastapi, sqlite, pydantic, watchlist, rest]

requires:
  - phase: 02-backend-apis
    provides: "database schema (watchlist table), price cache singleton, portfolio router patterns"

provides:
  - "GET /api/watchlist endpoint returning tickers with cached prices"
  - "POST /api/watchlist endpoint adding tickers (uppercased, idempotent)"
  - "DELETE /api/watchlist/{ticker} endpoint removing from DB and clearing cache"
  - "WatchlistRequest Pydantic model with ticker validation"
  - "Watchlist router registered in FastAPI app"

affects: [03-frontend, chat-router, sse-stream]

tech-stack:
  added: []
  patterns:
    - "Watchlist INSERT OR IGNORE for idempotent adds with no duplicate rows"
    - "DELETE endpoint clears price_cache.remove() to prevent stale data"
    - "No signaling needed on add — polling loop re-queries DB each cycle"
    - "Ticker normalization: .upper().strip() on both POST body and DELETE path param"

key-files:
  created:
    - backend/app/routers/watchlist.py
    - backend/tests/test_watchlist.py
  modified:
    - backend/app/main.py

key-decisions:
  - "INSERT OR IGNORE for idempotent ticker adds — no signaling or cache invalidation needed on add"
  - "DELETE explicitly removes from price_cache to prevent stale prices serving deleted tickers"
  - "WatchlistRequest mirrors TradeRequest validator pattern — uppercase+strip, ValueError→422 for bad input"

patterns-established:
  - "Router pattern: APIRouter(prefix='/api', tags=[...]) consistent with health/market/portfolio routers"
  - "Ticker normalization applied at both model-validator level (POST) and path-param level (DELETE)"

requirements-completed: [WTCH-01, WTCH-02, WTCH-03, TEST-04]

duration: 3min
completed: 2026-05-30
---

# Phase 02 Plan 03: Watchlist CRUD Endpoints Summary

**Watchlist GET/POST/DELETE REST endpoints with price-cache integration, idempotent adds via INSERT OR IGNORE, and cache eviction on delete**

## Performance

- **Duration:** 3 min
- **Started:** 2026-05-30T04:51:51Z
- **Completed:** 2026-05-30T04:52:27Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Implemented watchlist router with GET/POST/DELETE endpoints covering all WTCH requirements
- WatchlistRequest validates tickers: uppercases, strips whitespace, rejects empty or >10 char input (422)
- GET endpoint returns cached prices for each ticker (null when cache empty — correct for fresh state)
- POST uses INSERT OR IGNORE for idempotent ticker adds with no extra signaling
- DELETE removes from DB and calls price_cache.remove() to evict stale cache entries
- 7 tests cover all behaviors including lowercase normalization, idempotency, and cache eviction

## Task Commits

Each task was committed atomically:

1. **RED - Watchlist test suite** - `bf04bcf` (test)
2. **GREEN - Watchlist router + main.py registration** - `90ce03d` (feat)

_TDD plan: RED commit (failing tests) followed by GREEN commit (implementation)_

## Files Created/Modified
- `backend/app/routers/watchlist.py` - GET/POST/DELETE endpoints + WatchlistRequest model
- `backend/tests/test_watchlist.py` - 7 tests covering all behaviors including edge cases
- `backend/app/main.py` - Added watchlist router import and include_router registration

## Decisions Made
- Used INSERT OR IGNORE for idempotent adds — matches seed.py convention and avoids needing duplicate-check logic
- DELETE endpoint awaits price_cache.remove() to prevent stale prices from serving removed tickers
- WatchlistRequest mirrors TradeRequest pattern (uppercase+strip, ValueError for bad input) for consistency

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All Phase 2 REST endpoints complete (health, market SSE, portfolio, watchlist)
- Full backend test suite green: 94 tests passing
- Frontend can consume /api/watchlist GET/POST/DELETE endpoints
- Chat router (plan 04) can call watchlist add/remove via the existing route handlers

---
*Phase: 02-backend-apis*
*Completed: 2026-05-30*
