# Roadmap: FinAlly — AI Trading Workstation

## Overview

Starting from a completed market data layer (GBM simulator, Massive API client, price cache, polling loop), this roadmap builds the full trading workstation in six phases: FastAPI application foundation and database, backend API routes with streaming and portfolio logic, LLM chat integration, the frontend trading terminal UI, the AI chat panel, and finally Docker packaging with end-to-end tests. Each phase delivers a vertically complete, testable slice of functionality that builds on the previous one.

## Phases

**Phase Numbering:**

- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Backend Foundation** - FastAPI app with lifespan, SQLite database with lazy init and seed data (completed 2026-05-29)
- [ ] **Phase 2: Backend APIs** - SSE price streaming, portfolio CRUD, watchlist management, and backend unit tests
- [ ] **Phase 3: LLM Chat Integration** - LiteLLM to Cerebras structured output, auto-trade execution, mock mode
- [ ] **Phase 4: Frontend Trading Terminal** - Dark terminal UI, watchlist with price flashes, charts, portfolio heatmap, trade bar, SSE connection
- [ ] **Phase 5: AI Chat Panel** - Streaming chat UI, inline trade confirmations, connected to backend chat API
- [ ] **Phase 6: Docker and E2E Tests** - Multi-stage Dockerfile, start/stop scripts, Playwright E2E test suite

## Phase Details

### Phase 1: Backend Foundation

**Goal**: The FastAPI application starts cleanly, serves a health endpoint, auto-initializes the SQLite database with schema and seed data, and is ready to mount API routes
**Depends on**: Nothing (market data layer already complete)
**Requirements**: APP-01, APP-02, APP-03, DB-01, DB-02, DB-03
**Success Criteria** (what must be TRUE):

  1. `uvicorn backend.app.main:app` starts without error and the market data polling loop begins in the background
  2. `GET /api/health` returns `{"status": "ok"}`
  3. On first startup, all six SQLite tables are created and the default user profile plus 10 watchlist tickers are seeded — with no manual step required
  4. Subsequent startups with an existing database do not re-seed or error**Plans**: 2 plans

**Wave 1**

  - [x] 01-01-PLAN.md — SQLite database layer: schema, idempotent seed, connection helper, watchlist callable (DB-01, DB-02, DB-03)

**Wave 2** *(blocked on Wave 1 completion)*

  - [x] 01-02-PLAN.md — FastAPI app with lifespan, health endpoint, conditional static mount (APP-01, APP-02, APP-03)

### Phase 2: Backend APIs

**Goal**: All REST and SSE endpoints are functional and unit-tested — prices stream over SSE, portfolio and trade endpoints work correctly, and watchlist management persists to the database
**Depends on**: Phase 1
**Requirements**: STRM-01, STRM-02, STRM-03, PORT-01, PORT-02, PORT-03, PORT-04, PORT-05, PORT-06, WTCH-01, WTCH-02, WTCH-03, TEST-01, TEST-02, TEST-04
**Success Criteria** (what must be TRUE):

  1. `GET /api/stream/prices` delivers SSE events at ~500ms cadence, each containing ticker, price, prev_price, change_pct, and timestamp
  2. `GET /api/portfolio` returns current positions, cash balance, total value, and per-position unrealized P&L
  3. `POST /api/portfolio/trade` executes a buy or sell at the current cached price; insufficient cash or shares are rejected with an appropriate error
  4. Trades atomically update positions and cash balance and append a log entry to the trades table
  5. `GET /api/watchlist`, `POST /api/watchlist`, and `DELETE /api/watchlist/{ticker}` all function correctly and the polling loop reflects watchlist changes on its next cycle
  6. Backend unit tests cover trade execution logic, P&L calculations, and API route response shapes

**Plans**: 3 plans

**Wave 1**

  - [ ] 02-01-PLAN.md — SSE price streaming endpoint + busy_timeout pragma (STRM-01, STRM-02, STRM-03)

**Wave 2** *(blocked on Wave 1 completion)*

  - [ ] 02-02-PLAN.md — Portfolio read, atomic trade execution, history, snapshot recorder (PORT-01, PORT-02, PORT-03, PORT-04, PORT-05, PORT-06, TEST-01, TEST-02, TEST-04)

**Wave 3** *(blocked on Wave 2 completion)*

  - [ ] 02-03-PLAN.md — Watchlist CRUD endpoints (WTCH-01, WTCH-02, WTCH-03, TEST-04)

### Phase 3: LLM Chat Integration

