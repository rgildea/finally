---
plan: 01-01
phase: 01-backend-foundation
status: complete
---

## Summary

Implemented the SQLite database layer (`backend/app/db/`) with schema, seed, and connection logic.

## What Was Built

- `backend/app/db/__init__.py` — empty package marker
- `backend/app/db/schema.py` — `CREATE_TABLES` list with 6 `CREATE TABLE IF NOT EXISTS` statements (users_profile, watchlist, positions, trades, portfolio_snapshots, chat_messages); watchlist has `UNIQUE(user_id, ticker)` for idempotent seeding
- `backend/app/db/seed.py` — `seed(con)` using `INSERT OR IGNORE` for default user (cash_balance=10000.0) and 10 default tickers; `INSERT OR REPLACE` deliberately avoided to preserve cash balance across restarts
- `backend/app/db/database.py` — `DB_PATH` from env, `get_connection()` with WAL+foreign keys, `get_watchlist_tickers()` re-querying each call, `init_db()` creating tables + seeding
- `backend/tests/test_db.py` — 6 tests covering table creation, seed data correctness, double-init idempotency, cash balance preservation, and watchlist callable

## Test Results

65/65 tests pass (59 existing market tests + 6 new db tests)

## Key Files Created

- `backend/app/db/database.py` — DB_PATH, get_connection(), get_watchlist_tickers(), init_db()
- `backend/app/db/schema.py` — CREATE_TABLES (6 entries)
- `backend/app/db/seed.py` — seed() with INSERT OR IGNORE
- `backend/tests/test_db.py` — all 6 tests passing

## Self-Check: PASSED

All must_haves satisfied:
- init_db() on empty DB creates all six tables ✓
- Default user profile exists with cash_balance=10000.0 ✓
- Exactly 10 default watchlist tickers ✓
- Second init_db() neither errors nor duplicates rows nor resets cash_balance ✓
- get_watchlist_tickers() reads from DB each call ✓
