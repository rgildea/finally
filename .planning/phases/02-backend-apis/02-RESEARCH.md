# Phase 2: Backend APIs - Research

**Researched:** 2026-05-29
**Domain:** FastAPI SSE streaming, SQLite trade execution, portfolio math, async testing
**Confidence:** HIGH

## Summary

Phase 2 builds all REST and SSE endpoints on top of the Phase 1 foundation (FastAPI app, SQLite database with WAL mode, price cache, polling loop). The codebase is clean and well-structured: the market layer is complete and validated, the database layer is solid, and the Phase 1 test patterns provide a clear template for Phase 2 tests.

FastAPI 0.136.3 (installed) ships a native `EventSourceResponse` from `fastapi.sse` — the new idiomatic pattern requires `response_class=EventSourceResponse` and an `AsyncIterable[ServerSentEvent]` generator, replacing the older `StreamingResponse` + `f"data: ...\n\n"` approach. Keepalives (15-second comment pings) and cache-control headers are automatic.

Trade execution uses SQLite's `with con:` context manager for atomicity — all three mutations (positions upsert, cash debit/credit, trades insert) succeed or none do. WAL mode is already enabled via `get_connection()`, enabling concurrent readers during write transactions.

For SSE testing, direct HTTP stream tests with `httpx.AsyncClient` are known to hang on infinite generators. The recommended approach is (a) unit-test the SSE generator function's output logic directly and (b) use the synchronous `TestClient` with bounded `iter_lines()` for format-level integration checks.

**Primary recommendation:** Three `APIRouter` modules (`market`, `portfolio`, `watchlist`), one background snapshot task added to lifespan alongside the existing polling loop. No new packages required.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| SSE price streaming | API / Backend | — | Reads from in-memory `price_cache` singleton; no DB involvement |
| Portfolio read (GET /api/portfolio) | API / Backend | Database / Storage | Joins price_cache data with DB positions + cash |
| Trade execution (POST /api/portfolio/trade) | API / Backend | Database / Storage | Atomic SQLite transaction; price from cache |
| Portfolio snapshot recording | API / Backend | Database / Storage | Background asyncio task writing to portfolio_snapshots table |
| Watchlist CRUD | API / Backend | Database / Storage | DB is source of truth; polling loop reads it each cycle |
| P&L history (GET /api/portfolio/history) | API / Backend | Database / Storage | Pure DB read of portfolio_snapshots |

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| STRM-01 | GET /api/stream/prices SSE at ~500ms cadence | FastAPI 0.136.3 EventSourceResponse + asyncio.sleep(0.5) loop |
| STRM-02 | Each SSE event: ticker, price, prev_price, change_pct, timestamp | PriceUpdate.model_dump() already has all fields; ServerSentEvent(data=...) |
| STRM-03 | SSE reads from price_cache singleton, not data source | price_cache.get_all() in the generator loop |
| PORT-01 | GET /api/portfolio: positions, cash, total value, P&L per position | DB query positions + price_cache + users_profile; round to 2dp |
| PORT-02 | POST /api/portfolio/trade: buy/sell at cached price; validate cash/shares | Price from price_cache.get(ticker); validation before DB write |
| PORT-03 | Atomic positions + cash update | SQLite `with con:` context manager covers all three writes |
| PORT-04 | Trade appended to trades table | Part of the same atomic transaction |
| PORT-05 | GET /api/portfolio/history: portfolio_snapshots over time | Simple SELECT from portfolio_snapshots ordered by recorded_at |
| PORT-06 | Background snapshot every ~30s | asyncio.create_task in lifespan, same pattern as polling_loop |
| WTCH-01 | GET /api/watchlist with latest prices | DB SELECT + price_cache.get_many() |
| WTCH-02 | POST /api/watchlist: add ticker; polling loop picks up next cycle | DB INSERT; get_watchlist_tickers() re-queries every cycle automatically |
| WTCH-03 | DELETE /api/watchlist/{ticker}: remove ticker | DB DELETE; optionally price_cache.remove(ticker) |
| TEST-01 | Unit tests: trade execution logic (buy, sell, edge cases) | Test the DB mutation functions directly with tmp_db fixture |
| TEST-02 | Unit tests: P&L calculations | Pure-function tests; no DB needed |
| TEST-03 | (Phase 3) LLM structured output parsing | Out of scope for Phase 2 |
| TEST-04 | Unit tests: API route response shapes and status codes | httpx.AsyncClient(ASGITransport) pattern established in test_app.py |
</phase_requirements>

