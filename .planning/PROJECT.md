# FinAlly — AI Trading Workstation

## What This Is

FinAlly (Finance Ally) is an AI-powered trading workstation that streams live market data, lets users trade a simulated portfolio, and integrates an LLM chat assistant that can analyze positions and execute trades on the user's behalf. It runs in a single Docker container, accessible at `http://localhost:8000`, with no login required. The aesthetic is a modern Bloomberg terminal with an AI copilot.

This is the capstone project for an agentic AI coding course — built entirely by coding agents to demonstrate what orchestrated AI can produce.

## Core Value

The complete flow works end-to-end: prices stream live, the user can trade manually, and the AI assistant can analyze the portfolio and execute trades via natural language — all in one session from a single `docker run`.

## Requirements

### Validated

- ✓ Market data simulator (GBM-based, correlated sectors, random events) — market data phase
- ✓ Massive API client (Polygon.io REST polling, env-var activated) — market data phase
- ✓ Price cache (in-memory singleton, asyncio-safe) — market data phase
- ✓ Polling loop (background task, error-resilient, dynamic watchlist) — market data phase
- ✓ Market data abstract interface (source-agnostic contract) — market data phase

### Active

- [ ] FastAPI application (lifespan, router mounting, static file serving)
- [ ] SSE endpoint for live price streaming (`GET /api/stream/prices`)
- [ ] SQLite database with lazy initialization and seed data
- [ ] Portfolio API (positions, cash balance, unrealized P&L, trade execution)
- [ ] Watchlist API (get, add, remove tickers)
- [ ] Portfolio history snapshots (for P&L chart)
- [ ] LLM chat integration via LiteLLM → OpenRouter → Cerebras (structured outputs, auto trade execution)
- [ ] Chat history persistence (SQLite `chat_messages` table)
- [ ] Next.js frontend — trading terminal UI (TypeScript, static export, Tailwind dark theme)
- [ ] Watchlist panel with live price flash animations and sparklines
- [ ] Main chart area (selected ticker price history)
- [ ] Portfolio heatmap (treemap, positions sized by weight, colored by P&L)
- [ ] P&L chart (total portfolio value over time)
- [ ] Positions table (quantity, avg cost, current price, P&L)
- [ ] Trade bar (ticker, quantity, buy/sell, market orders, instant fill)
- [ ] AI chat panel (streaming responses, inline trade confirmations)
- [ ] Header (portfolio total, connection status dot, cash balance)
- [ ] Multi-stage Dockerfile (Node 20 → Python 3.12, port 8000)
- [ ] Docker volume for SQLite persistence
- [ ] Start/stop scripts (macOS/Linux shell, Windows PowerShell)
- [ ] Backend unit tests (portfolio logic, trade execution, chat parsing, API routes)
- [ ] Frontend unit tests (component rendering, price flash, watchlist CRUD)
- [ ] Playwright E2E tests with LLM_MOCK mode

### Out of Scope

- Real-time WebSocket connections — SSE is sufficient for one-way price push
- User authentication / multi-user support — single-user, `user_id="default"` hardcoded
- Limit orders, partial fills, order book — market orders only, instant fill
- Mobile app — web-first, desktop-optimized
- Real money / real brokerage integration — simulated portfolio only
- OAuth login — no auth layer at all
- Cloud deployment (Terraform, App Runner) — stretch goal, not in core build

## Context

- Market data layer fully built and tested (59 tests, `backend/app/market/`)
- Backend is a `uv`-managed Python project (`backend/pyproject.toml`)
- No FastAPI app, no database, no frontend yet
- LLM integration uses `openrouter/openai/gpt-oss-120b` via Cerebras inference (see `cerebras-inference` skill)
- `OPENROUTER_API_KEY` is in `.env` at project root; `MASSIVE_API_KEY` is optional
- Design: dark theme (#0d1117), accent yellow (#ecad0a), blue (#209dd7), purple (#753991)
- SSE over WebSockets (one-way push, simpler, universal browser support)
- SQLite over Postgres (single-user, no server, zero config)
- `LLM_MOCK=true` env var enables deterministic mock responses for E2E tests

## Constraints

- **Tech stack**: Python/FastAPI/uv backend; Next.js TypeScript frontend (static export); SQLite; LiteLLM → OpenRouter → Cerebras — no deviations
- **Deployment**: Single Docker container, single port (8000) — no docker-compose for production
- **Database**: SQLite only, lazy init on first startup — no Alembic, no migrations, no Postgres
- **LLM**: Must use structured output schema (`message`, `trades[]`, `watchlist_changes[]`) for auto-execution
- **Frontend build**: `output: 'export'` in Next.js config — served as static files by FastAPI

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| SSE over WebSockets | One-way push is all we need; simpler, no bidirectional complexity | — Pending |
| Static Next.js export | Single origin, no CORS, one port, one container | — Pending |
| SQLite over Postgres | No auth = no multi-user = no DB server needed | — Pending |
| Single Docker container | One `docker run` for students; no orchestration | — Pending |
| Market orders only | Eliminates order book, limit logic, partial fills | — Pending |
| LiteLLM → Cerebras | Fast inference, structured outputs, OpenRouter routing | ✓ Validated in Phase 03 |
| GBM simulator default | No API key required; realistic correlated price action | ✓ Validated |
| Strategy pattern (MarketDataSource ABC) | All downstream code stays source-agnostic | ✓ Validated |

---
*Last updated: 2026-05-30 after Phase 03 (LLM Chat Integration) complete*

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state
