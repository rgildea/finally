# FinAlly Build Contract

This document is the binding contract between the agent team building FinAlly.
`PLAN.md` is the product spec; this file resolves module boundaries, file
ownership, and exact interfaces so agents can work in parallel without
colliding. **Do not edit a file you do not own. If you need a change to a file
another agent owns, message that agent.**

The market data subsystem (`backend/app/market/`) is COMPLETE — do not modify it.
Factory function is `create_market_data_source()` (note the name). Singleton
cache is `app.market.cache.price_cache`. `PriceUpdate` fields: `ticker`, `price`,
`prev_price`, `timestamp` (ISO8601 UTC string), computed `change_pct` (percent).

---

## 1. File Ownership

| Owner | Paths |
|-------|-------|
| **db-engineer** | `backend/app/db/**` (schema, connection, lazy init/seed, query functions) |
| **backend-engineer** | `backend/app/main.py`, `backend/app/config.py`, `backend/app/api/{health,portfolio,watchlist,stream}.py`, `backend/app/services/**` |
| **llm-engineer** | `backend/app/api/chat.py`, `backend/app/llm/**` |
| **frontend-engineer** | `frontend/**` |
| **devops-engineer** | `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `.env.example`, `scripts/**` |
| **integration-tester** | `test/**` (Playwright E2E + `docker-compose.test.yml`) |

Shared/locked files: `backend/pyproject.toml` and `backend/uv.lock` are owned by
the **team lead**. If you need a new Python dependency, message the lead — do not
run `uv add` yourself (it rewrites the lock and causes conflicts). Current extra
deps already installed: `litellm`, `aiosqlite`, `sse-starlette`.

Everyone writes unit tests for their own code under the relevant `tests/` tree
(`backend/tests/<area>/` for Python, `frontend/` conventions for TS).

---

## 2. Database layer (db-engineer)

Package `backend/app/db/`. Use **aiosqlite** (async). DB file path from
`config.DB_PATH` (default `db/finally.db` relative to project root; overridable
via `FINALLY_DB_PATH` env). Provide:

```python
# app/db/__init__.py exports:
async def init_db() -> None      # lazy: create tables + seed if empty. Idempotent.
async def get_db() -> aiosqlite.Connection   # shared connection accessor
async def close_db() -> None
```

Query functions (async) in `app/db/queries.py`, returning plain dicts/dataclasses
(NOT raw rows). Minimum set the other agents depend on:

```python
# profile
async def get_profile() -> dict            # {"cash_balance": float}
async def set_cash_balance(balance: float) -> None

# watchlist
async def list_watchlist() -> list[str]            # tickers, ordered by added_at
async def add_watchlist(ticker: str) -> None       # ignore if exists (UNIQUE)
async def remove_watchlist(ticker: str) -> None

# positions
async def list_positions() -> list[dict]           # [{ticker, quantity, avg_cost}]
async def get_position(ticker: str) -> dict | None
async def upsert_position(ticker: str, quantity: float, avg_cost: float) -> None
async def delete_position(ticker: str) -> None

# trades
async def insert_trade(ticker, side, quantity, price) -> dict   # the inserted row
async def list_trades(limit: int = 100) -> list[dict]

# snapshots
async def insert_snapshot(total_value: float) -> None
async def list_snapshots(limit: int = 500) -> list[dict]   # [{recorded_at, total_value}]

# chat
async def insert_chat_message(role, content, actions: dict | None) -> dict
async def list_chat_messages(limit: int = 20) -> list[dict] # oldest->newest
```

Schema exactly as in `PLAN.md` §7. All tables carry `user_id` defaulting to
`"default"`; hardcode `"default"` everywhere for now. Seed: profile cash
`10000.0`, watchlist `AAPL, GOOGL, MSFT, AMZN, TSLA, NVDA, META, JPM, V, NFLX`.

---

## 3. Services layer (backend-engineer)

Package `backend/app/services/`. Business logic shared by REST routes AND the LLM
auto-executor. Pure functions over the db layer + price cache.

```python
# app/services/watchlist.py — also owns the in-memory watched-ticker set
#   that feeds the market polling loop's get_tickers.
async def load_watchlist() -> None          # called at startup: DB -> memory
def get_watched_tickers() -> list[str]       # SYNC; used by polling_loop get_tickers
async def add_ticker(ticker: str) -> list[str]      # validates, updates DB+memory
async def remove_ticker(ticker: str) -> list[str]

# app/services/trading.py
class TradeError(Exception): ...   # message is user-safe
async def execute_trade(ticker: str, side: str, quantity: float) -> dict
#   side in {"buy","sell"}; market order; fills at current cache price.
#   Validates: positive qty, price available, sufficient cash (buy) / shares (sell).
#   Updates positions + cash + inserts trade row. Returns:
#   {"ticker","side","quantity","price","cash_balance","position": {...}|None}
#   Raises TradeError(msg) on validation failure.

# app/services/portfolio.py
async def get_portfolio() -> dict            # shape defined in §4 GET /api/portfolio
async def record_snapshot() -> None          # compute total value, insert snapshot
```

`execute_trade` fill price = `price_cache.get(ticker)` latest price; if the ticker
has no cached price, raise `TradeError("No price available for <ticker>")`.

---

## 4. REST API shapes (backend-engineer unless noted)

All under `/api`. JSON. Mounted via routers in `main.py`.

```
GET /api/health -> {"status":"ok"}

GET /api/portfolio ->
{
  "cash_balance": 10000.0,
  "positions_value": 523.45,
  "total_value": 10523.45,
  "total_pl": 23.45,            # unrealized P&L across positions
  "total_pl_pct": 0.23,
  "positions": [
    {"ticker":"AAPL","quantity":10.0,"avg_cost":190.0,
     "current_price":195.0,"market_value":1950.0,
     "unrealized_pl":50.0,"unrealized_pl_pct":2.63}
  ]
}

POST /api/portfolio/trade  body {"ticker":"AAPL","quantity":10,"side":"buy"}
  -> 200 result of execute_trade (see §3)
  -> 400 {"detail":"<TradeError message>"} on validation failure

GET /api/portfolio/history -> {"snapshots":[{"recorded_at":"...","total_value":10500.0}, ...]}

GET /api/watchlist -> [
  {"ticker":"AAPL","price":195.0,"prev_price":194.5,"change_pct":0.25,"timestamp":"..."}
]   # tickers with no cached price yet: price/prev_price null, change_pct 0

POST /api/watchlist  body {"ticker":"PYPL"} -> 200 updated watchlist (same shape as GET)
DELETE /api/watchlist/{ticker} -> 200 updated watchlist

GET /api/stream/prices  (SSE)  # see §6
POST /api/chat  (SSE)          # llm-engineer, see §5
```

Ticker inputs are uppercased and stripped server-side.

---

## 5. Chat / LLM (llm-engineer)

`POST /api/chat` body `{"message":"..."}`. Returns an **SSE stream**
(`text/event-stream`). Event protocol (frontend depends on this exactly):

```
event: token   data: {"text":"partial chunk"}     # repeated, streaming the reply
event: action  data: {"trades":[...], "watchlist_changes":[...]}  # 0 or 1, after tokens
event: done     data: {"message_id":"<uuid>"}
event: error    data: {"detail":"..."}              # on failure
```

Flow per `PLAN.md` §9: load portfolio context (`services.portfolio.get_portfolio`),
watchlist w/ prices, recent history (`db.list_chat_messages`), call LLM with
structured output, auto-execute trades via `services.trading.execute_trade` and
watchlist changes via `services.watchlist.add_ticker/remove_ticker`, persist user
+ assistant messages (assistant `actions` = JSON of executed results incl. any
errors), then stream the conversational `message` token-by-token.

Use the **cerebras** skill: LiteLLM + OpenRouter, model
`openrouter/openai/gpt-oss-120b`, `extra_body={"provider":{"order":["cerebras"]}}`,
`response_format=<pydantic model>`. Structured output schema per `PLAN.md` §9
(`message`, optional `trades[]`, optional `watchlist_changes[]`).

`LLM_MOCK=true` -> deterministic responses in `app/llm/mock.py` (no network). Mock
must still exercise the action path: e.g. a message containing "buy" triggers a
small AAPL buy so E2E can assert inline trade confirmation. Document mock triggers
in a docstring so integration-tester can rely on them.

---

## 6. main.py assembly (backend-engineer)

FastAPI app with lifespan:
- startup: `await init_db()`; `await services.watchlist.load_watchlist()`;
  `source = create_market_data_source(); await source.start()`;
  start `polling_loop(source, get_tickers=services.watchlist.get_watched_tickers,
  interval_seconds=...)` as a task; start a snapshot task calling
  `services.portfolio.record_snapshot()` on an interval (e.g. every 15s).
- shutdown: cancel tasks, `await source.stop()`, `await close_db()`.
- Interval: 0.5s if simulator, 15s if Massive. Decide from env (MASSIVE_API_KEY).

Static serving: mount the built frontend (Next.js static export) at `/`. Serve
`backend/static/` if present (DevOps copies the export there in Docker). API
routes take precedence. For local dev without a build, a missing static dir must
not crash the app (serve a tiny placeholder or skip the mount). Use a SPA-style
fallback to `index.html` for unknown non-/api paths.

`config.py`: central settings (DB_PATH, LLM_MOCK, MASSIVE_API_KEY, OPENROUTER_API_KEY,
poll interval, snapshot interval, static dir). Load `.env` from project root.

---

## 7. Frontend (frontend-engineer)

Next.js + TypeScript, `output: 'export'` (static). Tailwind dark theme. Brand
colors: accent yellow `#ecad0a`, blue `#209dd7`, purple `#753991` (submit buttons).
Background ~`#0d1117`. Use the **frontend-design** skill for visual quality.

- All data via same-origin `/api/*` (no CORS). Use a small typed API client.
- Live prices via native `EventSource('/api/stream/prices')`; flash green/red on
  change, fade ~500ms. Connection-status dot in header (green/yellow/red).
- Sparklines (watchlist) and the main detail chart accumulate history
  **client-side from the SSE stream** — there is no historical-price backend
  endpoint. P&L chart uses `GET /api/portfolio/history`.
- Components per `PLAN.md` §10: watchlist, main chart, portfolio heatmap (treemap),
  P&L chart, positions table, trade bar, AI chat panel, header.
- Chat: consume the SSE protocol in §5 (token/action/done/error). Render streamed
  tokens; show executed trades/watchlist changes inline as confirmations.
- Charts: Recharts or Lightweight Charts.
- For local dev the frontend runs on Next's dev server proxying `/api` to
  `http://localhost:8000`; in production it is a static export served by FastAPI.
  Configure a dev proxy (next.config rewrites) so `npm run dev` works against the
  backend.

---

## 8. DevOps (devops-engineer)

- Multi-stage `Dockerfile`: Stage 1 Node 20+ builds `frontend/` (`npm ci && npm run
  build`) producing the static export; Stage 2 Python 3.12-slim installs uv, runs
  `uv sync` in `backend/`, copies the frontend export into `backend/static/`,
  exposes 8000, `CMD` uvicorn `app.main:app`.
- `.dockerignore`, `.env.example` (keys from `PLAN.md` §5), `docker-compose.yml`
  (named volume `finally-data` -> `/app/db`, `--env-file .env`, port 8000).
- `scripts/start_mac.sh`, `stop_mac.sh`, `start_pc.ps1`, `stop_pc.ps1` — idempotent,
  build-if-needed, volume mount, print URL. Per `PLAN.md` §11.

---

## 9. Integration testing (integration-tester)

- `test/` Playwright project (TypeScript) + `test/docker-compose.test.yml` running
  the app container with `LLM_MOCK=true`. Scenarios per `PLAN.md` §12.
- Run only once the app builds and starts. File issues back to owners via the
  shared task list (create a task, assign the owner) and message them.

---

## 10. Conventions

- No emojis. uv for Python (`uv run ...`). TypeScript only (no plain JS).
- Latest idiomatic style; short modules/functions; concise docstrings.
- Write tests for new code. Backend tests: `cd backend && uv run --group dev pytest`.
- Coordinate via the shared task list + SendMessage. Mark tasks in_progress when
  you start and completed only when tests pass.
</content>
</invoke>