## Standard Stack

### Core (already installed — no new packages)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| fastapi | 0.136.3 | API framework + SSE | `fastapi.sse.EventSourceResponse` built-in since 0.135.0 [VERIFIED: installed] |
| fastapi.sse | (built-in) | `EventSourceResponse`, `ServerSentEvent` | Native, no third-party package needed [VERIFIED: installed] |
| sqlite3 | stdlib | Atomic trade execution | Per-request connections, WAL already enabled [VERIFIED: installed] |
| pydantic | 2.x | Request/response schemas | Already used throughout; Pydantic v2 model_dump() [VERIFIED: installed] |
| pytest + pytest-asyncio | 8.x / 0.23.x | Async test suite | asyncio_mode = "auto" already configured [VERIFIED: installed] |
| httpx | 0.28.1 | AsyncClient for route tests | ASGITransport pattern from test_app.py [VERIFIED: installed] |

### NOT Needed

| Library | Why Skipped |
|---------|-------------|
| sse-starlette | Superseded by fastapi.sse in 0.135.0 |
| aiosqlite | Async SQLite wrapper; overkill for single-user; sync routes in thread pool |
| APScheduler | Overkill for single background task; asyncio.create_task is sufficient |
| pytest-httpx | Not needed; existing ASGITransport pattern covers non-streaming routes |
| async-asgi-testclient | Only needed if testing live SSE streams end-to-end; unit-test approach avoids the need |

**Installation:** None. All dependencies already declared in `backend/pyproject.toml`.

## Package Legitimacy Audit

Phase 2 installs **no new packages**. All dependencies (`fastapi`, `uvicorn`, `httpx`, `pydantic`, `python-dotenv`, and dev deps `pytest`, `pytest-asyncio`, `respx`) were installed in Phase 1 and are already declared in `pyproject.toml`.

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```
[Browser / EventSource]
        |
        | GET /api/stream/prices (SSE, long-lived)
        v
[SSE Router] ──reads──> [price_cache singleton]
                                ^
                                | writes every 0.5s
                        [polling_loop task] ──> [MarketDataSource]

[Browser fetch]
        |
        | GET /api/portfolio
        | POST /api/portfolio/trade  ──> [SQLite: positions, trades, users_profile]
        | GET /api/portfolio/history ──> [SQLite: portfolio_snapshots]
        | GET/POST/DELETE /api/watchlist ──> [SQLite: watchlist]
        v
[Portfolio Router]
[Watchlist Router]
        |
        | (trade exec reads price from)
        v
[price_cache singleton]

[lifespan background tasks]
    ├── polling_loop (existing)
    └── snapshot_recorder (new, every 30s) ──> [SQLite: portfolio_snapshots]
```

### Recommended Project Structure

```
backend/app/
├── routers/
│   ├── __init__.py
│   ├── health.py        # existing
│   ├── market.py        # new: SSE /api/stream/prices
│   ├── portfolio.py     # new: /api/portfolio, /api/portfolio/trade, /api/portfolio/history
│   └── watchlist.py     # new: /api/watchlist CRUD
├── db/
│   ├── database.py      # existing — add snapshot_recorder(), trade helpers here or in separate module
│   ├── schema.py
│   └── seed.py
├── market/
│   └── ...              # existing — unchanged
└── main.py              # add 3 new routers + snapshot_recorder task to lifespan
```

**Where to put trade logic:** Either inline in `portfolio.py` or extracted to `app/db/portfolio.py` (portfolio-specific DB helpers). Given the simplicity, inline in the router module is fine. The test file `tests/test_portfolio.py` will import and test the helper functions directly.

### Pattern 1: SSE Endpoint (FastAPI 0.135+ native style)

