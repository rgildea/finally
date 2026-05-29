# Codebase Concerns

**Analysis Date:** 2026-05-29

---

## Project Completeness

**Only the market data backend subsystem is implemented:**
- Problem: The plan specifies a full-stack application (FastAPI app, SQLite DB, SSE endpoints, portfolio endpoints, watchlist endpoints, LLM chat, frontend, Docker, E2E tests). Only `backend/app/market/` exists.
- Files: `backend/app/market/` (complete), everything else (absent)
- Impact: No runnable application exists. The Docker container, frontend, database schema, REST API routes, LLM integration, and E2E test infrastructure are all unbuilt.
- Fix approach: Build incrementally per the plan: FastAPI app shell → DB schema → SSE endpoint → portfolio endpoints → watchlist endpoints → LLM chat → frontend → Docker.

---

## Tech Debt

**No FastAPI application entry point:**
- Issue: `backend/app/__init__.py` is empty; no `main.py`, `app.py`, or `server.py` exists.
- Files: `backend/app/__init__.py`
- Impact: The market data modules cannot be wired to an HTTP server. `polling_loop`, `price_cache`, and the SSE endpoint have no host.
- Fix approach: Create `backend/app/main.py` with a FastAPI app, lifespan context that calls `source.start()` and launches `polling_loop`, and mounts static files for the frontend build.

**`price_cache.remove()` is not wired to the watchlist DELETE route:**
- Issue: `PriceCache.remove()` exists and is documented for use when a ticker is removed from the watchlist, but the DELETE route does not exist yet. When it is built, the cache eviction must be wired or stale prices will accumulate indefinitely.
- Files: `backend/app/market/cache.py:41`
- Impact: Cache grows unbounded as tickers are removed and re-added; stale prices persist after removal.
- Fix approach: When implementing `DELETE /api/watchlist/{ticker}`, call `await price_cache.remove(ticker)` and also call `source` (simulator)-level cleanup if needed.

**No `.env.example` committed:**
- Issue: The plan specifies `OPENROUTER_API_KEY` and optionally `MASSIVE_API_KEY` and `LLM_MOCK`. No `.env.example` exists at the repo root for developer onboarding.
- Files: (absent — should be at `/finally/.env.example`)
- Impact: New developers have no reference for required environment variables.
- Fix approach: Add `.env.example` with all three keys documented and safe placeholder values.

**`litellm` and `aiofiles` not in `pyproject.toml`:**
- Issue: The LLM chat feature requires `litellm` (per the cerebras skill). SQLite operations may require `aiosqlite`. Neither is listed as a dependency.
- Files: `backend/pyproject.toml`
- Impact: Building the chat feature will fail at import time until these are added.
- Fix approach: `uv add litellm aiosqlite` when implementing those features.

**No ruff configuration section in `pyproject.toml`:**
- Issue: `ruff` is a dev dependency but there is no `[tool.ruff]` section configuring line length, selected rules, or ignored rules.
- Files: `backend/pyproject.toml`
- Impact: Linting behavior is governed by ruff defaults, which may conflict with the project style as more code is added.
- Fix approach: Add a minimal `[tool.ruff]` section with `line-length = 100` and select relevant rule sets (E, F, I).

**No test coverage enforcement:**
- Issue: pytest config has no `--cov` or coverage requirements. As more modules are added (API routes, portfolio logic, LLM parsing), coverage can erode silently.
- Files: `backend/pyproject.toml`
- Impact: Critical paths may ship untested.
- Fix approach: Add `addopts = "--cov=app --cov-fail-under=80"` to `[tool.pytest.ini_options]` once `pytest-cov` is added.

---

## Security Considerations

**Massive API key transmitted in URL query parameter:**
- Risk: `apiKey` is appended as a query parameter (`?apiKey=...`). Query parameters appear in server access logs, browser history, HTTP referrer headers, and reverse-proxy logs — anywhere the URL is logged.
- Files: `backend/app/market/massive.py:63-68`
- Current mitigation: None. The Massive API requires this format per their REST spec.
- Recommendations: The Massive API also supports an `Authorization: Bearer <key>` header per the archive docs. Prefer the header approach if possible to keep the key out of URLs. If the query param is the only option per plan, document the risk explicitly.

