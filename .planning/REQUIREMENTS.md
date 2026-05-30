# Requirements: FinAlly — AI Trading Workstation

**Defined:** 2026-05-29
**Core Value:** The complete flow works end-to-end — prices stream live, the user can trade manually, and the AI assistant can analyze the portfolio and execute trades via natural language — all from a single `docker run`.

## v1 Requirements

### Backend Application

- [x] **APP-01**: FastAPI app starts with a lifespan that launches the market data polling loop and initializes the SQLite database on first run
- [x] **APP-02**: FastAPI serves the Next.js static export from `/` (all non-API paths return `index.html`)
- [x] **APP-03**: `GET /api/health` returns `{"status": "ok"}` for container health checks

### Streaming

- [ ] **STRM-01**: `GET /api/stream/prices` opens a long-lived SSE connection and pushes price updates for all watched tickers at ~500ms cadence
- [ ] **STRM-02**: Each SSE event contains ticker, price, prev_price, change_pct, and timestamp
- [ ] **STRM-03**: SSE endpoint reads from the shared `price_cache` singleton (not the data source directly)

### Database

- [x] **DB-01**: SQLite database is created and seeded automatically on first startup — no manual migration step
- [x] **DB-02**: Schema includes: `users_profile`, `watchlist`, `positions`, `trades`, `portfolio_snapshots`, `chat_messages` tables
- [x] **DB-03**: Default seed data: one user profile (`id="default"`, `cash_balance=10000.0`) and 10 default watchlist tickers (AAPL, GOOGL, MSFT, AMZN, TSLA, NVDA, META, JPM, V, NFLX)

### Portfolio

- [ ] **PORT-01**: `GET /api/portfolio` returns current positions, cash balance, total portfolio value, and unrealized P&L for each position
- [ ] **PORT-02**: `POST /api/portfolio/trade` executes a market order — buy or sell — at the current cached price with instant fill; validates sufficient cash (buy) or shares (sell)
- [ ] **PORT-03**: Successful trades update the `positions` table and debit/credit the `users_profile` cash balance atomically
- [ ] **PORT-04**: Each trade is appended to the `trades` table as an immutable log entry
- [ ] **PORT-05**: `GET /api/portfolio/history` returns portfolio value snapshots over time for the P&L chart
- [ ] **PORT-06**: A background task records a portfolio snapshot to `portfolio_snapshots` at a regular interval (e.g., every 30 seconds)

### Watchlist

- [ ] **WTCH-01**: `GET /api/watchlist` returns all watched tickers with their latest prices from the price cache
- [ ] **WTCH-02**: `POST /api/watchlist` adds a ticker to the watchlist; the polling loop picks it up on its next cycle
- [ ] **WTCH-03**: `DELETE /api/watchlist/{ticker}` removes a ticker from the watchlist

### LLM Chat

- [ ] **CHAT-01**: `POST /api/chat` accepts a user message and returns a streaming response (token-by-token) from the LLM
- [ ] **CHAT-02**: The backend constructs a prompt with current portfolio context (cash, positions with P&L, watchlist with live prices) and recent conversation history before calling the LLM
- [ ] **CHAT-03**: The LLM is called via LiteLLM → OpenRouter → Cerebras (`openrouter/openai/gpt-oss-120b`) with structured output matching `{message, trades[], watchlist_changes[]}`
- [ ] **CHAT-04**: Trades and watchlist changes in the LLM response are auto-executed before streaming the reply to the client
- [ ] **CHAT-05**: Each user message and assistant response (with executed actions) is persisted to the `chat_messages` table
- [ ] **CHAT-06**: When `LLM_MOCK=true`, the backend returns a deterministic mock response instead of calling OpenRouter

### Frontend — Core Layout