**What:** Async generator yielding `ServerSentEvent` objects; FastAPI handles formatting and keepalives.
**When to use:** All SSE endpoints; no manual `data: ...\n\n` formatting needed.

```python
# Source: fastapi.tiangolo.com/tutorial/server-sent-events/ [VERIFIED: official docs]
import asyncio
from collections.abc import AsyncIterable
from fastapi import APIRouter
from fastapi.sse import EventSourceResponse, ServerSentEvent
from app.market.cache import price_cache

router = APIRouter(prefix="/api", tags=["market"])

@router.get("/stream/prices", response_class=EventSourceResponse)
async def stream_prices() -> AsyncIterable[ServerSentEvent]:
    while True:
        updates = await price_cache.get_all()
        for ticker, update in updates.items():
            yield ServerSentEvent(
                data=update.model_dump(),
                event="price_update",
            )
        await asyncio.sleep(0.5)
```

Key points [VERIFIED: installed fastapi 0.136.3]:
- `response_class=EventSourceResponse` — FastAPI serializes yielded data to JSON automatically
- `ServerSentEvent(data=...)` — `data` field accepts a dict; FastAPI JSON-encodes it
- `asyncio.sleep(0.5)` — cadence matches polling_loop interval
- Client disconnect: `CancelledError` propagates from `asyncio.sleep` — no explicit disconnect check needed
- Keepalives: automatic 15-second comment pings [VERIFIED: official docs]
- Cache-control headers: set automatically [VERIFIED: official docs]

### Pattern 2: Atomic Trade Execution

**What:** All position/cash/trade mutations inside a single `with con:` block.
**When to use:** Any write that touches multiple tables.

```python
# Source: verified against sqlite3 stdlib documentation [VERIFIED: tested locally]
def execute_trade(ticker: str, side: str, quantity: float, price: float) -> dict:
    cost = quantity * price
    now = datetime.now(timezone.utc).isoformat()
    con = get_connection()
    try:
        with con:  # BEGIN ... COMMIT; raises on error → ROLLBACK
            profile = con.execute(
                "SELECT cash_balance FROM users_profile WHERE id='default'"
            ).fetchone()

            if side == "buy":
                if profile["cash_balance"] < cost:
                    raise ValueError("Insufficient cash")
                _upsert_position_buy(con, ticker, quantity, price, now)
                con.execute(
                    "UPDATE users_profile SET cash_balance = cash_balance - ? WHERE id = 'default'",
                    (cost,),
                )
            elif side == "sell":
                position = con.execute(
                    "SELECT quantity FROM positions WHERE user_id='default' AND ticker=?",
                    (ticker,),
                ).fetchone()
                if not position or position["quantity"] < quantity:
                    raise ValueError("Insufficient shares")
                _upsert_position_sell(con, ticker, quantity, now)
                con.execute(
                    "UPDATE users_profile SET cash_balance = cash_balance + ? WHERE id = 'default'",
                    (cost,),
                )

            con.execute(
                "INSERT INTO trades (id, user_id, ticker, side, quantity, price, executed_at) "
                "VALUES (?, 'default', ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), ticker, side, quantity, price, now),
            )
        return {"status": "ok", "ticker": ticker, "side": side, "quantity": quantity, "price": price}
    finally:
        con.close()
```

### Pattern 3: Portfolio GET — Joining Cache and DB

**What:** Read positions from DB, enrich each with current price from cache, compute P&L.
**When to use:** `GET /api/portfolio`

```python
# [ASSUMED] — pattern derived from codebase analysis; P&L math verified locally
async def get_portfolio() -> dict:
    con = get_connection()
    try:
        profile = con.execute(
            "SELECT cash_balance FROM users_profile WHERE id='default'"
        ).fetchone()
        rows = con.execute(
            "SELECT ticker, quantity, avg_cost FROM positions WHERE user_id='default'"
        ).fetchall()
    finally:
        con.close()

    tickers = [r["ticker"] for r in rows]
    prices = await price_cache.get_many(tickers)  # async call to cache

    positions = []
    total_market_value = 0.0
    for row in rows:
        ticker = row["ticker"]
        qty = row["quantity"]
        avg_cost = row["avg_cost"]
        current_price = prices[ticker].price if ticker in prices else avg_cost
        market_value = qty * current_price
        unrealized_pnl = (current_price - avg_cost) * qty
        pnl_pct = (current_price - avg_cost) / avg_cost * 100 if avg_cost else 0.0
        total_market_value += market_value
        positions.append({
            "ticker": ticker,
            "quantity": qty,
            "avg_cost": round(avg_cost, 4),
            "current_price": round(current_price, 4),
            "market_value": round(market_value, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
        })

    total_value = round(profile["cash_balance"] + total_market_value, 2)
    return {
        "cash_balance": round(profile["cash_balance"], 2),
        "total_value": total_value,
        "positions": positions,
    }
```