**Goal**: The backend chat endpoint accepts user messages, constructs a portfolio-aware prompt, calls the LLM via LiteLLM to Cerebras with structured output, auto-executes any trades or watchlist changes, persists conversation history, and streams the reply — with a deterministic mock mode for testing
**Depends on**: Phase 2
**Requirements**: CHAT-01, CHAT-02, CHAT-03, CHAT-04, CHAT-05, CHAT-06, TEST-03
**Success Criteria** (what must be TRUE):

  1. `POST /api/chat` streams a token-by-token LLM response back to the caller
  2. The LLM receives current portfolio context (cash, positions with P&L, watchlist with live prices) and recent conversation history in its prompt
  3. Trades and watchlist changes in the LLM structured response are executed automatically before streaming begins, and failures are surfaced in the reply
  4. Each user message and assistant response (including executed actions) is persisted to the `chat_messages` table
  5. When `LLM_MOCK=true`, the endpoint returns a deterministic mock response without calling OpenRouter
  6. Unit tests cover structured output parsing for valid and malformed LLM responses

**Plans**: TBD
**UI hint**: no

### Phase 4: Frontend Trading Terminal

**Goal**: Users can view a live trading terminal in the browser — prices update in real time with flash animations, charts render, the portfolio heatmap and positions table are visible, and trades can be executed from the trade bar
**Depends on**: Phase 2
**Requirements**: FE-01, FE-02, FE-03, FE-04, FE-05, FE-06, FE-07, FE-08, FE-09, FE-10, FE-11, FE-12, FE-16, FE-17, TEST-05, TEST-06
**Success Criteria** (what must be TRUE):

  1. The browser at `http://localhost:8000` shows a dark terminal UI (background #0d1117) with a header displaying live portfolio value, cash balance, and a green/yellow/red connection status dot
  2. The watchlist panel shows all 10 default tickers with live prices that flash green or red on each update, including sparkline mini-charts
  3. Clicking a ticker loads its price history in the main chart area; the P&L chart shows portfolio value over time
  4. The portfolio heatmap renders positions as rectangles sized by weight and colored by P&L; the positions table shows all position details
  5. Entering a ticker and quantity in the trade bar and clicking Buy or Sell executes the trade, updates cash and positions without a page reload
  6. The `EventSource` connection reconnects automatically on disconnect and the status dot reflects the live connection state

**Plans**: TBD
**UI hint**: yes

### Phase 5: AI Chat Panel

**Goal**: Users can converse with the AI trading assistant in a docked chat panel — responses stream token-by-token, and trades or watchlist changes executed by the AI appear inline as confirmation messages
**Depends on**: Phase 3, Phase 4
**Requirements**: FE-13, FE-14, FE-15
**Success Criteria** (what must be TRUE):

  1. The AI chat panel shows scrolling conversation history and a message input; the user can send a message and see the assistant response build token-by-token
  2. When the AI executes a trade or watchlist change, a confirmation message appears inline in the chat thread
  3. The chat panel reflects the current conversation state across multiple messages without a page reload

**Plans**: TBD
**UI hint**: yes

### Phase 6: Docker and E2E Tests

**Goal**: The full application runs from a single `docker run` command, data persists across restarts, start/stop scripts work on macOS and Windows, and the Playwright E2E suite validates all critical user flows
**Depends on**: Phase 5
**Requirements**: DOCK-01, DOCK-02, DOCK-03, DOCK-04, DOCK-05, TEST-07, TEST-08, TEST-09, TEST-10, TEST-11
**Success Criteria** (what must be TRUE):

  1. `bash scripts/start_mac.sh` builds the image and opens the app at `http://localhost:8000`; `bash scripts/stop_mac.sh` stops the container without deleting the data volume
  2. Portfolio data (cash balance, positions) persists across container restarts via the named Docker volume
  3. The PowerShell equivalents (`start_windows.ps1`, `stop_windows.ps1`) function correctly on Windows
  4. Playwright E2E tests confirm: fresh start shows 10 tickers and $10k balance with streaming prices; ticker add/remove works; buy/sell flows update portfolio correctly
  5. Playwright E2E test with `LLM_MOCK=true` confirms: sending a chat message returns a streamed response and any AI-executed trade appears inline in the chat

**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Backend Foundation | 2/2 | Complete    | 2026-05-29 |
| 2. Backend APIs | 0/3 | Not started | - |
| 3. LLM Chat Integration | 0/TBD | Not started | - |
| 4. Frontend Trading Terminal | 0/TBD | Not started | - |
| 5. AI Chat Panel | 0/TBD | Not started | - |
| 6. Docker and E2E Tests | 0/TBD | Not started | - |
</content>
