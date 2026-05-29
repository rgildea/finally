# External Integrations

**Analysis Date:** 2026-05-29

## APIs & External Services

**Market Data (conditional):**
- Massive (Polygon.io-compatible) REST API — real-time US equity price snapshots
  - SDK/Client: `httpx.AsyncClient` (no official SDK; raw HTTP in `backend/app/market/massive.py`)
  - Auth: `MASSIVE_API_KEY` env var passed as `?apiKey=` query parameter
  - Endpoint: `GET https://api.massive.com/v2/snapshot/locale/us/markets/stocks/tickers`
  - Plan requirement: Starter plan or above (Basic/free tier does NOT support the snapshot endpoint)
  - Rate limits: free ~5 req/min → poll every 15s; paid tiers support 5s or 1s
  - Error handling: HTTP 429 → 60s back-off in `backend/app/market/loop.py`
  - Active when: `MASSIVE_API_KEY` is set and non-empty in environment

**LLM / AI (planned, not yet implemented):**
- OpenRouter → Cerebras inference — LLM chat assistant
  - SDK/Client: `litellm` (to be added via `uv add litellm`)
  - Auth: `OPENROUTER_API_KEY` env var
  - Model: `openrouter/openai/gpt-oss-120b` with `{"provider": {"order": ["cerebras"]}}`
  - Pattern: Structured Outputs using Pydantic `BaseModel` subclass
  - Skill: `.claude/skills/cerebras/SKILL.md` documents exact usage pattern
  - Mock mode: `LLM_MOCK=true` returns deterministic responses without calling the API

## Data Storage

**Databases:**
- SQLite — single-file embedded database
  - File path: `/app/db/finally.db` (inside container) / `db/finally.db` (host volume)
  - Client: Python standard library `sqlite3` (no ORM; raw SQL — not yet wired)
  - Initialization: lazy on first request — schema created and seeded if file missing
  - Volume mount: `finally-data:/app/db` in Docker

**File Storage:**
- Local filesystem only (SQLite file, static frontend export)

**Caching:**
- In-process in-memory cache — `backend/app/market/cache.py`
  - `PriceCache` class with `asyncio.Lock`-protected dict
  - Module-level singleton `price_cache` imported by polling loop and SSE endpoint
  - No external cache (no Redis, no Memcached)

## Authentication & Identity

**Auth Provider:**
- None — single-user application, no login or signup
- All DB rows use hardcoded `user_id = "default"`
- Schema includes `user_id` columns to enable future multi-user without migration

## Monitoring & Observability

**Error Tracking:**
- None — no Sentry, Datadog, or equivalent

**Logs:**
- Python standard library `logging` module
- Logger per module: `logger = logging.getLogger(__name__)`
- Key log events: simulator start/stop, Massive API errors, 429 rate limit back-off, market shock events

## CI/CD & Deployment

**Hosting:**
- Docker container on port 8000 (local or cloud)
- Optional: AWS App Runner, Render, or any container platform
- Terraform for App Runner noted as stretch goal in `planning/PLAN.md`

**CI Pipeline:**
- `.github/` directory present (contents not inspected)
- Tests: `cd backend && uv run --group dev pytest`

## Environment Configuration

**Required env vars:**
- `OPENROUTER_API_KEY` — required for LLM chat feature (not yet implemented)

**Optional env vars:**
- `MASSIVE_API_KEY` — enables real market data; omit to use built-in simulator (recommended default)
- `LLM_MOCK` — set `"true"` for E2E tests and development without an API key

**Secrets location:**
- `.env` file at project root (gitignored)
- `.env.example` not yet committed (referenced in `planning/PLAN.md` as intended)
- Loaded by `python-dotenv` at backend startup

## Webhooks & Callbacks

**Incoming:**
- None

**Outgoing:**
- None

## Real-Time Data Delivery

**SSE Stream:**
- Endpoint: `GET /api/stream/prices`
- Long-lived Server-Sent Events connection; no WebSockets
- Client uses native browser `EventSource` API with built-in reconnection
- Server pushes price updates for all watched tickers at ~500ms cadence
- Data source: `price_cache` singleton in `backend/app/market/cache.py`
- Not yet implemented (wiring the cache to an SSE endpoint is pending)

---

*Integration audit: 2026-05-29*