Note: `get_portfolio()` must be `async def` because it awaits `price_cache.get_many()`.

### Pattern 4: Background Snapshot Task

**What:** Periodic asyncio task recording portfolio total value to DB.
**When to use:** PORT-06 — snapshot every 30 seconds.

```python
# Source: established pattern from main.py polling_loop [VERIFIED: codebase]
async def snapshot_recorder() -> None:
    """Record portfolio total value to portfolio_snapshots every 30 seconds."""
    while True:
        await asyncio.sleep(30)
        try:
            snapshot = await _compute_portfolio_value()  # reuse portfolio math
            con = get_connection()
            try:
                with con:
                    con.execute(
                        "INSERT INTO portfolio_snapshots (id, user_id, total_value, recorded_at) "
                        "VALUES (?, 'default', ?, ?)",
                        (str(uuid.uuid4()), snapshot, datetime.now(timezone.utc).isoformat()),
                    )
            finally:
                con.close()
        except Exception:
            logger.exception("Error recording portfolio snapshot — will retry")
```

Register in `main.py` lifespan alongside `polling_loop`:

```python
snapshot_task = asyncio.create_task(snapshot_recorder())
yield
snapshot_task.cancel()
task.cancel()
```

### Pattern 5: Router Registration in main.py

```python
# [VERIFIED: codebase pattern from health router]
from app.routers.market import router as market_router
from app.routers.portfolio import router as portfolio_router
from app.routers.watchlist import router as watchlist_router

app.include_router(market_router)
app.include_router(portfolio_router)
app.include_router(watchlist_router)
```

All routers use `prefix="/api"` to match the endpoint table in PLAN.md.

### Pattern 6: Watchlist — No Signaling Needed

**What:** `POST /api/watchlist` just inserts to DB; `DELETE` just removes. No notification to polling loop needed.
**Why:** `get_watchlist_tickers()` is called at the top of every polling cycle (every 0.5s). New tickers appear in the next cycle automatically. [VERIFIED: loop.py line 19 — `tickers = get_tickers()`]

```python
# DELETE: also remove from price cache to stop stale data appearing
from app.market.cache import price_cache

@router.delete("/watchlist/{ticker}")
async def remove_ticker(ticker: str):
    # DB delete
    con = get_connection()
    try:
        with con:
            con.execute(
                "DELETE FROM watchlist WHERE user_id='default' AND ticker=?", (ticker.upper(),)
            )
    finally:
        con.close()
    await price_cache.remove(ticker.upper())  # clean up cache
    return {"status": "ok"}
```

### Anti-Patterns to Avoid

- **Sharing a single SQLite connection across requests:** Each request must call `get_connection()` and `con.close()` independently. Never store the connection as a module-level singleton for request handling. [VERIFIED: WAL mode allows concurrent connections; sharing state across threads risks corruption]
- **Calling async cache methods from sync `def` routes:** If a route needs `await price_cache.get_all()`, the route must be `async def`. Don't mix sync route + async cache call (Python will raise or silently skip). [VERIFIED: PriceCache uses asyncio.Lock]
- **Manual SSE formatting:** Do not use the old `StreamingResponse` + `f"data: {json}\n\n"` pattern. Use `EventSourceResponse` + `ServerSentEvent`. [CITED: fastapi.tiangolo.com/tutorial/server-sent-events/]
- **Calling `price_cache.get()` before the polling loop has run:** On fresh startup, the cache is empty. Portfolio GET should fall back gracefully (use `avg_cost` as price proxy when cache has no entry). Trade execution must require a cached price — return 503 if ticker not in cache.
- **Not uppercasing tickers:** All ticker operations must normalize to uppercase. `ticker.upper()` in every route handler and DB helper.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| SSE wire format | Manual `data: ...\n\n` generator | `ServerSentEvent` + `EventSourceResponse` | Auto-handles JSON encoding, keepalives, headers |
| Atomic multi-table writes | Manual BEGIN/COMMIT/ROLLBACK | `with con:` context manager | sqlite3 stdlib handles commit/rollback on exception |
| Weighted avg cost math | Custom accumulation | Simple inline formula: `(old_qty * old_cost + new_qty * new_price) / total_qty` | One-liner; no library needed |
| Background tasks | External scheduler | `asyncio.create_task` | Pattern established by polling_loop; zero deps |

