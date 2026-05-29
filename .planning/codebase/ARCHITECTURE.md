<!-- refreshed: 2026-05-29 -->
# Architecture

**Analysis Date:** 2026-05-29

## System Overview

```text
┌─────────────────────────────────────────────────────────────┐
│                        Docker Container                      │
│                       (port 8000 only)                       │
├──────────────────────────────────────────────────────────────┤
│  FastAPI (Python/uv)                                         │
│  ├── /api/*           REST endpoints (portfolio, watchlist,  │
│  │                    chat, health)                          │
│  ├── /api/stream/*    SSE streaming (prices)                 │
│  └── /*               Static Next.js export                  │
│         ↑                                                    │
│  [NOT YET BUILT — planned]                                   │
│  Frontend: Next.js static export (future phase)              │
└──────────────────────────────────────────────────────────────┘
         ↓
┌─────────────────────────────────────────────────────────────┐
│  Market Data Layer   `backend/app/market/`                   │
│  ├── MarketSimulator  (GBM, default)                         │
│  └── MassiveAPIClient (REST polling, env-var activated)      │
│       ↓                                                      │
│  PriceCache singleton (asyncio.Lock, in-memory)              │
│       ↓                                                      │
│  polling_loop() asyncio task                                 │
└─────────────────────────────────────────────────────────────┘
         ↓
┌─────────────────────────────────────────────────────────────┐
│  SQLite database  `db/finally.db`                            │
│  (volume-mounted; lazily initialized on first startup)       │
└─────────────────────────────────────────────────────────────┘
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| `MarketDataSource` (ABC) | Abstract contract for all price sources | `backend/app/market/interface.py` |
| `PriceUpdate` | Pydantic model for one price event | `backend/app/market/interface.py` |
| `MarketSimulator` | GBM-based in-process price simulation | `backend/app/market/simulator.py` |
| `MassiveAPIClient` | Real prices via Massive REST API | `backend/app/market/massive.py` |
| `PriceCache` | In-memory singleton; asyncio-safe price store | `backend/app/market/cache.py` |
| `polling_loop()` | Bridges data source → price cache as asyncio task | `backend/app/market/loop.py` |
| `create_market_data_source()` | Factory: reads env and returns correct source | `backend/app/market/__init__.py` |
| FastAPI app | HTTP/SSE endpoints + static file serving | `backend/app/` (not yet implemented) |
| SQLite database | Persistent state: users, positions, watchlist, trades, chat | `db/finally.db` (runtime artifact) |
| Next.js frontend | SPA static export (Terminal UI) | `frontend/` (not yet implemented) |
| LLM chat handler | Cerebras/OpenRouter integration via LiteLLM | `backend/app/` (not yet implemented) |

## Pattern Overview

**Overall:** Layered async service with strategy pattern for data sourcing

**Key Characteristics:**
- Single Python process; all async (asyncio event loop — no threads)
- Strategy pattern: `MarketDataSource` ABC with two implementations; switching is purely env-var driven
- Module-level singletons: `price_cache` in `backend/app/market/cache.py` — imported by `loop.py` and the future SSE endpoint
- Single container, single port (8000) — frontend served as FastAPI static files, eliminating CORS
- SQLite for persistence (single-user, volume-mounted)
- SSE (not WebSockets) for server→client price streaming

## Layers

**Market Data Layer:**
- Purpose: Produce a continuous stream of `PriceUpdate` objects regardless of source
- Location: `backend/app/market/`
- Contains: ABC, two implementations, cache, polling loop, factory
- Depends on: `httpx` (Massive only), `pydantic`, `asyncio`
- Used by: SSE endpoint (reads `price_cache`), polling_loop task

**API / Application Layer (planned):**
- Purpose: REST + SSE endpoints, trade execution, LLM chat integration
- Location: `backend/app/` (routers not yet present)
- Contains: FastAPI route handlers, portfolio logic, chat logic
- Depends on: Market data layer (via `price_cache`), SQLite DB
- Used by: Frontend (via HTTP/SSE)

**Persistence Layer (planned):**
- Purpose: SQLite schema, seed data, lazily initialized on startup
- Location: `backend/db/` (planned) + runtime `db/finally.db`
- Contains: Table definitions, seed rows
- Depends on: Nothing (pure SQL)
- Used by: API / application layer

**Frontend Layer (planned):**
- Purpose: Static Next.js SPA served by FastAPI from `/`
- Location: `frontend/` (not yet created)
- Contains: React components, SSE client, Tailwind CSS
- Depends on: Backend API at `/api/*`
- Used by: Browser clients

## Data Flow

### Price Update Path (Market Data → Frontend)

1. `MarketSimulator._run_loop()` ticks every 500ms, updating `self._prices` in-process (`backend/app/market/simulator.py:120`)
2. `polling_loop()` calls `source.get_prices(tickers)` each cycle (`backend/app/market/loop.py:34`)
3. `_merge_with_prev()` attaches prior cached price so `change_pct` is accurate (`backend/app/market/loop.py:53`)
4. `price_cache.update_many()` writes atomically under `asyncio.Lock` (`backend/app/market/cache.py:21`)
5. SSE endpoint (planned) reads `price_cache.get_all()` and pushes events to `EventSource` clients

### Massive API Path (alternative to simulator)

1. `MASSIVE_API_KEY` env var triggers `create_market_data_source()` to return `MassiveAPIClient` (`backend/app/market/__init__.py:29`)
2. `polling_loop()` calls `MassiveAPIClient.get_prices()` which hits Massive REST `/v2/snapshot` (`backend/app/market/massive.py:63`)
3. Same `_merge_with_prev()` → `price_cache.update_many()` path as simulator
4. On HTTP 429, `polling_loop()` backs off 60 seconds (`backend/app/market/loop.py:41`)

### Trade Execution Path (planned)

1. User submits `POST /api/portfolio/trade` or AI chat triggers trade
2. Backend validates (sufficient cash / shares), executes at current `price_cache` price
3. SQLite updated: positions, trades log, cash balance
4. Response returned; portfolio snapshot recorded

### LLM Chat Path (planned)

1. `POST /api/chat` → load portfolio context + conversation history from SQLite
2. Call LiteLLM → OpenRouter → Cerebras (`openrouter/openai/gpt-oss-120b`) with structured output schema
3. Parse `LLMResponse` (message + optional trades + watchlist_changes)
4. Auto-execute any trades/watchlist changes
5. Stream `message` tokens back to frontend; persist message + actions to `chat_messages` table

**State Management:**
- Live prices: in-memory `PriceCache` singleton (ephemeral, rebuilt from live source on restart)
- Portfolio / watchlist / history: SQLite (`db/finally.db`, persistent via Docker volume)
- Conversation: SQLite `chat_messages` table

## Key Abstractions

**`MarketDataSource` (ABC):**
- Purpose: Decouple all downstream code from price source implementation
- Examples: `backend/app/market/simulator.py`, `backend/app/market/massive.py`
- Pattern: Template Method / Strategy — `start()`, `stop()`, `get_prices()` contract; `polling_loop` never knows which implementation it holds

**`PriceUpdate` (Pydantic model):**
- Purpose: Canonical price event with computed `change_pct`
- File: `backend/app/market/interface.py`
- Pattern: Value object — immutable, validated, serializable to JSON for SSE

**`PriceCache` (module singleton):**
- Purpose: Single source of truth for latest prices, shared between polling task and SSE handlers
- File: `backend/app/market/cache.py`
- Pattern: Singleton with asyncio.Lock — `price_cache` imported directly, never instantiated by callers

**`create_market_data_source()` (factory):**
- Purpose: Encapsulate env-var switching; all callers get a `MarketDataSource` regardless
- File: `backend/app/market/__init__.py`
- Pattern: Factory function

## Entry Points

**`polling_loop()` (asyncio task):**
- Location: `backend/app/market/loop.py`
- Triggers: FastAPI `lifespan` startup event (planned) — `asyncio.create_task(polling_loop(...))`
- Responsibilities: Polls source, merges prev-price, writes to cache; error-resilient (never crashes loop)

**FastAPI app (planned):**
- Location: `backend/app/main.py` (to be created)
- Triggers: `uvicorn backend.app.main:app`
- Responsibilities: Mount routers, start/stop market data source + polling task via lifespan

**`demo.py` (development tool):**
- Location: `backend/demo.py`
- Triggers: `cd backend && uv run --group dev python demo.py`
- Responsibilities: Rich terminal demo of simulator — not part of production path

## Architectural Constraints

- **Threading:** Single-threaded asyncio event loop. The GBM simulator loop runs as an asyncio task (not a thread). `PriceCache` uses `asyncio.Lock`, not `threading.Lock`.
- **Global state:** `price_cache` singleton at `backend/app/market/cache.py:48`. Imported module-level by `loop.py` and the planned SSE endpoint. Do not create additional instances.
- **Circular imports:** None detected in current codebase.
- **Single user:** All DB tables include a `user_id` column defaulting to `"default"`. Multi-user is a future concern; current code hardcodes this value.
- **No migrations:** SQLite schema is lazily initialized on first startup. Schema changes require handling existing DB files.

## Anti-Patterns

### Creating a new PriceCache instance

**What happens:** Code instantiates `PriceCache()` directly instead of importing the singleton
**Why it's wrong:** The polling loop and SSE endpoint need to share the exact same cache object; a new instance is always empty
**Do this instead:** `from app.market.cache import price_cache` — always import the module-level singleton

### Calling `source.get_prices()` directly from SSE handler

**What happens:** SSE handler bypasses the cache and calls the data source directly
**Why it's wrong:** Defeats the cache architecture; adds latency for each SSE client; breaks the source-agnostic design
**Do this instead:** Read from `price_cache.get_all()` or `price_cache.get_many()` in SSE handlers

### Passing a static list to `polling_loop`

**What happens:** `get_tickers` argument is a list literal, e.g. `polling_loop(source, ["AAPL"], 0.5)`
**Why it's wrong:** `polling_loop` signature requires a `Callable[[], list[str]]` — passing a list causes a `TypeError` and prevents dynamic watchlist updates
**Do this instead:** Pass a callable: `polling_loop(source, lambda: watchlist_state, 0.5)`

## Error Handling

**Strategy:** Fail-safe loop — catch and log, never terminate background tasks

**Patterns:**
- `polling_loop` catches all exceptions; HTTP 429 → 60s backoff, any other error → log + continue at normal interval
- `MarketSimulator._run_loop` catches non-`CancelledError` exceptions and continues the tick loop
- `MassiveAPIClient.get_prices` raises `httpx.HTTPStatusError` on non-2xx — caller (`polling_loop`) handles it

## Cross-Cutting Concerns

**Logging:** `logging.getLogger(__name__)` in each module. No structured logging yet.
**Validation:** Pydantic v2 for all data models (`PriceUpdate`, planned request/response schemas)
**Authentication:** None (single-user, no auth layer)
**LLM integration:** LiteLLM → OpenRouter → Cerebras via `cerebras-inference` skill pattern (`backend/.claude/skills/cerebras/SKILL.md`)

---

*Architecture analysis: 2026-05-29*