- [ ] **FE-01**: Single-page app with a dark terminal aesthetic (background ~#0d1117, accent yellow #ecad0a, blue #209dd7, purple #753991)
- [ ] **FE-02**: Header shows total portfolio value (live-updating), cash balance, and a connection status indicator dot (green/yellow/red)
- [ ] **FE-03**: Layout is desktop-first and optimized for wide screens

### Frontend — Watchlist

- [ ] **FE-04**: Watchlist panel shows all watched tickers with current price, daily change %, and a sparkline mini-chart (last 30 minutes of price action)
- [ ] **FE-05**: Price changes trigger a brief green (uptick) or red (downtick) background flash animation that fades over ~500ms via CSS transition
- [ ] **FE-06**: Clicking a ticker in the watchlist selects it as the active ticker for the main chart

### Frontend — Charts

- [ ] **FE-07**: Main chart area shows a price-over-time chart for the currently selected ticker
- [ ] **FE-08**: P&L chart shows total portfolio value over time using data from `GET /api/portfolio/history`

### Frontend — Portfolio

- [ ] **FE-09**: Portfolio heatmap (treemap) visualizes positions: each rectangle sized by portfolio weight, colored green (profit) or red (loss) by P&L
- [ ] **FE-10**: Positions table shows ticker, quantity, average cost, current price, unrealized P&L, and % change for each position

### Frontend — Trading

- [ ] **FE-11**: Trade bar has ticker input, quantity input, Buy button (purple submit), and Sell button; executes market orders via `POST /api/portfolio/trade`
- [ ] **FE-12**: Trade results update the positions table and portfolio display without a page reload

### Frontend — AI Chat

- [ ] **FE-13**: AI chat panel shows scrolling conversation history and a message input
- [ ] **FE-14**: Assistant responses stream token-by-token into the chat UI
- [ ] **FE-15**: Trade executions and watchlist changes triggered by the AI appear inline in the chat as confirmation messages

### Frontend — SSE Connection

- [ ] **FE-16**: Frontend uses native `EventSource` to connect to `GET /api/stream/prices` and updates the watchlist and header in real time
- [ ] **FE-17**: `EventSource` reconnects automatically on disconnect; the connection status dot reflects the current state

### Docker & Deployment

- [ ] **DOCK-01**: Multi-stage Dockerfile: Stage 1 (Node 20) builds the Next.js static export; Stage 2 (Python 3.12/uv) installs backend deps, copies the frontend build, and runs `uvicorn` on port 8000
- [ ] **DOCK-02**: The SQLite database persists across container restarts via a named Docker volume mounted at `/app/db`
- [ ] **DOCK-03**: `scripts/start_mac.sh` builds (if needed) and runs the container with volume, port 8000, and `.env` file; prints the URL
- [ ] **DOCK-04**: `scripts/stop_mac.sh` stops and removes the container without deleting the data volume
- [ ] **DOCK-05**: `scripts/start_windows.ps1` and `scripts/stop_windows.ps1` are PowerShell equivalents of the macOS scripts

### Testing

- [ ] **TEST-01**: Backend unit tests cover portfolio trade execution logic (buy, sell, insufficient cash, sell more than owned)
- [ ] **TEST-02**: Backend unit tests cover P&L calculations and portfolio summary
- [ ] **TEST-03**: Backend unit tests cover LLM structured output parsing (valid schema, malformed response)
- [ ] **TEST-04**: Backend unit tests cover API route response shapes and status codes
- [ ] **TEST-05**: Frontend unit tests cover price flash animation trigger on price change
- [ ] **TEST-06**: Frontend unit tests cover watchlist CRUD operations
- [ ] **TEST-07**: Playwright E2E test: fresh start — default watchlist with 10 tickers, $10k balance, prices streaming
- [ ] **TEST-08**: Playwright E2E test: add and remove a ticker from the watchlist
- [ ] **TEST-09**: Playwright E2E test: buy shares — cash decreases, position appears, portfolio updates
- [ ] **TEST-10**: Playwright E2E test: sell shares — cash increases, position updates or disappears
- [ ] **TEST-11**: Playwright E2E test: AI chat (mocked) — send a message, receive streamed response, trade execution appears inline

## v2 Requirements

### Notifications

- **NOTF-01**: User receives in-app notifications for AI-executed trades
- **NOTF-02**: Toast/alert on trade failure with reason

### Moderation / Admin

- **MOD-01**: Admin view of trade history across sessions

### Advanced Charts

- **CHART-01**: Volume indicators on main chart
- **CHART-02**: Technical overlays (moving averages)

### Cloud Deployment

- **CLOUD-01**: Terraform configuration for AWS App Runner deployment

## Out of Scope

| Feature | Reason |
|---------|--------|
| WebSocket connections | SSE is sufficient for one-way price push; bidirectional not needed |
| User authentication / multi-user | Single-user, `user_id="default"` hardcoded; auth adds complexity without course value |
| Limit orders / order book | Dramatically simpler portfolio math with market-only orders |
| Mobile app | Web-first, desktop-optimized; mobile is a future concern |
| Real brokerage integration | Simulated portfolio only — fake money, zero stakes |
| OAuth / magic link login | No auth layer at all |
| Video streaming or media uploads | Not relevant to trading terminal |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| APP-01 | Phase 1 | Complete |
| APP-02 | Phase 1 | Complete |
| APP-03 | Phase 1 | Complete |
| DB-01 | Phase 1 | Complete |
| DB-02 | Phase 1 | Complete |
| DB-03 | Phase 1 | Complete |
| STRM-01 | Phase 2 | Pending |
| STRM-02 | Phase 2 | Pending |
| STRM-03 | Phase 2 | Pending |
| PORT-01 | Phase 2 | Pending |
| PORT-02 | Phase 2 | Pending |
| PORT-03 | Phase 2 | Pending |
| PORT-04 | Phase 2 | Pending |
| PORT-05 | Phase 2 | Pending |
| PORT-06 | Phase 2 | Pending |
| WTCH-01 | Phase 2 | Pending |
| WTCH-02 | Phase 2 | Pending |
| WTCH-03 | Phase 2 | Pending |
| CHAT-01 | Phase 3 | Pending |
| CHAT-02 | Phase 3 | Pending |
| CHAT-03 | Phase 3 | Pending |
| CHAT-04 | Phase 3 | Pending |
| CHAT-05 | Phase 3 | Pending |
| CHAT-06 | Phase 3 | Pending |
| FE-01 | Phase 4 | Pending |
| FE-02 | Phase 4 | Pending |
| FE-03 | Phase 4 | Pending |
| FE-04 | Phase 4 | Pending |
| FE-05 | Phase 4 | Pending |
| FE-06 | Phase 4 | Pending |
| FE-07 | Phase 4 | Pending |
| FE-08 | Phase 4 | Pending |
| FE-09 | Phase 4 | Pending |
| FE-10 | Phase 4 | Pending |
| FE-11 | Phase 4 | Pending |
| FE-12 | Phase 4 | Pending |
| FE-13 | Phase 5 | Pending |
| FE-14 | Phase 5 | Pending |
| FE-15 | Phase 5 | Pending |
| FE-16 | Phase 4 | Pending |
| FE-17 | Phase 4 | Pending |
| DOCK-01 | Phase 6 | Pending |
| DOCK-02 | Phase 6 | Pending |
| DOCK-03 | Phase 6 | Pending |
| DOCK-04 | Phase 6 | Pending |
| DOCK-05 | Phase 6 | Pending |
| TEST-01 | Phase 2 | Pending |
| TEST-02 | Phase 2 | Pending |
| TEST-03 | Phase 3 | Pending |
| TEST-04 | Phase 2 | Pending |
| TEST-05 | Phase 4 | Pending |
| TEST-06 | Phase 4 | Pending |
| TEST-07 | Phase 6 | Pending |
| TEST-08 | Phase 6 | Pending |
| TEST-09 | Phase 6 | Pending |
| TEST-10 | Phase 6 | Pending |
| TEST-11 | Phase 6 | Pending |

**Coverage:**

- v1 requirements: 56 total
- Mapped to phases: 56
- Unmapped: 0 ✓

---
*Requirements defined: 2026-05-29*
*Last updated: 2026-05-29 after initial definition*