**Key insight:** The stdlib sqlite3 `with con:` pattern is sufficient for atomicity at this scale. SQLite serializes writers anyway — no additional locking logic needed.

## Common Pitfalls

### Pitfall 1: SSE Test Hangs
**What goes wrong:** Using `httpx.AsyncClient.stream()` with `aiter_lines()` on an infinite SSE generator hangs the test process indefinitely.
**Why it happens:** The SSE generator never yields `StopIteration`; the ASGI transport and event loop share the same thread — the test awaits a response that never terminates.
**How to avoid:** Unit-test the generator logic directly (call the async function, assert on the first N yielded values). For format-level checks, use synchronous `TestClient` with bounded `iter_lines()` and `break` after N events.
**Warning signs:** Test hangs after `await client.stream(...)` is entered.

```python
# GOOD: Test generator logic directly
async def test_sse_event_content(clear_global_cache):
    await price_cache.update("AAPL", make_update("AAPL", 190.0))
    # Call the streaming function and collect one event
    gen = stream_prices()
    event = await gen.__anext__()
    assert event.data["ticker"] == "AAPL"
    assert "price" in event.data
    await gen.aclose()
```

### Pitfall 2: SQLite "database is locked" on Concurrent Writes
**What goes wrong:** Two requests try to write simultaneously; one gets `sqlite3.OperationalError: database is locked`.
**Why it happens:** SQLite allows one writer at a time; WAL mode helps but doesn't eliminate write contention. FastAPI runs sync routes in a thread pool — concurrent writes are possible.
**How to avoid:** Add `PRAGMA busy_timeout = 5000` to `get_connection()` so SQLite retries for up to 5 seconds before raising.
**Warning signs:** `OperationalError: database is locked` in logs under load.

```python
def get_connection() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=5000")  # add this
    return con
```

Note: `get_connection()` is in Phase 1 code — the plan must include a task to add `busy_timeout`.

### Pitfall 3: Portfolio GET Mixing Async and Sync
**What goes wrong:** Route defined as `def get_portfolio()` (sync) but calls `await price_cache.get_many(...)`.
**Why it happens:** DB reads are sync, cache reads are async; easy to define the route as sync and forget.
**How to avoid:** `GET /api/portfolio` must be `async def` because price_cache requires `await`. Either define as `async def` throughout, or extract DB reads to a sync helper and await only the cache call.
**Warning signs:** `RuntimeWarning: coroutine was never awaited` at runtime.

### Pitfall 4: Trade Without Cached Price
**What goes wrong:** User tries to trade a ticker that isn't in the price cache (e.g., cache just started or ticker was removed).
**Why it happens:** Cache starts empty; after removal, ticker might not reappear for 0.5s.
**How to avoid:** In trade execution, check `price_cache.get(ticker)` returns non-None. If None, return HTTP 503 with `{"detail": "Price not available for ticker"}`.
**Warning signs:** `NoneType has no attribute 'price'` traceback in trade handler.

### Pitfall 5: Float Precision in P&L Display
**What goes wrong:** Unrealized P&L displayed as `12.000000000001` due to IEEE 754 representation.
**Why it happens:** Python float and SQLite REAL are both IEEE 754 double — rounding errors accumulate.
**How to avoid:** `round(value, 2)` for all monetary values in API responses. No need for `Decimal` at this scale.
**Warning signs:** Frontend displays many decimal places in P&L column.