**No input validation on ticker symbols:**
- Risk: Watchlist endpoints (not yet built) will accept ticker strings from untrusted user input. Without validation, arbitrary strings could be passed to the Massive API URL or stored in the SQLite database.
- Files: (future `backend/app/api/watchlist.py`)
- Current mitigation: Not applicable — routes not built yet.
- Recommendations: When implementing watchlist endpoints, validate tickers against a regex like `^[A-Z]{1,5}$` before use. Reject anything else with a 400 response.

**No authentication on any endpoints:**
- Risk: The plan explicitly has no auth (single user, simulated money), but the `/api/chat` endpoint will call an external LLM (cost center). Any exposure of port 8000 allows anyone to make LLM calls.
- Files: (future `backend/app/main.py`)
- Current mitigation: Not applicable — application not built yet.
- Recommendations: Document that port 8000 should not be exposed publicly. Consider a basic rate limiter on `/api/chat` (e.g., 10 requests/minute via `slowapi`) to limit abuse cost.

---

## Performance Bottlenecks

**`price_cache.get_all()` acquires a lock and copies the full dict on every SSE push cycle:**
- Problem: The SSE endpoint will call `price_cache.get_all()` every 500ms per connected client. Each call acquires `asyncio.Lock` and does a `dict()` shallow copy. With many connected clients and many tickers this creates contention.
- Files: `backend/app/market/cache.py:45-48`
- Cause: The lock copy pattern is correct for safety but does unnecessary work if the SSE endpoint only needs a snapshot.
- Improvement path: For the initial single-user use case this is not a bottleneck. If multi-client SSE is needed, consider a lock-free snapshot mechanism or a fan-out broadcast queue.

**GBM simulator runs even when no clients are connected:**
- Problem: `polling_loop` runs continuously even if no SSE clients are subscribed and no frontend is connected.
- Files: `backend/app/market/loop.py`
- Cause: Background task has no awareness of subscriber count.
- Improvement path: Acceptable for this use case (single user, always-on). No action needed unless power consumption is a concern.

---

## Fragile Areas

**Timing-dependent tests in `test_simulator.py`:**
- Files: `backend/tests/market/test_simulator.py:41-50`, `backend/tests/market/test_simulator.py:66-79`
- Why fragile: Two tests call `asyncio.sleep(1.0)` to let the GBM run, then assert prices are within ±10% of seed values. If a random event fires on a high-sigma ticker (TSLA σ=0.65) during the sleep window, the price could drift outside the ±10% bound, causing a spurious failure.
- Safe modification: These tests are probabilistically safe (the window is wide relative to 1 second of drift). Do not tighten the bounds. If flakiness is observed, either seed `random` before the test or disable random events in the test config.
- Test coverage: Covered — just statistically fragile.

**`test_loop.py` fixture clears cache internal state directly:**
- Files: `backend/tests/market/test_loop.py:25-27`
- Why fragile: The `clear_global_cache` fixture calls `cache_module.price_cache._data.clear()` — direct mutation of a private attribute, bypassing `asyncio.Lock`. Works today because no concurrent tasks run between tests, but would be unsafe if the fixture contract changes.
- Safe modification: Add a `reset()` method to `PriceCache` that acquires the lock for clearing, or keep the direct `_data.clear()` but document that it is fixture-only.
- Test coverage: The risk is in the fixture, not production code.

**`demo.py` imports private module members:**
- Files: `backend/demo.py:29-31`
- Why fragile: `demo.py` imports `_DEFAULT_TICKERS` and `_DEFAULT_CORRELATIONS` (module-private by convention). If these names are changed or the module refactored, the demo breaks silently.
- Safe modification: Export these constants via `simulator.__all__` or move them to a dedicated `constants.py`. Alternatively, accept the fragility since `demo.py` is a development script, not production code.

**`MarketSimulator._prices` is shared between `get_prices()` and `_tick()`:**
- Files: `backend/app/market/simulator.py:72`, `backend/app/market/simulator.py:154`
- Why fragile: `_tick()` mutates `self._prices` in the asyncio background task. `get_prices()` reads the same dict in the same event loop without a lock. In Python's asyncio (single-threaded), this is safe because `_tick()` only mutates between `await` points and `get_prices()` does not have an intermediate `await` during the read. However, this relies on an implicit concurrency assumption that is not documented and could break if `get_prices()` is ever made more complex.
- Safe modification: Document the concurrency invariant explicitly with a comment, or add an `asyncio.Lock` to `_prices` access if the code is extended.

---

## Scaling Limits

