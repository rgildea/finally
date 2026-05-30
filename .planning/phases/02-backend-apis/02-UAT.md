---
status: complete
phase: 02-backend-apis
source: [02-01-SUMMARY.md, 02-02-SUMMARY.md, 02-03-SUMMARY.md]
started: 2026-05-30T05:25:08Z
updated: 2026-05-30T05:45:00Z
---

## Current Test

<!-- OVERWRITE each test - shows where we are -->

[testing complete]

## Tests

### 1. Cold Start Smoke Test
expected: Kill any running server/service. Clear ephemeral state (temp DBs, caches, lock files). Start the application from scratch. Server boots without errors, any seed/migration completes, and a primary query (health check, homepage load, or basic API call) returns live data.
result: pass

### 2. SSE Price Stream
expected: Connect to GET /api/stream/prices (e.g., via curl or browser EventSource). The server sends a continuous stream of price_update events. Each event includes ticker, price, prev_price, change_pct, and timestamp fields. New events arrive roughly every 500ms.
result: pass

### 3. View Portfolio
expected: GET /api/portfolio returns JSON with cash balance (~$10,000 for a fresh DB), a positions array (empty on fresh start), and a total_value field. If you have open positions, each entry shows ticker, quantity, avg_cost, current_price, unrealized_pnl, pnl_pct, and market_value, all rounded to 2 decimal places.
result: pass

### 4. Buy Shares
expected: POST /api/portfolio/trade with body {"ticker": "AAPL", "side": "buy", "quantity": 5} returns 200 with the trade details. GET /api/portfolio immediately after shows a new AAPL position with quantity 5 and cash reduced by 5 × the purchase price.
result: pass

### 5. Sell Shares
expected: POST /api/portfolio/trade with body {"ticker": "AAPL", "side": "sell", "quantity": 5} (after buying 5) returns 200. GET /api/portfolio shows AAPL position gone (sell-to-zero removes the row) and cash increased by 5 × the sale price.
result: pass

### 6. Trade Validation Errors
expected: POST /api/portfolio/trade with quantity -1 returns 422. POST to buy a ticker not in the price cache returns 503. POST to sell more shares than you own returns 400.
result: pass

### 7. Portfolio History
expected: GET /api/portfolio/history returns a list of portfolio_snapshots ordered chronologically. Each entry has total_value and recorded_at. At least one snapshot exists (recorded automatically after each successful trade or by the 30s background task).
result: pass

### 8. View Watchlist
expected: GET /api/watchlist returns a list of tickers. A fresh DB shows the 10 default tickers (AAPL, GOOGL, MSFT, AMZN, TSLA, NVDA, META, JPM, V, NFLX). Each entry has ticker and a price field (may be null if the price cache is not yet populated).
result: pass

### 9. Add Ticker to Watchlist
expected: POST /api/watchlist with body {"ticker": "PYPL"} returns 200/201. GET /api/watchlist shows PYPL in the list. Posting the same ticker again is idempotent — no error, no duplicate.
result: pass

### 10. Remove Ticker from Watchlist
expected: DELETE /api/watchlist/PYPL returns 200. GET /api/watchlist no longer shows PYPL. If you try to delete a ticker that doesn't exist, no error is thrown (or a graceful 404).
result: pass

## Summary

total: 10
passed: 10
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps

[none yet]