### Pitfall 6: Missing `ticker.upper()` Normalization
**What goes wrong:** User POSTs `{"ticker": "aapl"}` and it is stored lowercased; cache has `"AAPL"`; price lookup returns None.
**Why it happens:** Case sensitivity mismatch between user input and cache keys.
**How to avoid:** `ticker = ticker.upper()` in every route handler before any DB or cache operation. Add a test case for lowercase input.

## Code Examples

Verified patterns from the installed codebase and official sources:

### SSE ServerSentEvent with dict data
```python
# Source: verified locally against fastapi 0.136.3
from fastapi.sse import ServerSentEvent
event = ServerSentEvent(
    data={"ticker": "AAPL", "price": 190.0, "prev_price": 189.0, "change_pct": 0.53},
    event="price_update",
)
# FastAPI serializes data dict to JSON automatically in the SSE data field
```

### SQLite atomic multi-table write
```python
# Source: verified locally — sqlite3 stdlib with WAL mode
with con:  # auto-commit on exit, auto-rollback on exception
    con.execute("UPDATE users_profile SET cash_balance=cash_balance-? WHERE id='default'", (cost,))
    con.execute("INSERT INTO positions ...", (...))
    con.execute("INSERT INTO trades ...", (...))
```

### Weighted average cost update (buy more shares)
```python
# Source: verified locally — standard VWAP formula
new_qty = existing_qty + buy_qty
new_avg_cost = (existing_qty * existing_avg_cost + buy_qty * buy_price) / new_qty
```

### Test pattern — async route with tmp_db fixture
```python
# Source: test_app.py test_health_endpoint [VERIFIED: codebase]
@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    import app.db.database as db_module
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "test.db")

async def test_portfolio_empty():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/portfolio")
    assert response.status_code == 200
    data = response.json()
    assert data["cash_balance"] == 10000.0
    assert data["positions"] == []
```