**SQLite single-file database (planned, not yet built):**
- Current capacity: Not yet implemented.
- Limit: SQLite handles a single writer at a time. For the single-user use case this is fine. Concurrent write bursts (e.g., portfolio snapshots being written while a trade executes) could serialise under write lock.
- Scaling path: The plan explicitly chose SQLite for simplicity. Add WAL mode (`PRAGMA journal_mode=WAL`) when the DB is initialised to improve read concurrency.

**Price cache is in-memory only:**
- Current capacity: Holds one `PriceUpdate` per ticker. With 10 default tickers plus dynamically added ones, the footprint is negligible.
- Limit: Prices are lost on restart. Historical prices for sparklines and the P&L chart rely on the database (not yet built); without it there is no price history on reconnect.
- Scaling path: Acceptable for the planned architecture. The P&L chart uses `portfolio_snapshots` from SQLite, not the cache.

---

## Dependencies at Risk

**`ruff>=0.15.14` pins a non-existent version:**
- Risk: As of analysis date, ruff's latest release is in the 0.x series but 0.15.x does not exist. The `>=0.15.14` constraint will fail to resolve if a compatible version is unavailable on PyPI.
- Files: `backend/pyproject.toml:32`
- Impact: `uv sync --group dev` may fail or install an unexpected version.
- Migration plan: Verify the correct version string against PyPI and pin to an existing release such as `ruff>=0.4.0`.

**Broad version floor constraints (`>=`) for all production dependencies:**
- Risk: `fastapi>=0.111`, `pydantic>=2.7`, `httpx>=0.27` have no upper bounds. A major version bump could introduce breaking changes that go undetected until deployment.
- Files: `backend/pyproject.toml:6-11`
- Impact: Low for now (stable libraries), higher as the codebase grows and more APIs are used.
- Migration plan: Add upper bounds when LLM and database features are implemented, or lock to specific versions in `uv.lock` (already present).

---

## Missing Critical Features

**No FastAPI application shell:**
- Problem: `polling_loop`, `price_cache`, and the SSE stream have no HTTP host. The market data layer is complete but cannot serve requests.
- Blocks: Everything — frontend, portfolio, watchlist, chat, Docker deployment.

**No database layer:**
- Problem: SQLite schema, init logic, and all persistence (users, positions, trades, snapshots, chat messages) are unbuilt.
- Blocks: Portfolio tracking, P&L chart, trade history, chat history, watchlist persistence across restarts.

**No frontend:**
- Problem: Next.js frontend does not exist. The Docker multi-stage build references a `frontend/` directory that is absent.
- Blocks: Any UI rendering; Docker image build would fail.

**No Dockerfile or start scripts:**
- Problem: The Docker container, `scripts/start_mac.sh`, and all deployment infrastructure are absent.
- Blocks: The user-facing "run one command" experience described in the plan.

**No E2E test infrastructure:**
- Problem: The `test/` directory with Playwright and `docker-compose.test.yml` does not exist.
- Blocks: End-to-end verification of the complete application.

**LLM dependencies not installed:**
- Problem: `litellm` is not in `pyproject.toml`. The chat feature and structured output parsing (per the cerebras skill) cannot be implemented without it.
- Blocks: `POST /api/chat` endpoint; any LLM-driven trade execution.

---

## Test Coverage Gaps

**No tests for future API route handlers:**
- What's not tested: Portfolio endpoints (`/api/portfolio`, `/api/portfolio/trade`, `/api/portfolio/history`), watchlist endpoints, SSE endpoint, chat endpoint.
- Files: (future `backend/app/api/`)
- Risk: Route logic, validation, database integration, and error handling have no coverage.
- Priority: High — these are the core application features.

**No tests for database initialization and schema:**
- What's not tested: Lazy DB init on first request, schema creation, seed data insertion, idempotency of multiple startups.
- Files: (future `backend/app/db/`)
- Risk: Database corruption or missing seed data could break the application silently.
- Priority: High.

**No tests for LLM structured output parsing:**
- What's not tested: JSON schema validation, trade extraction, watchlist change extraction, malformed response handling, LLM mock mode.
- Files: (future `backend/app/chat/`)
- Risk: LLM parsing failures could cause silent trade execution errors or crashes.
- Priority: High.

**No integration test connecting polling loop to SSE endpoint:**
- What's not tested: The full path from `MarketSimulator` → `polling_loop` → `price_cache` → SSE event push → client-side event format.
- Files: `backend/app/market/loop.py`, (future SSE endpoint)
- Risk: The SSE format sent to clients could be wrong even if individual units pass.
- Priority: Medium.

---

*Concerns audit: 2026-05-29*