### Test pattern — mock price_cache for portfolio tests
```python
# [ASSUMED] — standard unittest.mock pattern
from unittest.mock import AsyncMock, patch
from app.market.cache import price_cache

async def test_portfolio_with_price():
    with patch.object(price_cache, "get_many", new=AsyncMock(return_value={"AAPL": make_update("AAPL", 200.0)})):
        # test portfolio endpoint that would read from cache
        ...
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual SSE formatting via StreamingResponse + `f"data: ...\n\n"` | `EventSourceResponse` + `ServerSentEvent` from `fastapi.sse` | FastAPI 0.135.0 | Cleaner code, automatic JSON, built-in keepalives |
| `sse-starlette` third-party package | `fastapi.sse` built-in | FastAPI 0.135.0 | No new dependency needed |
| `asyncio_mode = "strict"` in pytest | `asyncio_mode = "auto"` | pytest-asyncio 0.21+ | Already configured; no `@pytest.mark.asyncio` decorator needed |

**Deprecated/outdated:**
- Manual `data: {json}\n\n` SSE formatting: replaced by `ServerSentEvent(data=...)` in FastAPI 0.135+
- `sse-starlette`: still works, but now redundant given fastapi.sse

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `get_portfolio()` pattern uses `avg_cost` as price fallback when cache is empty | Pattern 3 | Frontend shows stale P&L on startup — low risk, resolves within 0.5s |
| A2 | Snapshot recorder sleeps 30s before first snapshot | Pattern 4 | First snapshot delayed 30s — acceptable; could sleep after first record instead |
| A3 | Busy_timeout addition to get_connection() is a safe in-place edit | Pitfall 2 | If Phase 1 tests assert exact connection pragmas — check test_db.py (confirmed: no such assertion) |

## Open Questions

1. **SSE: Should each event contain all watched tickers or just changed tickers?**
   - What we know: `price_cache.get_all()` returns all; PLAN.md says "push updates for all watched tickers"
   - What's unclear: Whether to yield one SSE event per ticker or one event with all tickers as an array
   - Recommendation: One event per ticker per cycle (N events per 0.5s). Simpler frontend parsing; matches the `PriceUpdate` per-ticker model.

2. **Portfolio history: limit rows returned?**
   - What we know: `portfolio_snapshots` will grow unboundedly at 2/min
   - What's unclear: Whether GET /api/portfolio/history should return all rows or be limited
   - Recommendation: Return all rows for now (single user, small dataset); frontend can decide what to render. Add `LIMIT` if performance becomes an issue in Phase 4.

3. **Trade validation: what if ticker is not on the watchlist?**
   - What we know: PLAN.md doesn't restrict trades to watchlist tickers
   - What's unclear: Should a user be allowed to trade a ticker not in their watchlist?
   - Recommendation: Allow trades on any ticker that has a cached price. No watchlist restriction.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | All backend | ✓ | 3.13.2 | — |
| uv | Package mgmt | ✓ | 0.11.16 | — |
| fastapi 0.135+ | SSE (EventSourceResponse) | ✓ | 0.136.3 | — |
| fastapi.sse | SSE endpoint | ✓ | (built-in 0.136.3) | — |
| sqlite3 | Trade execution | ✓ | stdlib | — |
| pytest-asyncio | Async tests | ✓ | 0.23.x | — |
| httpx | Route tests | ✓ | 0.28.1 | — |

**Missing dependencies with no fallback:** None.
**Missing dependencies with fallback:** None.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-asyncio 0.23.x |
| Config file | `backend/pyproject.toml` (`[tool.pytest.ini_options]`) |
| Quick run command | `uv run pytest tests/test_portfolio.py tests/test_watchlist.py tests/test_market_sse.py -x -q` |
| Full suite command | `uv run pytest -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| STRM-01 | SSE generator yields events at correct cadence | unit | `uv run pytest tests/test_market_sse.py -x -q` | ❌ Wave 0 |
| STRM-02 | SSE event data has ticker, price, prev_price, change_pct, timestamp | unit | `uv run pytest tests/test_market_sse.py::test_sse_event_fields -x` | ❌ Wave 0 |
| STRM-03 | SSE reads from price_cache only | unit | `uv run pytest tests/test_market_sse.py::test_sse_reads_cache -x` | ❌ Wave 0 |
| PORT-01 | GET /api/portfolio response shape: positions, cash, total_value, pnl | unit | `uv run pytest tests/test_portfolio.py::test_portfolio_response_shape -x` | ❌ Wave 0 |
| PORT-02 | POST /api/portfolio/trade buy/sell validation | unit | `uv run pytest tests/test_portfolio.py -x -q` | ❌ Wave 0 |
| PORT-03 | Atomic trade: position + cash updated together | unit | `uv run pytest tests/test_portfolio.py::test_buy_atomic -x` | ❌ Wave 0 |
| PORT-04 | Trade log entry in trades table | unit | `uv run pytest tests/test_portfolio.py::test_trade_log -x` | ❌ Wave 0 |
| PORT-05 | GET /api/portfolio/history returns snapshots | unit | `uv run pytest tests/test_portfolio.py::test_portfolio_history -x` | ❌ Wave 0 |
| PORT-06 | Snapshot recorder inserts rows | unit | `uv run pytest tests/test_portfolio.py::test_snapshot_recorder -x` | ❌ Wave 0 |
| WTCH-01 | GET /api/watchlist returns tickers with prices | unit | `uv run pytest tests/test_watchlist.py::test_get_watchlist -x` | ❌ Wave 0 |
| WTCH-02 | POST /api/watchlist adds ticker | unit | `uv run pytest tests/test_watchlist.py::test_add_ticker -x` | ❌ Wave 0 |
| WTCH-03 | DELETE /api/watchlist/{ticker} removes ticker | unit | `uv run pytest tests/test_watchlist.py::test_remove_ticker -x` | ❌ Wave 0 |
| TEST-01 | Trade logic: buy, sell, insufficient cash, sell more than owned | unit | `uv run pytest tests/test_portfolio.py -x -q` | ❌ Wave 0 |
| TEST-02 | P&L calculations: unrealized_pnl, pnl_pct, total_value | unit | `uv run pytest tests/test_portfolio.py::test_pnl_calculations -x` | ❌ Wave 0 |
| TEST-04 | API route response shapes and status codes | unit | `uv run pytest tests/test_portfolio.py tests/test_watchlist.py -x -q` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest -q` (68 existing + new tests)
- **Per wave merge:** `uv run pytest -q`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_market_sse.py` — covers STRM-01, STRM-02, STRM-03
- [ ] `tests/test_portfolio.py` — covers PORT-01 through PORT-06, TEST-01, TEST-02, TEST-04
- [ ] `tests/test_watchlist.py` — covers WTCH-01, WTCH-02, WTCH-03, TEST-04

## Security Domain

`security_enforcement: true`, `security_asvs_level: 1` per config.json.

### Applicable ASVS Categories (Level 1)

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | No auth layer (by design — single user, no login) |
| V3 Session Management | No | No sessions |
| V4 Access Control | No | Single user, hardcoded `user_id="default"` |
| V5 Input Validation | Yes | Validate ticker (non-empty string, uppercase), quantity (positive float), side ("buy"/"sell") |
| V6 Cryptography | No | No secrets or crypto in Phase 2 |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Negative quantity trade | Tampering | Validate `quantity > 0` before any trade logic; return 422 |
| Invalid side value | Tampering | Validate `side in ("buy", "sell")`; return 422 |
| SQL injection via ticker param | Tampering | Parameterized queries only (already established pattern in codebase) |
| Oversized ticker string | DoS | Validate `len(ticker) <= 10` — tickers are 1-5 chars in practice |

**Validation approach:** Use Pydantic request body models for `POST /api/portfolio/trade` and `POST /api/watchlist`. Pydantic v2 validators catch type errors and enum violations before DB access.

```python
# Trade request body — Pydantic validates before handler runs
from pydantic import BaseModel, field_validator

class TradeRequest(BaseModel):
    ticker: str
    side: str  # "buy" or "sell"
    quantity: float

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, v: str) -> str:
        v = v.upper().strip()
        if not v or len(v) > 10:
            raise ValueError("Invalid ticker")
        return v

    @field_validator("side")
    @classmethod
    def validate_side(cls, v: str) -> str:
        if v not in ("buy", "sell"):
            raise ValueError("side must be 'buy' or 'sell'")
        return v

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("quantity must be positive")
        return v
```

## Sources

### Primary (HIGH confidence)
- FastAPI official docs — `fastapi.tiangolo.com/tutorial/server-sent-events/` — SSE EventSourceResponse pattern, keepalives, cache-control headers [VERIFIED]
- Installed fastapi 0.136.3 — `from fastapi.sse import EventSourceResponse, ServerSentEvent` — confirmed working [VERIFIED]
- Installed sqlite3 stdlib — WAL, busy_timeout, `with con:` atomicity — verified locally [VERIFIED]
- `backend/app/market/loop.py` — polling_loop pattern for background task [VERIFIED: codebase]
- `backend/app/market/cache.py` — PriceCache API: get_all(), get_many(), get(), remove() [VERIFIED: codebase]
- `backend/tests/test_app.py` — test patterns: tmp_db fixture, httpx.AsyncClient(ASGITransport) [VERIFIED: codebase]

### Secondary (MEDIUM confidence)
- FastAPI GitHub discussion #9126 — SSE streaming with httpx.AsyncClient hangs; unit-test generator directly [WebSearch verified with community report]
- SQLite official docs — threadsafety=3, WAL concurrent reads [CITED: sqlite.org/threadsafe.html]

### Tertiary (LOW confidence)
- None — all claims are backed by PRIMARY or SECONDARY sources

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all packages verified installed; no new packages
- Architecture (SSE): HIGH — fastapi.sse confirmed in 0.136.3
- Architecture (trade logic): HIGH — formulas verified locally
- Pitfalls (SSE test hang): MEDIUM — well-documented in FastAPI GitHub discussions, not in official docs
- Pitfalls (busy_timeout): MEDIUM — recommended by SQLite docs and community; no observed issue in this codebase yet

**Research date:** 2026-05-29
**Valid until:** 2026-06-28 (fastapi.sse is stable; no fast-moving dependencies)
